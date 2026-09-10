"""Origin authentication for Cloudflare Access Managed OAuth deployments.

Cloudflare handles OAuth discovery, registration and user login. The origin
accepts only a signed Access assertion for its configured app and owner.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
import time
from collections.abc import Mapping

import httpx
import jwt
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from http.cookies import SimpleCookie, CookieError


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str


class AccessDenied(Exception):
    pass


class KeysUnavailable(Exception):
    pass


@dataclass(frozen=True)
class AccessConfig:
    issuer: str
    audience: str
    email: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> AccessConfig | None:
        fields = ("POE2_CF_TEAM_DOMAIN", "POE2_CF_AUDIENCE", "POE2_CF_OWNER_EMAIL")
        mode = env.get("POE2_AUTH_MODE", "none")
        if mode == "none" and not any(key in env for key in fields):
            return None
        if mode != "cloudflare-access":
            raise ValueError("Set POE2_AUTH_MODE=cloudflare-access with all three POE2_CF settings")
        team, audience, email = (env.get(key, "").strip() for key in fields)
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com", team):
            raise ValueError("POE2_CF_TEAM_DOMAIN must be the team hostname without a scheme or path")
        if not re.fullmatch(r"[a-f0-9]{64}", audience):
            raise ValueError("POE2_CF_AUDIENCE must be the application's 64-character AUD tag")
        if len(email) > 254 or not re.fullmatch(r"[^\s@,]+@[^\s@,]+\.[^\s@,]+", email):
            raise ValueError("POE2_CF_OWNER_EMAIL must contain one owner email")
        return cls("https://" + team, audience, email.casefold())


class AccessVerifier:
    def __init__(self, config: AccessConfig, *, transport=None, clock=time.monotonic):
        self.config = config
        self.client = httpx.AsyncClient(transport=transport, timeout=5, follow_redirects=False,
                                       trust_env=False, limits=httpx.Limits(max_connections=2))
        self.clock = clock
        self.keys: dict[str, object] = {}
        self.expires = 0.0
        self.retry_at = 0.0
        self.lock = asyncio.Lock()

    async def close(self):
        await self.client.aclose()

    async def _key(self, kid: str):
        async with self.lock:
            now = self.clock()
            if now < self.expires and kid in self.keys:
                return self.keys[kid]
            if now < self.retry_at:
                if now >= self.expires:
                    raise KeysUnavailable()
                raise AccessDenied()
            # Unknown key IDs cannot cause an unbounded series of remote fetches.
            self.retry_at = now + 30
            try:
                async with self.client.stream("GET", self.config.issuer + "/cdn-cgi/access/certs") as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise ValueError()
                data = json.loads(body)
                entries = data["keys"]
                if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
                    raise ValueError()
                keys = {}
                for entry in entries:
                    if (entry.get("kty") != "RSA" or entry.get("alg", "RS256") != "RS256"
                            or entry.get("use", "sig") != "sig"):
                        continue
                    key_id = entry["kid"]
                    if not isinstance(key_id, str) or not 1 <= len(key_id) <= 256 or key_id in keys:
                        raise ValueError()
                    key = jwt.PyJWK.from_dict(entry, algorithm="RS256").key
                    if key.key_size < 2048:
                        raise ValueError()
                    keys[key_id] = key
                if not keys:
                    raise ValueError()
                self.keys, self.expires = keys, now + 300
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, jwt.PyJWTError):
                raise KeysUnavailable() from None
            if kid not in self.keys:
                raise AccessDenied()
            return self.keys[kid]

    async def verify(self, token: str) -> Principal:
        try:
            if not 1 <= len(token) <= 16384:
                raise AccessDenied()
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or not 1 <= len(kid) <= 256:
                raise AccessDenied()
            if header.get("crit"):
                raise AccessDenied()
            key = await self._key(kid)
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=self.config.audience,
                                issuer=self.config.issuer, leeway=10,
                                options={"require": ["exp", "iat", "iss", "aud", "sub", "email"]})
            if (not isinstance(claims["sub"], str) or not claims["sub"]
                    or not isinstance(claims["email"], str)
                    or claims["email"].casefold() != self.config.email):
                raise AccessDenied()
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise AccessDenied() from None
        return Principal(self.config.issuer, claims["sub"])


class CloudflareAccessMiddleware:
    def __init__(self, app: ASGIApp, verifier: AccessVerifier, *, account_path: str | None = None,
                 account_cookie: str | None = None):
        self.app, self.verifier = app, verifier
        self.account_path, self.account_cookie = account_path, account_cookie

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        try:
            assertions = [v for k, v in scope["headers"] if k.lower() == b"cf-access-jwt-assertion"]
            if len(assertions) != 1:
                raise AccessDenied()
            principal = await self.verifier.verify(assertions[0].decode("ascii"))
        except (AccessDenied, UnicodeError):
            response = JSONResponse({"error": "access_denied"}, status_code=403,
                                    headers={"Cache-Control": "no-store"})
        except KeysUnavailable:
            response = JSONResponse({"error": "authentication_unavailable"}, status_code=503,
                                    headers={"Cache-Control": "no-store", "Retry-After": "30"})
        else:
            # Never expose identity assertions or browser/opaque tokens to MCP.
            clean_scope = dict(scope)
            clean_scope["state"] = {**scope.get("state", {}), "principal": principal}
            # Only account UI requests receive their own opaque browser binding.
            # Original website cookies and Access credentials remain stripped.
            if self.account_path and (scope.get("path") == self.account_path or
                                      scope.get("path", "").startswith(self.account_path + "/")):
                cookie = SimpleCookie()
                try:
                    for k, v in scope["headers"]:
                        if k.lower() == b"cookie" and len(v) <= 8192:
                            cookie.load(v.decode("ascii"))
                    value = cookie[self.account_cookie].value if self.account_cookie and self.account_cookie in cookie else ""
                    if re.fullmatch(r"[0-9a-f]{64}", value):
                        clean_scope["state"]["account_browser"] = value
                except (ValueError, UnicodeError, CookieError):
                    pass
            hidden = {b"cf-access-jwt-assertion", b"authorization", b"cookie",
                      b"cf-access-authenticated-user-email", b"cf-access-client-secret"}
            clean_scope["headers"] = [(k, v) for k, v in scope["headers"] if k.lower() not in hidden]
            return await self.app(clean_scope, receive, send)
        # Reject before consuming any request body. Cloudflare, not this origin,
        # supplies the public OAuth challenge and discovery endpoints.
        await response(scope, receive, send)
