import asyncio
import json
import socket
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from poe2_companion.character_provider import CharacterProvider, provider_app
from poe2_companion.characters import (CharacterClient, CharacterRequest, AccountRequest,
    AttachmentRequest, OpenAIFile, CharacterError, account_slug)
from poe2_companion.pob_io import atomic_write
from poe2_companion.server import build_server
from poe2_companion.scout import Scout
from test_build_boundary import code, MARKER
from test_scout import Backend

TAG = "Example_#7513"
REQUEST = CharacterRequest(account_tag=TAG, character_name="테스트캐릭터", league="forbiddenrites")


class NinjaBackend:
    def __init__(self):
        self.calls = []
        self.status = 200
        self.rows = [{"accountName":TAG, "name": REQUEST.character_name, "leagueUrl": "forbiddenrites", "level": 91, "className": "Witch"}]
        self.model = {"account": TAG, "name": REQUEST.character_name, "league": "Forbidden Rites",
                      "level": 91, "class": "Witch", "pathOfBuildingExport": code().decode(),
                      "defensiveStats": {"life": 2100, "energyShield": 4300, "unknown": MARKER},
                      "updatedUtc": "2026-09-08T09:00:00Z", "notes": MARKER}

    def __call__(self, request):
        self.calls.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"message": MARKER}, headers={"retry-after": "60"})
        if "/events/" in request.url.path:
            return httpx.Response(200, content=b'data: {"version":15}\n\n', headers={"content-type":"text/event-stream"})
        if request.method == "POST":
            assert request.content == b""
            return httpx.Response(200, json={"success": True, "waitSeconds": None, "message": MARKER})
        if "/model/" in request.url.path:
            return httpx.Response(200, json={"type": "profile", "charModel": self.model})
        return httpx.Response(200, json=self.rows)


def provider(tmp_path, backend=None, files=None):
    backend = backend or NinjaBackend()
    return CharacterProvider(tmp_path/"raw", tmp_path/"safe", tmp_path/"state",
        http=httpx.AsyncClient(transport=httpx.MockTransport(backend)),
        attachment_http=httpx.AsyncClient(transport=httpx.MockTransport(files or (lambda _: httpx.Response(200, content=code())))))


async def test_account_resolution_import_dedup_and_private_projection(tmp_path):
    backend = NinjaBackend()
    p = provider(tmp_path, backend)
    result = await p.get_character(CharacterRequest(account_tag=TAG, character_name=REQUEST.character_name))
    text = result.model_dump_json()
    assert result.build.level == 91 and result.build.build_id.startswith("bld_")
    assert MARKER not in text and code().decode() not in text and "pathOfBuildingExport" not in text
    assert (p.private/(result.build.build_id+".pob")).read_bytes() == code()
    assert (await p.get_character(REQUEST)).reused
    assert len(list(p.private.glob("*.pob"))) == 1
    backend.rows += [{**backend.rows[0], "leagueUrl": "standard"}]
    with pytest.raises(CharacterError, match="ambiguous_league"):
        await p.get_character(CharacterRequest(account_tag=TAG, character_name=REQUEST.character_name))
    backend.model["account"] = "Another#1111"
    with pytest.raises(CharacterError, match="schema_changed"):
        await p.get_character(REQUEST)
    await p.close()


async def test_refresh_auth_binding_cooldown_persistence_and_redaction(tmp_path):
    backend = NinjaBackend()
    p = provider(tmp_path, backend)
    assert (await p.refresh_character(REQUEST)).status == "authentication_required"
    atomic_write(p.state/"session.json", json.dumps({"account_tag": "Other#1111", "cookie": "test=synthetic"}).encode())
    assert (await p.refresh_character(REQUEST)).status == "account_mismatch"
    atomic_write(p.state/"session.json", json.dumps({"account_tag": TAG, "cookie": "test=synthetic"}).encode())
    result = await p.refresh_character(REQUEST)
    assert result.success and result.snapshot and not result.game_fetch_confirmed
    assert MARKER not in result.model_dump_json()
    assert sum(r.method == "POST" for r in backend.calls) == 1
    assert all("cookie" not in r.headers for r in backend.calls if r.method == "GET")
    second = provider(tmp_path, backend)
    assert (await second.refresh_character(REQUEST)).status == "cooldown"
    assert sum(r.method == "POST" for r in backend.calls) == 1
    await p.close()
    await second.close()


async def test_attachment_preserves_bytes_and_blocks_ssrf_redirects_and_payloads(tmp_path, monkeypatch):
    async def public_dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", public_dns)
    original = b"\xef\xbb\xbf" + code() + b"\r\n"
    calls = []
    def files(request):
        calls.append(request)
        assert "cookie" not in request.headers and "authorization" not in request.headers
        return httpx.Response(200, content=original)
    p = provider(tmp_path, files=files)
    file = OpenAIFile(download_url="https://files.oaiusercontent.com/file/test?sig=synthetic", file_id="file_test", file_name="build.txt")
    result = await p.import_pob_attachment(AttachmentRequest(file=file))
    assert (p.private/(result.build.build_id+".pob")).read_bytes() == original
    assert code().decode() not in result.model_dump_json()
    for url in ["http://files.oaiusercontent.com/f", "https://127.0.0.1/f", "https://files.oaiusercontent.com.attacker.test/f",
                "https://files.oaiusercontent.com@127.0.0.1/f", "file:///private-builds/input.pob"]:
        with pytest.raises(CharacterError, match="host_not_allowed"):
            await p.import_pob_attachment(AttachmentRequest(file=file.model_copy(update={"download_url": url})))
    assert len(calls) == 1
    async def private_dns(*a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", private_dns)
    with pytest.raises(CharacterError, match="host_not_allowed"):
        await p.import_pob_attachment(AttachmentRequest(file=file))
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", public_dns)
    await p.attachment_http.aclose()
    p.attachment_http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(302, headers={"location":"http://127.0.0.1/"})))
    with pytest.raises(CharacterError, match="attachment_unavailable"):
        await p.import_pob_attachment(AttachmentRequest(file=file))
    await p.close()


async def test_mcp_file_schema_and_invalid_inputs_never_echo_payload(tmp_path, caplog, monkeypatch):
    p = provider(tmp_path)
    rpc = CharacterClient("unused", http=httpx.AsyncClient(transport=httpx.ASGITransport(app=provider_app(p)), base_url="http://provider"))
    scout = Scout(user_agent="test", cache_path=tmp_path/"prices.db", transport=httpx.MockTransport(Backend()))
    server = build_server(scout, characters=rpc)
    tools = {t.name:t for t in await server.list_tools()}
    tool = tools["import_pob_attachment"]
    assert tool.meta["openai/fileParams"] == ["file"]
    schema = tool.inputSchema
    file_schema = schema["$defs"]["OpenAIFile"]
    assert set(file_schema["required"]) == {"download_url", "file_id"}
    assert set(file_schema["properties"]) == {"download_url", "file_id", "mime_type", "file_name"}
    assert not tool.annotations.readOnlyHint and not tools["refresh_character"].annotations.idempotentHint
    async def public_dns(*a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", public_dns)
    result = await server.call_tool("import_pob_attachment", {"file": {
        "download_url": "https://files.oaiusercontent.com/file/test?sig=do-not-return",
        "file_id": "file_test", "file_name": "build.txt", "mime_type": "text/plain"}})
    # FastMCP's successful direct call returns content + structured projection.
    serialized = str(result)
    assert "bld_" in serialized and code().decode() not in serialized
    assert "do-not-return" not in serialized and MARKER not in serialized
    for name, arguments in [("get_character", {"request":{"account_tag":TAG,"character_name":MARKER}}),
                            ("import_pob_attachment", {"file":{"content":code().decode()}}),
                            ("get_character", {"request": REQUEST.model_dump(), "raw": MARKER})]:
        result = await server.call_tool(name, arguments)
        assert result.isError and MARKER not in str(result) and code().decode() not in str(result)
    response = await rpc.http.post("/get_character", json={**REQUEST.model_dump(), "raw": MARKER})
    assert response.status_code == 400 and MARKER not in response.text
    assert MARKER not in caplog.text
    await rpc.close()
    await p.close()
    await scout.close()


async def test_streamed_versions_are_bounded_and_close_after_first_data(tmp_path):
    class Events(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            yield b': ping\r\n\r'
            yield b'\ndata: {"version":'
            yield b'26}\r\n\r\n'
            pytest.fail("Version consumer kept the SSE connection open")
        async def aclose(self):
            self.closed = True
    events = Events()
    p = provider(tmp_path)
    await p.http.aclose()
    p.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
        stream=events, headers={"content-type":"text/event-stream"})))
    assert await p.version("characters/Example_-7513") == 26 and events.closed
    await p.http.aclose()
    p.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
        content=b": ping\n\n"*3000, headers={"content-type":"text/event-stream"})))
    with pytest.raises(CharacterError, match="schema_changed"):
        await p.version("characters/Example_-7513")
    await p.close()


async def test_import_quota_and_dedup_are_private_per_user(tmp_path):
    first, second = provider(tmp_path/"owner"), provider(tmp_path/"guest1")
    a, reused = first.store(code())
    b, _ = second.store(code())
    assert not reused and a.build_id != b.build_id
    assert not (second.private/(a.build_id+".pob")).exists()
    for i in range(499):
        (first.private/f"bld_quota{i}.pob").touch()
    assert first.store(code())[1]  # Dedup is permitted at capacity.
    with pytest.raises(CharacterError, match="storage_full"):
        first.store(code()+b"\n")
    from poe2_companion.pob_io import MAX_CODE_BYTES
    with pytest.raises(CharacterError, match="too_large"):
        first.store(b"x"*(MAX_CODE_BYTES+1))
    await first.close()
    await second.close()


@pytest.mark.parametrize("status,error", [(401,"authentication_required"),(403,"authentication_required"),(429,"rate_limited"),(500,"unavailable")])
async def test_upstream_errors_are_fixed_and_no_retry(tmp_path, status, error):
    b = NinjaBackend()
    b.status = status
    p = provider(tmp_path,b)
    with pytest.raises(CharacterError, match=error):
        await p.get_character(REQUEST)
    assert len(b.calls) == 1
    if status == 429:
        with pytest.raises(CharacterError, match="rate_limited"):
            await p.get_character(REQUEST)
        assert len(b.calls) == 1
    await p.close()


def test_identifiers_and_removed_host_file_import():
    assert account_slug(TAG) == "Example_-7513"
    for tag in ["https://example.com", "../foo#7513", "hello\n#7513", MARKER]:
        with pytest.raises(ValueError): account_slug(tag)
    for name in ["../secret", "foo%2fbar", MARKER]:
        with pytest.raises(ValidationError): CharacterRequest(account_tag=TAG,character_name=name)
    root = Path(__file__).resolve().parents[1]
    assert 'sub.add_parser("import-build"' not in (root/"scripts/mac.py").read_text()
    assert "poe2-pob-files =" not in (root/"pyproject.toml").read_text()
