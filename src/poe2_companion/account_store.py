"""Single-member persistent state. Only the private account broker opens it."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from collections.abc import Callable, Iterator
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .accounts import AccountView, Provider, TravelResult


class StoreError(Exception):
    pass


def load_key(path: Path, *, create: bool) -> bytes:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600) if create else None
    except FileExistsError:
        fd = None
    if fd is not None:
        with os.fdopen(fd, "wb") as stream:
            stream.write(AESGCM.generate_key(bit_length=256))
            stream.flush()
            os.fsync(stream.fileno())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if os.fstat(stream.fileno()).st_mode & 0o077:
            raise ValueError("account_key_permissions")
        key = stream.read(33)
    if len(key) != 32:
        raise ValueError("invalid_account_key")
    return key


class AccountStore:
    def __init__(self, directory: Path, key_path: Path, member: str,
                 *, clock: Callable[[], float] = time.time) -> None:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        path = directory / "accounts.sqlite3"
        if path.is_symlink():
            raise ValueError("account_store_symlink")
        self.key = load_key(key_path, create=not path.exists())
        self.cipher, self.member, self.clock = AESGCM(self.key), member, clock
        self.db = sqlite3.connect(path, isolation_level=None)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, external_id TEXT,
            name TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0,
            preferred INTEGER NOT NULL DEFAULT 0, auto_refresh INTEGER NOT NULL DEFAULT 1,
            epoch INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'unverified', secret TEXT,
            access_exp INTEGER, refresh_exp INTEGER, next_refresh INTEGER,
            verified_at INTEGER, refreshing INTEGER NOT NULL DEFAULT 0,
            UNIQUE(provider, external_id));
          CREATE UNIQUE INDEX IF NOT EXISTS one_default ON accounts(preferred) WHERE preferred=1;
          CREATE TABLE IF NOT EXISTS attempts (
            state_hash TEXT PRIMARY KEY, browser_hash TEXT NOT NULL, secret TEXT NOT NULL,
            created INTEGER NOT NULL, expires INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS intents (
            id TEXT PRIMARY KEY, account_id TEXT NOT NULL, epoch INTEGER NOT NULL,
            created INTEGER NOT NULL, expires INTEGER NOT NULL, payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'prepared');
        """)
        stored = self.db.execute("SELECT value FROM metadata WHERE key='member'").fetchone()
        if stored and stored[0] != member:
            raise ValueError("account_store_member_mismatch")
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('member', ?)", (member,))
        check = self.db.execute("SELECT value FROM metadata WHERE key='key_check'").fetchone()
        if check:
            self.unseal("key_check", check[0])
        else:
            self.db.execute("INSERT INTO metadata VALUES ('key_check', ?)", (self.seal("key_check", {"ok": True}),))
        # A process may have died after upstream consumed a refresh token.
        self.db.execute("UPDATE accounts SET refreshing=0, status='reauth_required', next_refresh=NULL WHERE refreshing=1")

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def authorize(self, principal: str) -> None:
        with self.transaction():
            stored = self.db.execute("SELECT value FROM metadata WHERE key='principal'").fetchone()
            if stored and not hmac.compare_digest(stored[0], principal):
                raise StoreError("identity_mismatch")
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('principal', ?)", (principal,))

    def seal(self, purpose: str, data: dict[str, Any]) -> str:
        nonce = secrets.token_bytes(12)
        aad = (self.member + "\0" + purpose).encode()
        raw = json.dumps(data, separators=(",", ":"), allow_nan=False).encode()
        return base64.urlsafe_b64encode(nonce + self.cipher.encrypt(nonce, raw, aad)).decode()

    def unseal(self, purpose: str, encrypted: str) -> dict[str, Any]:
        raw = base64.urlsafe_b64decode(encrypted)
        data = json.loads(self.cipher.decrypt(raw[:12], raw[12:], (self.member + "\0" + purpose).encode()))
        if not isinstance(data, dict):
            raise ValueError("invalid_account_secret")
        return data

    def csrf(self, principal: str, browser: str, stamp: int | None = None) -> str:
        stamp = int(self.clock()) if stamp is None else stamp
        message = f"csrf\0{self.member}\0{principal}\0{browser}\0{stamp}".encode()
        return str(stamp) + "." + hmac.new(self.key, message, hashlib.sha256).hexdigest()

    def check_csrf(self, principal: str, browser: str, token: str) -> None:
        try:
            stamp = int(token.split(".")[0])
            if not 0 <= self.clock() - stamp <= 1800 or not hmac.compare_digest(token, self.csrf(principal, browser, stamp)):
                raise ValueError()
        except ValueError:
            raise StoreError("invalid_csrf") from None

    def row(self, account_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if row is None:
            raise StoreError("not_found")
        return row

    def view(self, row: sqlite3.Row) -> AccountView:
        now = int(self.clock())
        status = row["status"]
        if status == "active" and (not row["access_exp"] or row["access_exp"] <= now):
            status = "refresh_pending" if row["auto_refresh"] and row["refresh_exp"] and row["refresh_exp"] > now else "reauth_required"
        renewal = "disabled" if not row["auto_refresh"] else "unavailable"
        if row["auto_refresh"] and row["refresh_exp"] and row["refresh_exp"] > now:
            renewal = "expiring" if row["refresh_exp"] - now <= 7 * 86400 else "available"
        action = {"unverified": "link_account", "disconnected": "reconnect", "reauth_required": "reauthenticate", "refresh_pending": "wait_for_refresh"}.get(status, "none")
        if status == "active" and renewal in {"expiring", "unavailable"}:
            action = "reauthenticate"
        elif status == "active" and renewal == "disabled":
            action = "enable_refresh"
        return AccountView.model_validate(dict(account_id=row["id"], provider=row["provider"],
            display_name=row["name"], verified=bool(row["verified"]), default_for_travel=bool(row["preferred"]),
            auto_refresh=bool(row["auto_refresh"]), session_status=status, renewal_status=renewal,
            access_expires_at=row["access_exp"], refresh_absolute_expires_at=row["refresh_exp"],
            last_verified_at=row["verified_at"], next_action=action))

    def register(self, provider: Provider, name: str) -> AccountView:
        existing = self.db.execute("SELECT * FROM accounts WHERE provider=? AND name=? AND status!='disconnected' ORDER BY verified DESC LIMIT 1",
                                   (provider, name)).fetchone()
        if existing:
            return self.view(existing)
        if self.db.execute("SELECT count(*) FROM accounts").fetchone()[0] >= 16:
            raise StoreError("limit_reached")
        identity = "acct_" + secrets.token_hex(16)
        self.db.execute("INSERT INTO accounts(id,provider,name) VALUES(?,?,?)", (identity, provider, name))
        return self.view(self.row(identity))

    def set_default(self, account_id: str) -> AccountView:
        row = self.row(account_id)
        if row["status"] == "disconnected":
            raise StoreError("not_found")
        with self.transaction():
            self.db.execute("UPDATE accounts SET preferred=0 WHERE preferred=1")
            self.db.execute("UPDATE accounts SET preferred=1 WHERE id=?", (account_id,))
        return self.view(self.row(account_id))

    def disconnect(self, account_id: str) -> None:
        self.row(account_id)
        with self.transaction():
            self.db.execute("UPDATE accounts SET epoch=epoch+1,version=version+1,secret=NULL,status='disconnected',"
                            "preferred=0,refreshing=0,access_exp=NULL,refresh_exp=NULL,next_refresh=NULL WHERE id=?", (account_id,))
            self.db.execute("UPDATE intents SET status='cancelled' WHERE account_id=?", (account_id,))
            # Pending authorizations could otherwise reconnect after disconnect.
            self.db.execute("DELETE FROM attempts")
            self.db.execute("INSERT INTO metadata VALUES('link_generation','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")

    def link_generation(self) -> int:
        row = self.db.execute("SELECT value FROM metadata WHERE key='link_generation'").fetchone()
        return int(row[0]) if row else 0

    def begin_attempt(self, browser: str, verifier: str) -> str:
        now = int(self.clock())
        self.cleanup()
        if self.db.execute("SELECT count(*) FROM attempts").fetchone()[0] >= 16:
            raise StoreError("limit_reached")
        state = secrets.token_hex(32)
        digest = hashlib.sha256(state.encode()).hexdigest()
        self.db.execute("INSERT INTO attempts VALUES(?,?,?,?,?)", (digest,
            hashlib.sha256(browser.encode()).hexdigest(), self.seal("attempt:" + digest, {"verifier": verifier}), now, now + 600))
        return state

    def consume_attempt(self, state: str, browser: str) -> str:
        digest = hashlib.sha256(state.encode()).hexdigest()
        with self.transaction():
            row = self.db.execute("SELECT * FROM attempts WHERE state_hash=?", (digest,)).fetchone()
            if not row or row["expires"] <= self.clock() or not hmac.compare_digest(
                    row["browser_hash"], hashlib.sha256(browser.encode()).hexdigest()):
                raise StoreError("invalid_link_attempt")
            self.db.execute("DELETE FROM attempts WHERE state_hash=?", (digest,))
        return str(self.unseal("attempt:" + digest, row["secret"])["verifier"])

    def save_grant(self, external_id: str, name: str, grant: dict[str, Any], now: int) -> AccountView:
        existing = self.db.execute("SELECT * FROM accounts WHERE provider='ggg' AND external_id=?", (external_id,)).fetchone()
        # A manually registered name carries no ownership. It may be upgraded only
        # after an authenticated profile identifies the real account.
        if existing is None:
            existing = self.db.execute("SELECT * FROM accounts WHERE provider='ggg' AND name=? AND verified=0", (name,)).fetchone()
        if existing is None:
            registered = self.register("ggg", name)
            existing = self.row(registered.account_id)
        identity, version = existing["id"], existing["version"] + 1
        refresh_exp = now + 90 * 86400 if grant.get("refresh_token") else None
        with self.transaction():
            self.db.execute("UPDATE accounts SET external_id=?,name=?,verified=1,epoch=epoch+1,version=?,status='active',"
                "secret=?,access_exp=?,refresh_exp=?,next_refresh=?,verified_at=?,refreshing=0 WHERE id=?",
                (external_id, name, version, self.seal(f"credential:{identity}:{version}", grant),
                 now + grant["expires_in"], refresh_exp, refresh_time(now, grant["expires_in"]) if refresh_exp else None, now, identity))
            self.db.execute("UPDATE intents SET status='cancelled' WHERE account_id=?", (identity,))
        return self.view(self.row(identity))

    def prepare(self, data: dict[str, Any], account_id: str | None) -> TravelResult:
        if account_id is None:
            rows = self.db.execute("SELECT id,preferred FROM accounts WHERE status!='disconnected'").fetchall()
            chosen = [row for row in rows if row["preferred"]]
            if len(rows) == 1:
                chosen = rows
            if len(chosen) != 1:
                return TravelResult(status="account_selection_required")
            account_id = chosen[0]["id"]
        try:
            row = self.row(account_id)
        except StoreError:
            return TravelResult(status="account_unavailable")
        if row["status"] == "disconnected":
            return TravelResult(status="account_unavailable")
        self.cleanup()
        if self.db.execute("SELECT count(*) FROM intents").fetchone()[0] >= 256:
            # Bounded journal; retain at least the currently live requests.
            self.db.execute("DELETE FROM intents WHERE id IN (SELECT id FROM intents WHERE expires<=? ORDER BY created LIMIT 64)", (self.clock(),))
            if self.db.execute("SELECT count(*) FROM intents").fetchone()[0] >= 256:
                return TravelResult(status="broker_unavailable")
        now, identity = int(self.clock()), "travel_" + secrets.token_hex(16)
        result = TravelResult(status="prepared", intent_id=identity, account_id=account_id,
            account_name=row["name"], listing_ref=data["listing_ref"], quoted_price=data.get("quoted_price"), expires_at=now + 120,
            url=data["url"])
        self.db.execute("INSERT INTO intents(id,account_id,epoch,created,expires,payload) VALUES(?,?,?,?,?,?)",
            (identity, account_id, row["epoch"], now, now + 120, result.model_dump_json()))
        return result

    def intent(self, identity: str) -> TravelResult:
        row = self.db.execute("SELECT * FROM intents WHERE id=?", (identity,)).fetchone()
        if row is None:
            return TravelResult(status="not_found")
        result = TravelResult.model_validate_json(row["payload"])
        account = self.row(row["account_id"])
        if row["status"] == "cancelled" or account["epoch"] != row["epoch"]:
            result.status, result.url = "cancelled", None
        elif row["expires"] <= self.clock():
            result.status, result.url = "expired", None
        return result

    def cleanup(self) -> None:
        self.db.execute("DELETE FROM attempts WHERE expires<=?", (self.clock(),))
        self.db.execute("DELETE FROM intents WHERE created<?", (self.clock() - 86400,))


def refresh_time(now: int, lifetime: int) -> int:
    margin = min(86400, max(1, lifetime // 10))
    return now + max(1, lifetime - margin - secrets.randbelow(max(1, min(300, margin))))
