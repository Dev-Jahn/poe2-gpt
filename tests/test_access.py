import asyncio
import json
import time

from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import jwt
import pytest
from starlette.responses import JSONResponse

from poe2_companion.access import (AccessConfig, AccessDenied, AccessVerifier,
                                   CloudflareAccessMiddleware, KeysUnavailable)

CONFIG = AccessConfig("https://test-team.cloudflareaccess.com", "a" * 64, "owner@example.com")
PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk(private=PRIVATE, kid="first"):
    result = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    return {**result, "kid": kid, "alg": "RS256", "use": "sig"}


def token(*, private=PRIVATE, kid="first", omit=(), **changes):
    now = int(time.time())
    claims = {"iss": CONFIG.issuer, "aud": [CONFIG.audience], "sub": "owner-subject",
              "email": CONFIG.email, "iat": now, "exp": now + 300, **changes}
    for key in omit:
        claims.pop(key)
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid})


def verifier():
    return AccessVerifier(CONFIG, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"keys": [jwk()]})))


def test_config_is_explicit_and_complete():
    assert AccessConfig.from_env({}) is None
    values = {"POE2_AUTH_MODE": "cloudflare-access", "POE2_CF_TEAM_DOMAIN": "test-team.cloudflareaccess.com",
              "POE2_CF_AUDIENCE": CONFIG.audience, "POE2_CF_OWNER_EMAIL": CONFIG.email}
    assert AccessConfig.from_env(values) == CONFIG
    for key in values:
        with pytest.raises(ValueError):
            AccessConfig.from_env({k: v for k, v in values.items() if k != key})
    for team in ("https://test.cloudflareaccess.com", "localhost", "test.cloudflareaccess.com.evil.test", "a/b.cloudflareaccess.com"):
        with pytest.raises(ValueError):
            AccessConfig.from_env({**values, "POE2_CF_TEAM_DOMAIN": team})


@pytest.mark.parametrize("changes", [
    {"aud": ["b" * 64]}, {"iss": "https://wrong.cloudflareaccess.com"},
    {"email": "another@example.com"}, {"sub": ""}, {"exp": 1},
    {"nbf": int(time.time()) + 1000}, {"iat": int(time.time()) + 1000},
    {"omit": ["email"]}, {"omit": ["exp"]}, {"omit": ["sub"]},
    {"private": OTHER},
])
async def test_invalid_assertions_are_rejected(changes):
    check = verifier()
    try:
        with pytest.raises(AccessDenied):
            await check.verify(token(**changes))
    finally:
        await check.close()


async def test_valid_signature_owner_and_header_scrubbing():
    check = verifier()
    seen = []
    async def app(scope, receive, send):
        seen.append(scope)
        await JSONResponse({"ok": True})(scope, receive, send)
    secured = CloudflareAccessMiddleware(app, check)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=secured), base_url="http://test") as client:
            response = await client.post("/mcp", headers={"Cf-Access-Jwt-Assertion": token(email="OWNER@example.com"),
                "Authorization": "Bearer opaque-secret", "Cookie": "private-cookie"}, content=b"body")
            assert response.status_code == 200
            assert not {b"cf-access-jwt-assertion", b"authorization", b"cookie"}.intersection(dict(seen[0]["headers"]))
            seen.clear()
            for headers in ({}, {"Cf-Access-Jwt-Assertion": "invalid-secret"},
                            [("Cf-Access-Jwt-Assertion", token()), ("Cf-Access-Jwt-Assertion", token())]):
                response = await client.post("/mcp", headers=headers, content=b"raw-must-not-echo")
                assert response.status_code == 403 and response.json() == {"error": "access_denied"}
                assert response.headers["cache-control"] == "no-store"
            assert seen == []
    finally:
        await check.close()


async def test_reject_does_not_consume_body_or_fetch_keys():
    async def forbidden(*args):
        raise AssertionError("Must not be called")
    check = AccessVerifier(CONFIG, transport=httpx.MockTransport(forbidden))
    secured = CloudflareAccessMiddleware(forbidden, check)
    sent = []
    async def send(message):
        sent.append(message)
    await secured({"type": "http", "headers": []}, forbidden, send)
    assert sent[0]["status"] == 403
    await check.close()


async def test_rotation_cache_concurrency_and_outage():
    now = [1.0]
    calls = []
    fail = [False]
    def backend(request):
        assert str(request.url) == CONFIG.issuer + "/cdn-cgi/access/certs"
        calls.append(request)
        return httpx.Response(503) if fail[0] else httpx.Response(200, json={"keys": [jwk(), jwk(OTHER, "second")]})
    check = AccessVerifier(CONFIG, clock=lambda: now[0], transport=httpx.MockTransport(backend))
    try:
        await asyncio.gather(*(check.verify(token()) for _ in range(10)))
        assert len(calls) == 1
        await check.verify(token(private=OTHER, kid="second"))
        for i in range(20):
            with pytest.raises(AccessDenied):
                await check.verify(token(kid=f"unknown-{i}"))
        assert len(calls) == 1
        now[0] += 31
        with pytest.raises(AccessDenied):
            await check.verify(token(kid="unknown"))
        assert len(calls) == 2
        now[0] += 301
        fail[0] = True
        for _ in range(3):
            with pytest.raises(KeysUnavailable):
                await check.verify(token())
        assert len(calls) == 3
        now[0] += 31
        fail[0] = False
        await check.verify(token())
    finally:
        await check.close()


@pytest.mark.parametrize("payload", [{"keys": []}, {"keys": [None]}, {"keys": [jwk(), jwk()]}, {"huge": "a" * 65536}])
async def test_bad_jwks_fails_closed(payload):
    check = AccessVerifier(CONFIG, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    try:
        with pytest.raises(KeysUnavailable):
            await check.verify(token())
    finally:
        await check.close()


async def test_algorithm_confusion_and_header_url_cannot_choose_keys():
    check = verifier()
    try:
        with pytest.raises(AccessDenied):
            await check.verify(jwt.encode({"email": CONFIG.email}, "s" * 64, algorithm="HS256", headers={"kid": "first"}))
        # Even a signed token's jku has no influence over the configured issuer/JWKS URL.
        claims = jwt.decode(token(), PRIVATE.public_key(), algorithms=["RS256"], audience=CONFIG.audience)
        await check.verify(jwt.encode(claims, PRIVATE, algorithm="RS256",
            headers={"kid": "first", "jku": "http://127.0.0.1/private"}))
    finally:
        await check.close()
