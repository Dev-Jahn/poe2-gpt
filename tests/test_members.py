from contextlib import AsyncExitStack
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from poe2_companion.access import AccessConfig, AccessVerifier, CloudflareAccessMiddleware
from poe2_companion.builds import BuildReader
from poe2_companion.deployment import render_member_stack, validate_members
from poe2_companion.engine import EngineClient
from poe2_companion.engine_models import ENGINE_COMMIT, EngineError
from poe2_companion.engine_worker import PrivateEngine, worker_app
from poe2_companion.equipment import EquipmentService
from poe2_companion.scout import Scout
from poe2_companion.server import build_server
from poe2_companion.trade import TradeClient
from test_access import CONFIG, jwk, token
from test_build_boundary import imported as import_build, MARKER
from test_equipment import imported as import_equipment, NOW, optimizer
from test_scout import Backend
from test_trade import TradeBackend

MEMBERS = [
    {"id": "alice", "email": "alice@example.com", "port": 18082, "enabled": True},
    {"id": "bob", "email": "bob@example.com", "port": 18083, "enabled": True},
]


def test_member_identity_is_unique_and_retirement_does_not_reassign_data():
    validate_members(MEMBERS, "owner@example.com")
    invalid = [
        [*MEMBERS, {"id": "third", "email": "third@example.com", "port": 18084, "enabled": True}],
        [{**MEMBERS[0], "id": "../../bob"}], [{**MEMBERS[0], "email": "OWNER@example.com"}],
        [{**MEMBERS[0], "port": 18081}], [{**MEMBERS[0], "enabled": "false"}],
        [{**MEMBERS[0], "enabled": False}, {**MEMBERS[1], "id": "alice"}],
        [MEMBERS[0], {**MEMBERS[1], "email": "ALICE@example.com"}],
    ]
    for members in invalid:
        with pytest.raises(ValueError):
            validate_members(members, "owner@example.com")


def test_renderer_preserves_owner_and_separates_private_volumes():
    base = {"services": {
        "poe2-companion": {"image": "mcp:local", "command": ["--transport", "streamable-http"],
            "environment": {"POE2_CF_OWNER_EMAIL": "owner@example.com"},
            "depends_on": {"pob-engine": {"condition": "service_healthy"}},
            "volumes": [{"type": "volume", "source": n, "target": "/" + n}
                        for n in ("prices", "engine-socket", "build-projections")]},
        "pob-engine": {"image": "engine:local", "build": {"context": "."}, "network_mode": "none",
            "volumes": [{"type": "volume", "source": n, "target": "/" + n}
                        for n in ("private-builds", "engine-socket", "engine-coordination")]},
        "pob-import": {"image": "mcp:local", "volumes": [{"type": "volume", "source": "private-builds", "target": "/private-builds"}]}},
        "volumes": {n: {"name": "poe2_" + n} for n in ("private-builds", "engine-socket", "build-projections", "prices", "engine-coordination")}}
    before = deepcopy(base)
    stack = render_member_stack(base, MEMBERS)
    assert base == before
    assert stack["services"]["poe2-companion"] == base["services"]["poe2-companion"]
    for member in MEMBERS:
        identity = member["id"]
        mcp = stack["services"]["poe2-companion-" + identity]
        assert mcp["environment"]["POE2_CF_OWNER_EMAIL"] == member["email"]
        assert mcp["command"][-1] == f"/u/{identity}/mcp"
        assert mcp["ports"][0]["host_ip"] == "127.0.0.1"
        mounts = {v["source"] for v in mcp["volumes"]}
        assert mounts == {"prices", "engine-socket-" + identity, "build-projections-" + identity}
        assert stack["volumes"]["private-builds-" + identity]["name"] == "poe2_private-builds-" + identity
        worker = stack["services"]["pob-engine-" + identity]
        assert worker["network_mode"] == "none" and "build" not in worker
        assert {v["source"] for v in worker["volumes"]} == {
            "private-builds-" + identity, "engine-socket-" + identity, "engine-coordination"}
    retired = render_member_stack(base, [{**MEMBERS[0], "enabled": False}])
    assert retired == base


def test_shared_compute_lease_is_exclusive_and_released_on_errors(tmp_path):
    engines = [PrivateEngine(tmp_path, tmp_path, lock_file=tmp_path / "compute.lock") for _ in range(2)]
    with pytest.raises(RuntimeError):
        with engines[0].compute_lease():
            with pytest.raises(EngineError, match="engine_busy"):
                with engines[1].compute_lease():
                    pytest.fail("Second worker acquired the lease")
            raise RuntimeError("Simulated calculation failure")
    with engines[1].compute_lease():
        pass
    (tmp_path / "wrong.lock").symlink_to(tmp_path / "compute.lock")
    engines[1].lock_file = tmp_path / "wrong.lock"
    with pytest.raises(EngineError, match="engine_busy"):
        with engines[1].compute_lease():
            pytest.fail("Must not follow lock symlinks")


async def test_known_foreign_build_dataset_search_and_spoofed_identity_are_denied(tmp_path):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    (engine_dir / "COMPANION_COMMIT").write_text(ENGINE_COMMIT)
    users = []
    async with AsyncExitStack() as stack:
        for index, member in enumerate(MEMBERS):
            root = tmp_path / member["id"]
            root.mkdir()
            build_id, private, projections, _ = import_build(root)
            dataset_id, equipment_dir = import_equipment(root)
            scout = Scout(user_agent="test", transport=httpx.MockTransport(Backend()), interval=0)
            trade = TradeClient("test", transport=httpx.MockTransport(TradeBackend()), interval=0, clock=lambda: NOW)
            worker = PrivateEngine(private, engine_dir)
            engine = EngineClient("/unused", http=httpx.AsyncClient(
                transport=httpx.ASGITransport(app=worker_app(worker)), base_url="http://worker"))
            access = AccessVerifier(AccessConfig(CONFIG.issuer, CONFIG.audience, member["email"]),
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": [jwk()]})))
            for resource in (scout, trade, engine, access):
                stack.push_async_callback(resource.close)
            path = f"/u/{member['id']}/mcp"
            server = build_server(scout, build_reader=BuildReader(projections),
                equipment=EquipmentService(equipment_dir, scout, clock=lambda: NOW), trade=trade, engine=engine, mcp_path=path)
            app = server.streamable_http_app()
            await stack.enter_async_context(app.router.lifespan_context(app))
            client = await stack.enter_async_context(httpx.AsyncClient(base_url="http://localhost:8000",
                transport=httpx.ASGITransport(app=CloudflareAccessMiddleware(app, access)),
                headers={"Cf-Access-Jwt-Assertion": token(email=member["email"]),
                         "Accept": "application/json, text/event-stream"}))
            users.append({"client": client, "path": path, "build": build_id, "dataset": dataset_id})

        async def call(user, name, arguments):
            result = await user["client"].post(user["path"], json={"jsonrpc": "2.0", "id": 1,
                "method": "tools/call", "params": {"name": name, "arguments": arguments}})
            assert result.status_code == 200
            assert MARKER not in result.text
            return result.json()["result"]

        for user in users:
            assert not (await call(user, "get_build_summary", {"build_id": user["build"]})).get("isError")
            assert not (await call(user, "optimize_equipment_upgrades", {"request": optimizer(user["dataset"]).model_dump()})).get("isError")
            search = await call(user, "search_trade_equipment", {"request": {"category": "accessory.ring"}})
            user["search"] = search["structuredContent"]["search_id"]

        for index, user in enumerate(users):
            other = users[1-index]
            for name, arguments in [
                ("get_build_summary", {"build_id": other["build"]}),
                ("recalculate_build", {"request": {"build_id": other["build"]}}),
                ("get_equipment_dataset", {"request": {"dataset_id": other["dataset"]}}),
                ("optimize_equipment_upgrades", {"request": optimizer(other["dataset"]).model_dump()}),
                ("get_trade_search_results", {"request": {"search_id": other["search"]}}),
                ("get_build_summary", {"build_id": other["build"], "user_id": MEMBERS[1-index]["id"]}),
            ]:
                assert (await call(user, name, arguments))["isError"]
            # Even when a valid JWT is sent to the other person's actual backend,
            # the signed email decides access. Unsigned identity headers do not.
            response = await other["client"].post(other["path"], headers={
                "Cf-Access-Jwt-Assertion": token(email=MEMBERS[index]["email"]),
                "Cf-Access-Authenticated-User-Email": MEMBERS[1-index]["email"],
                "X-User-Id": MEMBERS[1-index]["id"]}, content=b"must-not-be-read-or-echoed")
            assert response.status_code == 403 and response.json() == {"error": "access_denied"}
            root_response = await user["client"].post("/mcp", json={})
            assert root_response.status_code == 404
