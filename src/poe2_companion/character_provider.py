"""Private ingestion service. Provider payloads and credentials never reach MCP.

This network-enabled process writes imports. The PoB computation worker remains
network-disabled, and the MCP process mounts neither raw files nor credentials.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import math
import os
import socket
import time
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from .builds import BuildReader, PlayerStat, bounded_dto, read_regular_file
from .characters import (AccountRequest, CharacterRequest, CharacterIdentity, CharacterPage,
    CharacterOverview, CharacterImport, CharacterRefresh, AttachmentRequest, AttachmentImport,
    CHARACTER_INPUTS, CHARACTER_ERRORS, CharacterError, account_slug)
from .pob_io import import_stream, atomic_write, MAX_CODE_BYTES

NINJA = "https://poe.ninja"
STAT_MAP = {"life": "Life", "energyShield": "EnergyShield", "mana": "Mana",
            "armour": "Armour", "evasionRating": "Evasion", "strength": "Str",
            "dexterity": "Dex", "intelligence": "Int"}


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except ValueError:
        return None


class CharacterProvider:
    def __init__(self, private_dir: Path, projection_dir: Path, state_dir: Path, *,
                 http=None, attachment_http=None, attachment_hosts=None):
        self.private = private_dir
        self.projections = projection_dir
        self.state = state_dir
        # Separate clients prevent Ninja cookies leaking to file download hosts.
        self.http = http or httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False,
            headers={"User-Agent": "poe2-gpt/0.8.0 (https://github.com/Dev-Jahn/poe2-gpt)", "Accept": "application/json"})
        self.attachment_http = attachment_http or httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False)
        self.attachment_hosts = set(attachment_hosts or ["files.oaiusercontent.com"])
        self.lock = asyncio.Lock()
        self.blocked_until = 0.0

    async def close(self):
        await self.http.aclose()
        await self.attachment_http.aclose()

    async def ninja(self, path, *, method="GET", cookie=None, events=False):
        if time.monotonic() < self.blocked_until:
            raise CharacterError("character_rate_limited")
        try:
            headers = {"Accept": "text/event-stream" if events else "application/json"}
            if cookie:
                headers.update({"Cookie": cookie, "Origin": NINJA})
            async with self.http.stream(method, NINJA + path, headers=headers) as response:
                if response.status_code == 429:
                    retry = response.headers.get("retry-after", "60")
                    wait = min(86400, max(1, int(retry))) if retry.isdigit() else 60
                    self.blocked_until = time.monotonic() + wait
                    raise CharacterError("character_rate_limited")
                if response.status_code in (401, 403):
                    raise CharacterError("character_authentication_required")
                if response.status_code == 404:
                    raise CharacterError("character_not_found")
                expected_type = "text/event-stream" if events else "json"
                if response.status_code != 200 or expected_type not in response.headers.get("content-type", ""):
                    raise CharacterError("character_unavailable")
                body = bytearray()
                received = 0
                async for chunk in response.aiter_bytes():
                    received += len(chunk)
                    body.extend(chunk)
                    if received > (16384 if events else 4 * 1024 * 1024):
                        raise CharacterError("character_schema_changed")
                    if events:
                        event = body.replace(b"\r\n", b"\n")
                        while b"\n\n" in event:
                            first, event = event.split(b"\n\n", 1)
                            lines = [line[5:].strip() for line in first.splitlines() if line.startswith(b"data:")]
                            if lines:
                                return json.loads(b"\n".join(lines))
                        body = bytearray(event)
                return json.loads(body)
        except CharacterError:
            raise
        except Exception:
            raise CharacterError("character_unavailable") from None

    async def version(self, suffix):
        event = await self.ninja("/poe2/api/events/" + suffix, events=True)
        version = event.get("version") if isinstance(event, dict) else None
        if type(version) is not int or not 0 <= version <= 2147483647:
            raise CharacterError("character_schema_changed")
        return version

    async def entries(self, tag):
        slug = quote(account_slug(tag), safe="")
        version = await self.version("characters/" + slug)
        data = await self.ninja("/poe2/api/profile/characters/" + slug + "/" + str(version))
        # Exact shape is pinned with a synthetic fixture; never return upstream
        # dictionaries, model exports, HTML or arbitrary text to the caller.
        rows = data
        if not isinstance(rows, list) or len(rows) > 1000:
            raise CharacterError("character_schema_changed")
        if any(not isinstance(row, dict) or account_slug(row.get("accountName", "")) != account_slug(tag) for row in rows):
            raise CharacterError("character_schema_changed")
        return rows

    async def list_account_characters(self, request: AccountRequest):
        rows = await self.entries(request.account_tag)
        items = []
        for row in rows:
            if not isinstance(row, dict):
                raise CharacterError("character_schema_changed")
            league = row.get("leagueUrl")
            if request.league is None or league == request.league:
                items.append(CharacterIdentity(name=row["name"], league=league,
                    level=row.get("level"), class_name=row.get("className")))
        end = request.offset + request.limit
        return CharacterPage(account_slug=account_slug(request.account_tag), characters=items[request.offset:end],
            total=len(items), next_offset=end if end < len(items) else None, retrieved_at_epoch=int(time.time()))

    async def resolve(self, request):
        if request.league is not None:
            return request
        rows = await self.entries(request.account_tag)
        leagues = {r.get("leagueUrl") for r in rows if isinstance(r, dict) and r.get("name") == request.character_name}
        if not leagues:
            raise CharacterError("character_not_found")
        if len(leagues) != 1:
            raise CharacterError("character_ambiguous_league")
        return CharacterRequest(account_tag=request.account_tag, character_name=request.character_name, league=leagues.pop())

    async def model(self, request):
        identity = "/".join(quote(v, safe="") for v in
            (account_slug(request.account_tag), request.league, request.character_name))
        version = await self.version("character/" + identity)
        path = "/poe2/api/profile/characters/" + identity + f"/model/{version}"
        data = await self.ninja(path)
        model = data.get("charModel") if isinstance(data, dict) else None
        if not isinstance(model, dict):
            raise CharacterError("character_schema_changed")
        # Refuse mismatched identities before importing any code.
        if account_slug(model.get("account", "")) != account_slug(request.account_tag) or model.get("name") != request.character_name:
            raise CharacterError("character_schema_changed")
        return model

    def overview(self, request, model):
        stats = []
        defensive = model.get("defensiveStats", {})
        if not isinstance(defensive, dict):
            raise CharacterError("character_schema_changed")
        for source, name in STAT_MAP.items():
            value = defensive.get(source)
            if type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e15:
                stats.append(PlayerStat(name=name, value=float(value)))
        return CharacterOverview(account_slug=account_slug(request.account_tag),
            character=CharacterIdentity(name=request.character_name, league=request.league,
                level=model.get("level"), class_name=model.get("class")), stats=stats,
            pob_available=isinstance(model.get("pathOfBuildingExport"), str) and bool(model["pathOfBuildingExport"]),
            retrieved_at_epoch=int(time.time()), source_updated_at=timestamp(model.get("updatedUtc")))

    def store(self, code):
        if len(code) > MAX_CODE_BYTES:
            raise CharacterError("attachment_too_large")
        digest = hashlib.sha256(code).hexdigest()
        index = self.state / ("import-" + digest + ".json")
        if index.exists():
            try:
                saved = json.loads(read_regular_file(index, 1024))
                summary = BuildReader(self.projections).summary(saved["build_id"])
                if (self.private / (summary.build_id + ".pob")).is_file():
                    return summary, True
            except Exception:
                pass
        paths = list(self.private.glob("bld_*.pob"))
        if len(paths) >= 500 or sum(p.stat().st_size for p in paths) + len(code) > 128 * 1024 * 1024:
            raise CharacterError("character_storage_full")
        try:
            build_id = import_stream(BytesIO(code), self.private, self.projections)
            atomic_write(index, json.dumps({"build_id": build_id}).encode())
            return BuildReader(self.projections).summary(build_id), False
        except Exception:
            raise CharacterError("character_import_unavailable") from None

    async def get_character(self, request: CharacterRequest):
        request = await self.resolve(request)
        model = await self.model(request)
        overview = self.overview(request, model)
        if not overview.pob_available:
            raise CharacterError("character_import_unavailable")
        summary, reused = self.store(model["pathOfBuildingExport"].encode("ascii"))
        return CharacterImport(character=overview, build=summary, reused=reused)

    def session(self):
        path = self.state / "session.json"
        if not path.exists():
            return None
        data = json.loads(read_regular_file(path, 16384))
        if not isinstance(data, dict) or set(data) != {"account_tag", "cookie"}:
            raise ValueError("invalid_session")
        account_slug(data["account_tag"])
        cookie = data["cookie"]
        if not isinstance(cookie, str) or not 1 <= len(cookie) <= 12000 or any(ord(c) < 32 or ord(c) > 126 for c in cookie):
            raise ValueError("invalid_session")
        return data

    async def refresh_character(self, request: CharacterRequest):
        session = self.session()
        if session is None:
            return CharacterRefresh(status="authentication_required", success=False)
        if account_slug(session["account_tag"]) != account_slug(request.account_tag):
            return CharacterRefresh(status="account_mismatch", success=False)
        request = await self.resolve(request)
        # Validate the account/name identity through the public model first.
        await self.model(request)
        key = (account_slug(request.account_tag), request.league, request.character_name)
        deadline_path = self.state / ("refresh-" + hashlib.sha256(json.dumps(key).encode()).hexdigest() + ".json")
        if deadline_path.exists():
            deadline = json.loads(read_regular_file(deadline_path, 128))["after"]
            if deadline > time.time():
                return CharacterRefresh(status="cooldown", success=False, wait_seconds=min(86400, math.ceil(deadline-time.time())))
        # Persist before POST: don't repeat a possibly successful operation after
        # a timeout/restart. There are no automatic POST retries.
        atomic_write(deadline_path, json.dumps({"after": time.time()+300}).encode())
        try:
            data = await self.ninja("/poe2/api/account/refresh-character/" +
                quote(request.league, safe="") + "/" + quote(request.character_name, safe=""),
                method="POST", cookie=session["cookie"])
        except CharacterError as error:
            if str(error) == "character_authentication_required":
                return CharacterRefresh(status="authentication_required", success=False)
            raise
        if not isinstance(data, dict) or type(data.get("success")) is not bool:
            raise CharacterError("character_schema_changed")
        wait = data.get("waitSeconds")
        wait = min(86400, max(0, math.ceil(wait))) if type(wait) in (int, float) and math.isfinite(wait) else None
        atomic_write(deadline_path, json.dumps({"after": time.time()+max(300, wait or 0)}).encode())
        result = CharacterRefresh(status="requested" if data["success"] else "cooldown" if wait else "unavailable",
            success=data["success"], wait_seconds=wait)
        if data["success"]:
            try:
                result.snapshot = self.overview(request, await self.model(request))
            except Exception:
                result.snapshot_error = "character_unavailable"
        return result

    async def import_pob_attachment(self, request: AttachmentRequest):
        file = request.file
        if not file.file_name.lower().endswith(".txt") or file.mime_type not in ("text/plain", "application/octet-stream"):
            raise CharacterError("attachment_must_be_txt")
        parts = urlsplit(file.download_url)
        if (parts.scheme != "https" or parts.hostname not in self.attachment_hosts or parts.username or parts.password
                or parts.port not in (None, 443) or parts.fragment):
            raise CharacterError("attachment_host_not_allowed")
        # Only operator-approved exact vendor hosts, and no private-address
        # destinations, credentials, redirects, or arbitrary URL import tools.
        addresses = await asyncio.get_running_loop().getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise CharacterError("attachment_host_not_allowed")
        try:
            async with self.attachment_http.stream("GET", file.download_url) as response:
                if response.status_code != 200:
                    raise CharacterError("attachment_unavailable")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_CODE_BYTES:
                        raise CharacterError("attachment_too_large")
            summary, reused = self.store(bytes(data))
            return AttachmentImport(build=summary, reused=reused)
        except CharacterError:
            raise
        except Exception:
            raise CharacterError("attachment_unavailable") from None


def provider_app(provider):
    async def health(_):
        return JSONResponse({"status": "ok"})

    async def handle(request):
        if provider.lock.locked():
            return JSONResponse({"code": "character_provider_busy"}, status_code=429)
        async with provider.lock:
            try:
                async with asyncio.timeout(55):
                    body = bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 12288:
                            raise CharacterError("invalid_character_request")
                    operation = request.path_params["operation"]
                    if operation not in CHARACTER_INPUTS:
                        raise CharacterError("invalid_character_request")
                    value = CHARACTER_INPUTS[operation].model_validate_json(body)
                    result = bounded_dto(await getattr(provider, operation)(value))
                    return JSONResponse(result.model_dump(mode="json"))
            except CharacterError as error:
                code = str(error) if str(error) in CHARACTER_ERRORS else "character_unavailable"
                return JSONResponse({"code": code}, status_code=400)
            except Exception:
                # No upstream bodies, validation inputs, URLs, cookies or
                # decoded payload fragments in errors or logs.
                return JSONResponse({"code": "character_unavailable"}, status_code=400)

    @asynccontextmanager
    async def lifespan(_):
        yield
        await provider.close()

    return Starlette(routes=[Route("/health", health), Route("/{operation}", handle, methods=["POST"])], lifespan=lifespan)


def main():
    import uvicorn
    import sys
    import logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    os.umask(0o077)
    if sys.argv[1:]:
        if sys.argv[1:] != ["--configure-session"]:
            raise SystemExit("invalid_operator_arguments")
        try:
            data = json.loads(sys.stdin.buffer.read(16385))
            if not isinstance(data, dict) or set(data) != {"account_tag", "cookie"}:
                raise ValueError()
            account_slug(data["account_tag"])
            cookie = data["cookie"]
            if not isinstance(cookie, str) or len(cookie) > 12000 or any(ord(c) < 32 or ord(c) > 126 for c in cookie):
                raise ValueError()
            destination = Path("/character-state/session.json")
            if cookie:
                atomic_write(destination, json.dumps(data).encode())
            else:
                destination.unlink(missing_ok=True)
            print("Ninja refresh session updated")
            return
        except Exception:
            raise SystemExit("invalid_ninja_session") from None
    path = Path(os.environ.get("POE2_CHARACTER_SOCKET", "/character-socket/characters.sock"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    provider = CharacterProvider(Path("/private-builds"), Path("/build-projections"), Path("/character-state"),
        attachment_hosts=os.environ.get("POE2_ATTACHMENT_HOSTS", "files.oaiusercontent.com").split(","))
    # Never enable HTTP client debug/access logs for signed file URLs or sessions.
    uvicorn.run(provider_app(provider), uds=str(path), access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
