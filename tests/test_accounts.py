"""Account isolation, credential lifecycle, browser consent and MCP contracts."""
from contextlib import AsyncExitStack, asynccontextmanager
import asyncio
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

import httpx
from jsonschema import Draft202012Validator
import pytest

from poe2_companion.access import AccessVerifier, CloudflareAccessMiddleware, Principal
from poe2_companion.accounts import AccountClient, AccountView, BrokerError
from poe2_companion.account_store import AccountStore, StoreError
from poe2_companion.account_oauth import GGGOAuth, OAuthConfig, OAuthError
from poe2_companion.account_broker import AccountBroker, RPC, create_app, configure_oauth
from poe2_companion.account_ui import AccountUI
from poe2_companion.scout import Scout
from poe2_companion.server import build_server
from poe2_companion.trade import TradeClient
from test_access import CONFIG, jwk, token
from test_scout import Backend
from test_trade import TradeBackend

SUB = "11111111-2222-4333-8444-555555555555"
HOST = "accounts.example.test"
BASE = "https://" + HOST
NOW = 1800000000
SECRET = "NEVER-EXPOSE-REFRESH-CREDENTIAL"


def grant(**changes):
    return {"access_token": "NEVER-EXPOSE-ACCESS-CREDENTIAL", "refresh_token": SECRET,
            "expires_in": 28 * 86400, "token_type": "bearer", "scope": "account:profile", "sub": SUB, **changes}


class ProviderBackend:
    def __init__(self):
        self.requests = []
        self.failure = None
        self.profile_id = SUB
        self.started = self.release = None

    async def __call__(self, request):
        self.requests.append(request)
        assert "cookie" not in request.headers
        if self.started:
            self.started.set()
            await self.release.wait()
        if self.failure:
            return self.failure
        if request.url.path == "/profile":
            assert request.headers["authorization"].startswith("Bearer ")
            return httpx.Response(200, json={"uuid": self.profile_id, "name": "Test#1234"})
        assert str(request.url) == "https://www.pathofexile.com/oauth/token"
        data = parse_qs(request.content.decode())
        assert data["client_id"] == ["test-client"] and data["client_secret"] == ["private-client-secret"]
        if data["grant_type"] == ["refresh_token"]:
            return httpx.Response(200, json=grant(refresh_token=SECRET + "-rotated"))
        return httpx.Response(200, json=grant())


@asynccontextmanager
async def environment(tmp_path, *, configured=True, member="owner"):
    clock = [NOW]
    store = AccountStore(tmp_path / "state", tmp_path / "keys/master.key", member, clock=lambda: clock[0])
    provider = ProviderBackend()
    path = ("" if member == "owner" else "/u/" + member) + "/accounts"
    oauth = GGGOAuth(OAuthConfig("test-client", "private-client-secret", "test@example.com"), BASE + path + "/callback",
                     transport=httpx.MockTransport(provider)) if configured else None
    broker = AccountBroker(store, BASE, path, oauth)
    private = AccountClient("/unused", http=httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(broker)), base_url="http://broker"))
    scout = Scout(user_agent="test", transport=httpx.MockTransport(Backend()), interval=0)
    trade = TradeClient("test", transport=httpx.MockTransport(TradeBackend()), interval=0)
    server = build_server(scout, accounts=private, trade=trade, allowed_hosts=[HOST], mcp_path=path.removesuffix("/accounts") + "/mcp")
    app = server.streamable_http_app()
    access = AccessVerifier(CONFIG, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"keys": [jwk()]})))
    cookie = "__Secure-poe2-account-" + member
    secured = CloudflareAccessMiddleware(AccountUI(app, private, BASE, path, cookie), access, account_path=path, account_cookie=cookie)
    async with AsyncExitStack() as stack:
        for resource in (oauth, private, scout, trade, access):
            if resource:
                stack.push_async_callback(resource.close)
        await stack.enter_async_context(app.router.lifespan_context(app))
        client = await stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(app=secured), base_url=BASE,
            headers={"Cf-Access-Jwt-Assertion": token(), "Accept": "application/json, text/event-stream"}))
        try:
            yield store, broker, client, clock, provider, path, server
        finally:
            store.close()


async def call(client, name, request, path="/mcp"):
    response = await client.post(path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": {"request": request}}})
    assert response.status_code == 200, response.text
    return response.json()["result"]


async def start_link(client, path):
    page = await client.get(path)
    assert page.status_code == 200, page.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
    response = await client.post(path + "/start", data={"csrf": csrf}, headers={"Origin": BASE})
    assert response.status_code == 303, response.text
    query = parse_qs(urlsplit(response.headers["location"]).query)
    return csrf, query


async def test_authenticated_mcp_empty_contract_and_cross_subject_isolation(tmp_path):
    async with environment(tmp_path, configured=False) as (store, broker, client, clock, provider, path, server):
        schemas = {tool.name: tool.outputSchema for tool in await server.list_tools()}
        empty = await call(client, "get_game_accounts", {})
        assert not empty.get("isError") and empty["structuredContent"]["records"] == []
        Draft202012Validator(schemas["get_game_accounts"]).validate(empty["structuredContent"])
        result = await call(client, "register_game_account", {"account_name": "Test#1234"})
        account = result["structuredContent"]["account"]
        assert account["verified"] is False and account["session_status"] == "unverified"
        repeat = await call(client, "register_game_account", {"account_name": "Test#1234"})
        assert repeat["structuredContent"]["account"]["account_id"] == account["account_id"]
        selected = await call(client, "set_default_game_account", {"account_id": account["account_id"]})
        assert selected["structuredContent"]["account"]["default_for_travel"]
        absent = await call(client, "get_game_connection_status", {"account_id": "acct_" + "f" * 32})
        assert absent["structuredContent"]["status"] == "not_found"
        link = await call(client, "begin_game_account_link", {})
        assert link["structuredContent"]["status"] == "provider_not_configured"
        assert link["structuredContent"]["url"] == BASE + path
        bad = await call(client, "register_game_account", {"account_name": "Test#1234", "cookie": SECRET})
        assert bad["isError"] and SECRET not in json.dumps(bad)
        client.headers["Cf-Access-Jwt-Assertion"] = token(sub="different-subject-same-email")
        denied = await call(client, "get_game_accounts", {})
        assert denied["structuredContent"]["status"] == "identity_mismatch" and denied["structuredContent"]["records"] == []
        client.headers["Cf-Access-Jwt-Assertion"] = token(email="other@example.com")
        assert (await client.get(path)).status_code == 403


async def test_oauth_browser_pkce_csrf_account_verification_and_disconnect(tmp_path):
    async with environment(tmp_path) as (store, broker, client, clock, provider, path, server):
        csrf, query = await start_link(client, path)
        assert query["scope"] == ["account:profile"] and query["code_challenge_method"] == ["S256"]
        assert query["redirect_uri"] == [BASE + path + "/callback"]
        # GET/HEAD and cross-origin POST cannot start a login or game action.
        before = len(provider.requests)
        assert (await client.get(path + "/start")).status_code == 405
        assert (await client.head(path + "/start")).status_code == 405
        assert (await client.post(path + "/start", data={"csrf": csrf}, headers={"Origin": "https://evil.test"})).status_code == 403
        assert len(provider.requests) == before
        failed = await client.get(path + "/callback", params={"code": "code", "state": "f" * 64})
        assert failed.status_code == 400
        response = await client.get(path + "/callback", params={"code": "code", "state": query["state"][0]})
        assert response.status_code == 303
        assert len(provider.requests) == 2
        sent = parse_qs(provider.requests[0].content.decode())
        import base64, hashlib
        challenge = base64.urlsafe_b64encode(hashlib.sha256(sent["code_verifier"][0].encode()).digest()).rstrip(b"=").decode()
        assert challenge == query["code_challenge"][0]
        result = (await call(client, "get_game_accounts", {}))["structuredContent"]
        account = result["records"][0]
        assert account["verified"] and account["refresh_absolute_expires_at"] == NOW + 90 * 86400
        assert SECRET not in json.dumps(result) and "access_token" not in json.dumps(result)
        replay = await client.get(path + "/callback", params={"code": "code", "state": query["state"][0]})
        assert replay.status_code == 400 and len(provider.requests) == 2
        row = store.row(account["account_id"])
        assert SECRET not in row["secret"]
        for file in (tmp_path / "state").iterdir():
            assert SECRET.encode() not in file.read_bytes()
        disconnected = await client.post(path + "/disconnect", data={"csrf": csrf, "account_id": account["account_id"]}, headers={"Origin": BASE})
        assert disconnected.status_code == 200 and "공식 계정" in disconnected.text
        assert store.row(account["account_id"])["secret"] is None


async def test_cookie_binding_and_profile_mismatch_are_not_linked(tmp_path):
    async with environment(tmp_path) as (store, broker, client, clock, provider, path, server):
        csrf, query = await start_link(client, path)
        saved = dict(client.cookies.items())
        client.cookies.clear()
        assert (await client.get(path + "/callback", params={"code": "code", "state": query["state"][0]})).status_code == 400
        assert not provider.requests
        for name, value in saved.items():
            client.cookies.set(name, value, domain=HOST, path=path)
        provider.profile_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        assert (await client.get(path + "/callback", params={"code": "code", "state": query["state"][0]})).status_code == 400
        assert store.db.execute("SELECT count(*) FROM accounts").fetchone()[0] == 0


async def test_refresh_rotation_absolute_expiry_concurrency_and_restart(tmp_path):
    clock = [NOW]
    store = AccountStore(tmp_path / "state", tmp_path / "keys/master.key", "owner", clock=lambda: clock[0])
    provider = ProviderBackend()
    oauth = GGGOAuth(OAuthConfig("test-client", "private-client-secret", "test@example.com"), BASE + "/accounts/callback", transport=httpx.MockTransport(provider))
    broker = AccountBroker(store, BASE, "/accounts", oauth)
    account = store.save_grant(SUB, "Test#1234", grant(), NOW)
    identity = account.account_id
    clock[0] += 28 * 86400
    await asyncio.gather(*(broker.refresh_due() for _ in range(8)))
    row = store.row(identity)
    assert len(provider.requests) == 1 and row["version"] == 2
    assert row["refresh_exp"] == NOW + 90 * 86400
    assert store.unseal(f"credential:{identity}:2", row["secret"])["refresh_token"] == SECRET + "-rotated"
    store.close()
    store = AccountStore(tmp_path / "state", tmp_path / "keys/master.key", "owner", clock=lambda: clock[0])
    assert store.view(store.row(identity)).verified
    assert store.row(identity)["refresh_exp"] == NOW + 90 * 86400
    broker.store = store
    clock[0] = NOW + 90 * 86400
    await broker.refresh_due()
    assert len(provider.requests) == 1  # expired refresh token must never be submitted
    store.db.execute("UPDATE accounts SET refreshing=1 WHERE id=?", (identity,))
    store.close()
    store = AccountStore(tmp_path / "state", tmp_path / "keys/master.key", "owner", clock=lambda: clock[0])
    assert store.row(identity)["status"] == "reauth_required"
    store.close()
    await oauth.close()


@pytest.mark.parametrize("failure,expected", [
    (httpx.Response(429, headers={"Retry-After": "120"}), "active"),
    (httpx.Response(400, json={"error": "invalid_grant", "secret": SECRET}), "reauth_required"),
    (httpx.Response(503), "reauth_required"),
    (httpx.Response(200, text="not JSON " + SECRET), "reauth_required"),
])
async def test_refresh_failure_preserves_connection_and_never_echoes_secret(tmp_path, failure, expected):
    async with environment(tmp_path) as (store, broker, client, clock, provider, path, server):
        account = store.save_grant(SUB, "Test#1234", grant(expires_in=100), NOW)
        provider.failure = failure
        clock[0] += 95
        await broker.refresh_due()
        row = store.row(account.account_id)
        assert row["status"] == expected and not row["refreshing"]
        assert row["refresh_exp"] == NOW + 90 * 86400
        if expected == "active":
            assert row["next_refresh"] == clock[0] + 120
        assert SECRET not in json.dumps(store.view(row).model_dump())


async def test_disconnect_during_refresh_cannot_restore_secret(tmp_path):
    async with environment(tmp_path) as (store, broker, client, clock, provider, path, server):
        account = store.save_grant(SUB, "Test#1234", grant(expires_in=100), NOW)
        clock[0] += 95
        provider.started, provider.release = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(broker.refresh_due())
        await provider.started.wait()
        store.disconnect(account.account_id)
        provider.release.set()
        await pending
        row = store.row(account.account_id)
        assert row["status"] == "disconnected" and row["secret"] is None


async def test_provider_cooldown_covers_other_accounts_and_login(tmp_path):
    async with environment(tmp_path) as (store, broker, client, clock, provider, path, server):
        store.save_grant(SUB, "First#1234", grant(expires_in=100), NOW)
        other = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        store.save_grant(other, "Second#1234", grant(sub=other, expires_in=100), NOW)
        provider.failure = httpx.Response(429, headers={"Retry-After": "120"})
        clock[0] += 95
        await broker.refresh_due()
        assert len(provider.requests) == 1
        with pytest.raises(OAuthError, match="rate_limited"):
            await broker.oauth.exchange("fresh-code", "verifier")
        assert len(provider.requests) == 1


async def test_disconnect_during_callback_cannot_reconnect(tmp_path):
    async with environment(tmp_path) as (store, broker, client, clock, provider, path, server):
        old = store.register("ggg", "Test#1234")
        csrf, query = await start_link(client, path)
        provider.started, provider.release = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(client.get(path + "/callback", params={"code": "code", "state": query["state"][0]}))
        await provider.started.wait()
        store.disconnect(old.account_id)
        provider.release.set()
        assert (await pending).status_code == 400
        assert store.row(old.account_id)["status"] == "disconnected"


async def test_handoff_uses_owned_listing_and_keeps_selected_account(tmp_path):
    async with environment(tmp_path, configured=False) as (store, broker, client, clock, provider, path, server):
        first = (await call(client, "register_game_account", {"account_name": "First#1234"}))["structuredContent"]["account"]
        second = (await call(client, "register_game_account", {"account_name": "Second#5678"}))["structuredContent"]["account"]
        search = (await call(client, "search_trade_equipment", {"category": "armour.helmet"}))["structuredContent"]
        req = {"search_id": search["search_id"], "listing_ref": search["items"][0]["listing_ref"]}
        assert (await call(client, "prepare_hideout_travel", req))["structuredContent"]["status"] == "account_selection_required"
        await call(client, "set_default_game_account", {"account_id": first["account_id"]})
        handoff = (await call(client, "prepare_hideout_travel", req))["structuredContent"]
        assert handoff["status"] == "prepared" and handoff["mode"] == "official_site"
        assert handoff["game_action_executed"] is False and handoff["website_account_verified"] is False
        assert handoff["url"] == search["website_url"]
        await call(client, "set_default_game_account", {"account_id": second["account_id"]})
        receipt = (await call(client, "get_hideout_travel_result", {"intent_id": handoff["intent_id"]}))["structuredContent"]
        assert receipt["account_id"] == first["account_id"]
        foreign = await call(client, "prepare_hideout_travel", {**req, "listing_ref": "f" * 64})
        assert foreign["structuredContent"]["status"] == "listing_unavailable"
        clock[0] += 121
        assert store.intent(handoff["intent_id"]).status == "expired" and store.intent(handoff["intent_id"]).url is None
        store.disconnect(first["account_id"])
        assert store.intent(handoff["intent_id"]).status == "cancelled"
        assert not provider.requests
        kakao = store.register("kakao", "Kakao#1234")
        unsupported = await call(client, "prepare_hideout_travel", {**req, "account_id": kakao.account_id})
        assert unsupported["structuredContent"]["status"] == "provider_not_supported"
        assert unsupported["structuredContent"]["url"] is None


def test_key_identity_permissions_quotas_and_config(tmp_path):
    state, key = tmp_path / "state", tmp_path / "keys/master.key"
    store = AccountStore(state, key, "alice", clock=lambda: NOW)
    store.authorize("a" * 64)
    with pytest.raises(StoreError, match="identity_mismatch"):
        store.authorize("b" * 64)
    for i in range(16):
        store.register("ggg", f"Test{i}#1234")
    with pytest.raises(StoreError, match="limit_reached"):
        store.register("ggg", "Extra#1234")
    store.close()
    with pytest.raises(ValueError, match="member_mismatch"):
        AccountStore(state, key, "bob")
    original = key.read_bytes()
    key.unlink()
    with pytest.raises(FileNotFoundError):
        AccountStore(state, key, "alice")
    key.write_bytes(original)
    key.chmod(0o644)
    with pytest.raises(ValueError, match="permissions"):
        AccountStore(state, key, "alice")
    folder = tmp_path / "config"
    assert OAuthConfig.load(folder / "oauth.json") is None
    configure_oauth(folder, json.dumps({"client_id": "test-client", "client_secret": "secret", "contact": "a@example.com"}).encode())
    assert OAuthConfig.load(folder / "oauth.json").client_id == "test-client"
    assert (folder / "oauth.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        configure_oauth(folder, b'{"client_secret":"secret"}')
    configure_oauth(folder, b"null")
    assert OAuthConfig.load(folder / "oauth.json") is None


async def test_rpc_validation_size_client_errors_and_authless_mcp(tmp_path):
    async with environment(tmp_path, configured=False) as (store, broker, client, clock, provider, path, server):
        app = create_app(broker)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://broker") as raw:
            assert (await raw.get("/health")).status_code == 200
            assert (await raw.post("/rpc", content="x" * 16385)).status_code == 400
            assert (await raw.post("/rpc", json={"operation": "list", "principal": "../bad", "payload": {}})).status_code == 400
            bad = await raw.post("/rpc", json={"operation": "list", "principal": "a" * 64, "payload": {"cookie": SECRET}})
            assert bad.status_code == 400 and SECRET not in bad.text
        proxy = AccountClient("/unused", http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500, text=SECRET)), base_url="http://broker"))
        with pytest.raises(BrokerError, match="authentication_required"):
            await proxy.call("list", {}, None)
        with pytest.raises(BrokerError, match="broker_unavailable"):
            await proxy.call("list", {}, Principal("issuer", "subject"))
        await proxy.close()
        from mcp.shared.memory import create_connected_server_and_client_session
        async with create_connected_server_and_client_session(server) as session:
            result = await session.call_tool("get_game_accounts", {"request": {}})
            assert not result.isError and result.structuredContent["status"] == "authentication_required"
            assert result.structuredContent["records"] == []


async def test_member_accounts_callbacks_and_intents_are_isolated(tmp_path):
    async with environment(tmp_path / "alice", member="alice") as alice, environment(tmp_path / "bob", member="bob") as bob:
        a_store, _, a_client, _, _, a_path, _ = alice
        b_store, _, b_client, _, b_provider, b_path, _ = bob
        account = (await call(a_client, "register_game_account", {"account_name": "Alice#1234"}, "/u/alice/mcp"))["structuredContent"]["account"]
        foreign = await call(b_client, "get_game_connection_status", {"account_id": account["account_id"]}, "/u/bob/mcp")
        assert foreign["structuredContent"]["status"] == "not_found"
        assert a_store.key != b_store.key
        _, a_query = await start_link(a_client, a_path)
        await start_link(b_client, b_path)
        response = await b_client.get(b_path + "/callback", params={"code": "code", "state": a_query["state"][0]})
        assert response.status_code == 400 and not b_provider.requests
        handoff = a_store.prepare({"listing_ref": "a" * 64, "url": "https://www.pathofexile.com/trade2/search/poe2/Standard/q"}, account["account_id"])
        assert b_store.intent(handoff.intent_id).status == "not_found"


async def test_expired_csrf_auto_refresh_switch_and_broker_lifespan(tmp_path):
    async with environment(tmp_path) as (store, broker, client, clock, provider, path, server):
        account = store.save_grant(SUB, "Test#1234", grant(expires_in=100), NOW)
        page = await client.get(path)
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
        fields = {"csrf": csrf, "account_id": account.account_id}
        off = await client.post(path + "/refresh-setting", data={**fields, "enabled": "false"}, headers={"Origin": BASE})
        assert off.status_code == 303
        clock[0] += 95
        await broker.refresh_due()
        assert not provider.requests
        assert store.view(store.row(account.account_id)).renewal_status == "disabled"
        await client.post(path + "/refresh-setting", data={**fields, "enabled": "true"}, headers={"Origin": BASE})
        app = create_app(broker)
        async with app.router.lifespan_context(app):
            for _ in range(20):
                if provider.requests:
                    break
                await asyncio.sleep(0)
            assert len(provider.requests) == 1
        clock[0] += 1801
        response = await client.post(path + "/disconnect", data=fields, headers={"Origin": BASE})
        assert response.status_code == 400 and store.row(account.account_id)["status"] == "active"
        assert (await client.post(path + "/default", data={"csrf": "bad", "account_id": account.account_id}, headers={"Origin": BASE})).status_code == 400
        assert (await client.post(path + "/default", content="x" * 4097, headers={"Origin": BASE, "Content-Type": "application/x-www-form-urlencoded"})).status_code == 413
        oauth = broker.oauth
        broker.oauth = None
        status = (await call(client, "get_game_connection_status", {"account_id": account.account_id}))["structuredContent"]["account"]
        assert not status["provider_configured"] and status["next_action"] == "configure_provider"
        broker.oauth = oauth


def test_broker_render_and_removal_include_all_private_volumes():
    from poe2_companion.deployment import render_member_stack, member_services
    from test_members import MEMBERS
    volumes = ["account-socket", "account-state", "account-keys", "account-config"]
    base = {"services": {
        "poe2-companion": {"environment": {"POE2_CF_OWNER_EMAIL": "owner@example.com"}, "command": [],
            "volumes": [{"type": "volume", "source": "account-socket", "target": "/account-socket"}],
            "depends_on": {"account-broker": {"condition": "service_healthy"}}},
        "account-broker": {"environment": {"POE2_ACCOUNT_MEMBER": "owner"},
            "volumes": [{"type": "volume", "source": v, "target": "/" + v} for v in volumes]}},
        "volumes": {v: {"name": "poe2_" + v} for v in volumes}}
    stack = render_member_stack(base, MEMBERS)
    for member in MEMBERS:
        ident = member["id"]
        broker = stack["services"]["account-broker-" + ident]
        assert broker["environment"]["POE2_ACCOUNT_MEMBER"] == ident and "ports" not in broker
        assert {v["source"] for v in broker["volumes"]} == {v + "-" + ident for v in volumes}
        assert set(stack["services"]["poe2-companion-" + ident]["depends_on"]) == {"account-broker-" + ident}
        assert "account-broker-" + ident in member_services(ident, True, accounts=True)
        assert len(stack["services"]["poe2-companion-" + ident]["volumes"]) == 1
