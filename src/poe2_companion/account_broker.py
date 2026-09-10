"""Private per-member account service; UDS only, no raw secrets in public DTOs."""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
from typing import Annotated, Any
from urllib.parse import quote

from pydantic import Field, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .accounts import (AccountPageRequest, AccountRequest, AccountLinkRequest, RegisterAccountRequest,
                       TravelResultRequest, AccountID, Provider, AccountView)
from .builds import DTO
from .equipment import Price, LeagueName
from .account_oauth import GGGOAuth, OAuthConfig, OAuthError
from .account_store import AccountStore, StoreError, refresh_time


class RPC(DTO):
    operation: Annotated[str, Field(pattern=r"^[a-z_]{1,32}$")]
    principal: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    payload: dict[str, Any]


class UIRequest(DTO):
    browser: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    csrf: Annotated[str, Field(max_length=100)] = ""
    provider: Provider = "ggg"
    account_id: AccountID | None = None
    code: Annotated[str, Field(max_length=2048, pattern=r"^[^\x00-\x20\x7f]*$")] = ""
    state: Annotated[str, Field(pattern=r"^(?:[0-9a-f]{64})?$")] = ""
    enabled: bool = True


class Handoff(DTO):
    account_id: AccountID | None = None
    listing_ref: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    query_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    league: LeagueName
    quoted_price: Price | None = None


class AccountBroker:
    def __init__(self, store: AccountStore, public_base: str, account_path: str, oauth: GGGOAuth | None = None) -> None:
        self.store, self.public_base, self.account_path, self.oauth = store, public_base, account_path, oauth
        self.refresh_lock = asyncio.Lock()
        self.callback_lock = asyncio.Lock()
        self.maintenance_healthy = True

    def present(self, account: AccountView) -> dict[str, Any]:
        account.provider_configured = self.oauth is not None and account.provider == "ggg"
        if account.verified and account.session_status != "disconnected" and not account.provider_configured:
            account.renewal_status, account.next_action = "unavailable", "configure_provider"
        return account.model_dump()

    async def dispatch(self, request: RPC) -> dict[str, Any]:
        self.store.authorize(request.principal)
        operation, payload = request.operation, request.payload
        if operation == "list":
            page = AccountPageRequest.model_validate(payload)
            rows = self.store.db.execute("SELECT * FROM accounts ORDER BY id LIMIT ? OFFSET ?", (page.limit, page.offset)).fetchall()
            total = self.store.db.execute("SELECT count(*) FROM accounts").fetchone()[0]
            return {"status": "ok", "records": [self.present(self.store.view(row)) for row in rows], "total": total,
                    "next_offset": page.offset + len(rows) if page.offset + len(rows) < total else None}
        if operation == "register":
            registration = RegisterAccountRequest.model_validate(payload)
            return {"status": "ok", "account": self.present(self.store.register(registration.provider, registration.account_name))}
        if operation in {"status", "default"}:
            account_id = AccountRequest.model_validate(payload).account_id
            view = self.store.set_default(account_id) if operation == "default" else self.store.view(self.store.row(account_id))
            return {"status": "ok", "account": self.present(view)}
        if operation == "link":
            link = AccountLinkRequest.model_validate(payload)
            status = "provider_not_supported" if link.provider != "ggg" else "ready" if self.oauth else "provider_not_configured"
            return {"status": status, "url": self.public_base + self.account_path, "travel_link_supported": False}
        if operation == "prepare":
            handoff = Handoff.model_validate(payload)
            # Build the URL from validated components; never accept a URL from MCP.
            url = "https://www.pathofexile.com/trade2/search/poe2/" + quote(handoff.league, safe="") + "/" + handoff.query_id
            result = self.store.prepare({"listing_ref": handoff.listing_ref, "url": url,
                "quoted_price": handoff.quoted_price.model_dump() if handoff.quoted_price else None}, handoff.account_id)
            return result.model_dump()
        if operation == "result":
            return self.store.intent(TravelResultRequest.model_validate(payload).intent_id).model_dump()
        if operation.startswith("ui_"):
            ui = UIRequest.model_validate(payload)
            return await self.ui(operation, ui, request.principal)
        raise StoreError("invalid_request")

    async def ui(self, operation: str, ui: UIRequest, principal: str) -> dict[str, Any]:
        if operation == "ui_page":
            rows = self.store.db.execute("SELECT * FROM accounts ORDER BY id").fetchall()
            return {"status": "ok", "records": [self.present(self.store.view(row)) for row in rows],
                    "csrf": self.store.csrf(principal, ui.browser), "oauth_configured": self.oauth is not None}
        if operation == "ui_callback":
            if self.oauth is None or not ui.code or not ui.state:
                raise StoreError("invalid_link_attempt")
            # Bound callback concurrency and compare persisted disconnect generation
            # after every await so an old authorization cannot revive a link.
            async with self.callback_lock:
                verifier = self.store.consume_attempt(ui.state, ui.browser)
                generation, now = self.store.link_generation(), int(self.store.clock())
                grant = await self.oauth.exchange(ui.code, verifier)
                identity, name = await self.oauth.profile(grant)
                if generation != self.store.link_generation():
                    raise StoreError("link_cancelled")
                account = self.store.save_grant(identity, name, grant, now)
                return {"status": "ok", "account": self.present(account)}
        self.store.check_csrf(principal, ui.browser, ui.csrf)
        if operation == "ui_start":
            if self.oauth is None or ui.provider != "ggg":
                return {"status": "provider_not_configured"}
            verifier = secrets.token_urlsafe(48)
            state = self.store.begin_attempt(ui.browser, verifier)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            return {"status": "ready", "url": self.oauth.authorization_url(state, challenge)}
        if not ui.account_id:
            raise StoreError("invalid_request")
        if operation == "ui_disconnect":
            self.store.disconnect(ui.account_id)
            # Requested profile scope does not include oauth:revoke. Explicitly
            # distinguish local deletion from revocation in the upstream account.
            return {"status": "disconnected", "upstream_revocation": "use_official_applications_page"}
        if operation == "ui_refresh_setting":
            self.store.row(ui.account_id)
            self.store.db.execute("UPDATE accounts SET auto_refresh=? WHERE id=?", (int(ui.enabled), ui.account_id))
            return {"status": "ok"}
        if operation == "ui_default":
            return {"status": "ok", "account": self.present(self.store.set_default(ui.account_id))}
        raise StoreError("invalid_request")

    async def refresh_due(self) -> None:
        if self.oauth is None or self.refresh_lock.locked():
            return
        async with self.refresh_lock:
            self.store.cleanup()
            now = int(self.store.clock())
            rows = self.store.db.execute("SELECT * FROM accounts WHERE status='active' AND auto_refresh=1 "
                "AND refreshing=0 AND next_refresh<=? AND refresh_exp>? ORDER BY next_refresh LIMIT 16", (now, now)).fetchall()
            for row in rows:
                # The durable flag is written before any network I/O.
                claimed = self.store.db.execute("UPDATE accounts SET refreshing=1 WHERE id=? AND version=? AND epoch=? "
                    "AND status='active' AND auto_refresh=1 AND refreshing=0", (row["id"], row["version"], row["epoch"])).rowcount
                if not claimed:
                    continue
                try:
                    old = self.store.unseal(f"credential:{row['id']}:{row['version']}", row["secret"])
                    requested_at = int(self.store.clock())
                    grant = await self.oauth.refresh(old["refresh_token"])
                    if not grant.get("refresh_token") or grant["sub"] != old["sub"]:
                        raise OAuthError("account_mismatch")
                    version = row["version"] + 1
                    expiry = requested_at + grant["expires_in"]
                    next_at = refresh_time(requested_at, grant["expires_in"])
                    # The returned refresh token inherits the *original* deadline.
                    self.store.db.execute("UPDATE accounts SET secret=?,version=?,access_exp=?,next_refresh=?,refreshing=0 "
                        "WHERE id=? AND version=? AND epoch=? AND refreshing=1 AND status='active'",
                        (self.store.seal(f"credential:{row['id']}:{version}", grant), version, expiry,
                         next_at if next_at < row["refresh_exp"] else None, row["id"], row["version"], row["epoch"]))
                except OAuthError as error:
                    if error.code == "rate_limited":
                        self.store.db.execute("UPDATE accounts SET refreshing=0,next_refresh=? WHERE id=? AND epoch=? AND version=?",
                            (int(self.store.clock()) + (error.retry_after or 60), row["id"], row["epoch"], row["version"]))
                    else:
                        self.store.db.execute("UPDATE accounts SET refreshing=0,status='reauth_required',next_refresh=NULL "
                            "WHERE id=? AND epoch=? AND version=?", (row["id"], row["epoch"], row["version"]))
                except Exception:
                    # Never print decrypted payloads or exception reprs.
                    self.store.db.execute("UPDATE accounts SET refreshing=0,status='reauth_required',next_refresh=NULL "
                        "WHERE id=? AND epoch=? AND version=?", (row["id"], row["epoch"], row["version"]))


def create_app(broker: AccountBroker) -> Starlette:
    async def rpc(request: Request) -> JSONResponse:
        try:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16384:
                    raise ValueError()
            command = RPC.model_validate_json(body)
            result = await broker.dispatch(command)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except StoreError as error:
            return JSONResponse({"status": str(error)}, status_code=403 if str(error) == "identity_mismatch" else 200)
        except OAuthError as error:
            return JSONResponse({"status": error.code, "retry_after_seconds": error.retry_after})
        except (ValidationError, ValueError, TypeError, KeyError):
            return JSONResponse({"status": "invalid_request"}, status_code=400)
        except Exception:
            return JSONResponse({"status": "broker_unavailable"}, status_code=503)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok" if broker.maintenance_healthy else "maintenance_unavailable"},
                            status_code=200 if broker.maintenance_healthy else 503)

    async def maintain() -> None:
        while True:
            try:
                await broker.refresh_due()
                broker.maintenance_healthy = True
            except Exception:
                broker.maintenance_healthy = False
            await asyncio.sleep(60)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        task = asyncio.create_task(maintain())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return Starlette(routes=[Route("/rpc", rpc, methods=["POST"]), Route("/health", health)], lifespan=lifespan)


def configure_oauth(directory: Path, payload: bytes) -> None:
    if len(payload) > 8192:
        raise ValueError("invalid_oauth_config")
    data = json.loads(payload)
    if data is not None:
        OAuthConfig.parse(data)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    destination = directory / "oauth.json"
    if destination.is_symlink():
        raise ValueError("invalid_oauth_config")
    if data is None:
        destination.unlink(missing_ok=True)
        return
    temporary = directory / ("oauth-" + secrets.token_hex(16) + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps(data).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    os.umask(0o077)
    if sys.argv[1:] == ["--configure-oauth"]:
        try:
            configure_oauth(Path("/account-config"), sys.stdin.buffer.read(8193))
        except Exception:
            raise SystemExit("invalid_oauth_config") from None
        print("Account OAuth configuration saved; restart this broker to apply.")
        return
    if sys.argv[1:] not in ([], ["--invalidate-restored-sessions"]):
        raise SystemExit("invalid_account_broker_arguments")
    member = os.environ.get("POE2_ACCOUNT_MEMBER", "owner")
    host = os.environ.get("POE2_PUBLIC_HOST", "")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,23}", member) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host):
        raise SystemExit("invalid_account_broker_configuration")
    account_path = ("" if member == "owner" else "/u/" + member) + "/accounts"
    store = AccountStore(Path("/account-state"), Path("/account-keys/master.key"), member)
    if sys.argv[1:] == ["--invalidate-restored-sessions"]:
        for row in store.db.execute("SELECT id FROM accounts").fetchall():
            store.disconnect(row["id"])
        store.close()
        print("Restored sessions invalidated; reconnect accounts in the account UI.")
        return
    config = OAuthConfig.load(Path("/account-config/oauth.json"))
    oauth = GGGOAuth(config, "https://" + host + account_path + "/callback") if config else None
    broker = AccountBroker(store, "https://" + host, account_path, oauth)
    import uvicorn
    try:
        uvicorn.run(create_app(broker), uds="/account-socket/accounts.sock", access_log=False,
                    log_level="warning", proxy_headers=False)
    finally:
        store.close()


if __name__ == "__main__":
    main()
