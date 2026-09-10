"""Documented GGG confidential-client OAuth only; no website-cookie adapter."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator


class OAuthError(Exception):
    def __init__(self, code: str, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


class Grant(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    access_token: str = Field(min_length=1, max_length=16384)
    refresh_token: str | None = Field(default=None, min_length=1, max_length=16384)
    expires_in: int = Field(gt=0, le=90 * 86400)
    token_type: str
    scope: str = Field(max_length=1024)
    sub: str = Field(max_length=64)

    @field_validator("access_token", "refresh_token")
    @classmethod
    def token(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[\x21-\x7e]+", value):
            raise ValueError("invalid_oauth_response")
        return value


@dataclass(frozen=True)
class OAuthConfig:
    client_id: str
    client_secret: str = field(repr=False)
    contact: str

    @classmethod
    def load(cls, path: Path) -> OAuthConfig | None:
        if not path.exists():
            return None
        if path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_size > 8192:
            raise ValueError("invalid_oauth_config_permissions")
        data = json.loads(path.read_text())
        return cls.parse(data)

    @classmethod
    def parse(cls, data: Any) -> OAuthConfig:
        if not isinstance(data, dict) or set(data) != {"client_id", "client_secret", "contact"}:
            raise ValueError("invalid_oauth_config")
        if any(not isinstance(v, str) or not 1 <= len(v) <= 2048 or not re.fullmatch(r"[\x21-\x7e]+", v) for v in data.values()):
            raise ValueError("invalid_oauth_config")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", data["client_id"]):
            raise ValueError("invalid_oauth_client_id")
        return cls(**data)


class GGGOAuth:
    def __init__(self, config: OAuthConfig, redirect_uri: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config, self.redirect_uri = config, redirect_uri
        self.http = httpx.AsyncClient(transport=transport, timeout=10, follow_redirects=False, trust_env=False,
            limits=httpx.Limits(max_connections=2), headers={"User-Agent":
            f"OAuth {config.client_id}/0.13.0 (contact: {config.contact}) poe2-gpt"})

    async def close(self) -> None:
        await self.http.aclose()

    def authorization_url(self, state: str, challenge: str) -> str:
        return "https://www.pathofexile.com/oauth/authorize?" + urlencode({
            "client_id": self.config.client_id, "response_type": "code", "scope": "account:profile",
            "redirect_uri": self.redirect_uri, "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256"})

    async def request(self, method: str, url: str, *, data: dict[str, str] | None = None,
                      token: str | None = None) -> dict[str, Any]:
        request = self.http.build_request(method, url, data=data,
            headers={"Authorization": "Bearer " + token} if token else {})
        request.headers.pop("cookie", None)
        try:
            response = await self.http.send(request, stream=True)
            try:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise OAuthError("invalid_oauth_response")
                if response.status_code == 429:
                    value = response.headers.get("retry-after", "60")
                    wait = max(1, min(int(value), 86400)) if value.isdigit() else 60
                    raise OAuthError("rate_limited", wait)
                if response.status_code != 200:
                    # Token POST results can be ambiguous. Never replay automatically.
                    raise OAuthError("reauth_required")
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise ValueError()
                return result
            finally:
                await response.aclose()
        except httpx.HTTPError:
            raise OAuthError("outcome_unknown") from None
        except (ValueError, TypeError):
            raise OAuthError("invalid_oauth_response") from None

    async def grant(self, fields: dict[str, str]) -> dict[str, Any]:
        raw = await self.request("POST", "https://www.pathofexile.com/oauth/token", data={
            "client_id": self.config.client_id, "client_secret": self.config.client_secret, **fields})
        try:
            grant = Grant.model_validate(raw)
            if grant.token_type.casefold() != "bearer" or set(grant.scope.split()) != {"account:profile"}:
                raise ValueError()
            UUID(grant.sub)
            return grant.model_dump(exclude_none=True)
        except (ValueError, TypeError):
            raise OAuthError("invalid_oauth_response") from None

    async def exchange(self, code: str, verifier: str) -> dict[str, Any]:
        return await self.grant({"grant_type": "authorization_code", "code": code,
            "code_verifier": verifier, "redirect_uri": self.redirect_uri, "scope": "account:profile"})

    async def refresh(self, token: str) -> dict[str, Any]:
        return await self.grant({"grant_type": "refresh_token", "refresh_token": token})

    async def profile(self, grant: dict[str, Any]) -> tuple[str, str]:
        data = await self.request("GET", "https://api.pathofexile.com/profile", token=grant["access_token"])
        from .accounts import RegisterAccountRequest
        try:
            identity = str(UUID(data["uuid"]))
            if identity != str(UUID(grant["sub"])):
                raise ValueError()
            name = RegisterAccountRequest(account_name=data["name"]).account_name
            return identity, name
        except (ValueError, TypeError, KeyError):
            raise OAuthError("account_mismatch") from None
