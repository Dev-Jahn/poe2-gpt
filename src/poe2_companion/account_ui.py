"""Authenticated account UI. GET renders only; credentials stay in the broker."""
from __future__ import annotations

from html import escape
import re
import secrets
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .access import Principal
from .accounts import AccountClient, AccountView, BrokerError


HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
           "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://www.pathofexile.com; frame-ancestors 'none'; base-uri 'none'",
           "X-Content-Type-Options": "nosniff"}
STATES = {"active": "연결됨", "refresh_pending": "인증 갱신 대기 중", "unverified": "소유권 미확인", "reauth_required": "재로그인 필요", "disconnected": "연결 해제됨"}


class AccountUI:
    def __init__(self, app: ASGIApp, client: AccountClient, public_base: str, path: str, cookie_name: str) -> None:
        self.app, self.client, self.public_base, self.path, self.cookie_name = app, client, public_base, path, cookie_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == self.path or path.startswith(self.path + "/")):
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        principal = scope.get("state", {}).get("principal")
        if not isinstance(principal, Principal) or request.headers.get("host") != urlsplit(self.public_base).netloc:
            await Response(status_code=403, headers=HEADERS)(scope, receive, send)
            return
        browser = scope.get("state", {}).get("account_browser")
        new_browser = not isinstance(browser, str) or re.fullmatch(r"[0-9a-f]{64}", browser) is None
        if new_browser:
            browser = secrets.token_hex(32)
        try:
            response = await self.route(request, principal, browser, new_browser)
        except BrokerError:
            response = self.page("계정 서비스를 사용할 수 없습니다. 잠시 후 다시 열어 주세요.", 503)
        except Exception:
            # Never echo authorization codes, state or incoming form values.
            response = self.page("요청을 처리할 수 없습니다. 계정 화면을 다시 열어 주세요.", 400)
        response.headers.update(HEADERS)
        if new_browser and path == self.path and request.method == "GET":
            response.set_cookie(self.cookie_name, browser, max_age=8 * 3600, secure=True,
                httponly=True, samesite="lax", path=self.path)
        await response(scope, receive, send)

    def page(self, body: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse("<!doctype html><html lang='ko'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>PoE2 계정 연결</title>"
            "<style>body{font:16px system-ui;max-width:760px;margin:40px auto;padding:0 20px;line-height:1.6}"
            "article{border:1px solid #aaa;border-radius:8px;padding:16px;margin:16px 0}"
            "button{padding:8px 14px;margin:5px 5px 5px 0}form{display:inline-block}small{display:block}</style>"
            "<body><h1>게임 계정 연결</h1>" + body + "</body></html>", status_code=status, headers=HEADERS)

    def form(self, endpoint: str, csrf: str, label: str, fields: dict[str, str] | None = None) -> str:
        values = {"csrf": csrf, **(fields or {})}
        hidden = "".join(f'<input type="hidden" name="{escape(k, quote=True)}" value="{escape(v, quote=True)}">' for k, v in values.items())
        return f'<form method="post" action="{escape(self.path + endpoint, quote=True)}">{hidden}<button>{escape(label)}</button></form>'

    async def route(self, request: Request, principal: Principal, browser: str, new_browser: bool) -> Response:
        suffix = request.url.path[len(self.path):]
        if request.method in {"GET", "HEAD"} and not suffix:
            data = await self.client.call("ui_page", {"browser": browser}, principal)
            if data.get("status") != "ok":
                return self.page("계정 정보를 읽을 수 없습니다.", 403)
            csrf = data["csrf"]
            body = "<p>등록한 계정 이름과 연결 설정을 보관합니다. 실제 로그인 인증은 만료되거나 철회될 수 있으며, 그때는 재로그인이 필요합니다.</p>"
            if data["oauth_configured"]:
                body += self.form("/start", csrf, "Path of Exile 계정 연결 / 재로그인")
            else:
                body += "<p>공식 계정 로그인은 아직 사용할 수 없습니다. 서버 운영자가 GGG에 등록한 공식 API 앱과 콜백 주소를 설정해야 연결 버튼이 표시됩니다. 지금은 ChatGPT에서 계정 이름을 등록할 수 있습니다. 계정 이름 등록은 로그인이나 소유권 확인이 아닙니다.</p>"
            body += "<p>게임 은신처 이동은 향후 추가 기능입니다. 계정 연결과 poe.ninja 갱신, 게임 온라인 상태는 각각 별도이며, 현재 거래소 링크는 웹페이지를 엽니다.</p>"
            for raw in data["records"]:
                account = AccountView.model_validate(raw)
                body += f"<article><strong>{escape(account.display_name)}</strong> ({escape(account.provider)})<br>{STATES[account.session_status]}"
                if account.default_for_travel:
                    body += " · 기본 이동 계정"
                if account.refresh_absolute_expires_at:
                    from datetime import datetime, timezone
                    deadline = datetime.fromtimestamp(account.refresh_absolute_expires_at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    body += "<small>자동 갱신 가능 기한: " + deadline + "</small>"
                if account.next_action == "reauthenticate":
                    body += "<p>연결을 계속 사용하려면 재로그인해 주세요.</p>"
                if account.session_status != "disconnected":
                    fields = {"account_id": account.account_id}
                    body += self.form("/default", csrf, "기본 계정으로 선택", fields)
                    body += self.form("/refresh-setting", csrf, "자동 갱신 끄기" if account.auto_refresh else "자동 갱신 켜기",
                        {**fields, "enabled": "false" if account.auto_refresh else "true"})
                    body += self.form("/disconnect", csrf, "연결 해제", fields)
                body += "</article>"
            if not data["records"]:
                body += "<p>등록된 계정이 없습니다. ChatGPT에서 사용할 계정 이름을 등록하거나 위에서 공식 계정을 연결하세요.</p>"
            body += "<p>현재 은신처 이동은 공식 거래소에서 로그인 계정을 확인하고 이동 버튼을 눌러 주세요. 계정 연결만으로 게임 접속 상태를 확인하지는 않습니다.</p>"
            return self.page(body)
        if request.method == "GET" and suffix == "/callback":
            if new_browser or len(request.scope.get("query_string", b"")) > 4096:
                return self.page("연결을 시작한 브라우저에서 다시 시도해 주세요.", 400)
            pairs = list(request.query_params.multi_items())
            if len(pairs) != 2 or {k for k, _ in pairs} != {"code", "state"}:
                return self.page("로그인이 완료되지 않았습니다. 계정 화면에서 다시 시작해 주세요.", 400)
            data = await self.client.call("ui_callback", {"browser": browser, **dict(pairs)}, principal)
            if data.get("status") != "ok":
                return self.page("계정 연결에 실패했습니다. 계정 화면에서 다시 로그인해 주세요.", 400)
            return RedirectResponse(self.public_base + self.path, status_code=303)
        operations = {"/start": "ui_start", "/default": "ui_default", "/disconnect": "ui_disconnect", "/refresh-setting": "ui_refresh_setting"}
        if request.method != "POST" or suffix not in operations:
            return Response(status_code=405, headers=HEADERS)
        if new_browser or request.headers.get("origin") != self.public_base or request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            return Response(status_code=403, headers=HEADERS)
        form_body = bytearray()
        async for chunk in request.stream():
            form_body.extend(chunk)
            if len(form_body) > 4096:
                return Response(status_code=413, headers=HEADERS)
        pairs = parse_qsl(form_body.decode("utf-8"), max_num_fields=5, strict_parsing=True)
        values: dict[str, Any] = dict(pairs)
        if len(values) != len(pairs) or set(values) - {"csrf", "account_id", "enabled"}:
            return Response(status_code=400, headers=HEADERS)
        if "enabled" in values:
            if values["enabled"] not in {"true", "false"}:
                return Response(status_code=400, headers=HEADERS)
            values["enabled"] = values["enabled"] == "true"
        result = await self.client.call(operations[suffix], {"browser": browser, **values}, principal)
        if suffix == "/start" and result.get("status") == "ready":
            # The private adapter constructs this URL, but fail closed on origin.
            url = result["url"]
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.netloc != "www.pathofexile.com" or parsed.path != "/oauth/authorize":
                return Response(status_code=502, headers=HEADERS)
            return RedirectResponse(url, status_code=303)
        if result.get("status") == "disconnected":
            return self.page('<p>이 서버의 연결과 저장된 자격증명을 삭제했습니다. 공식 계정의 앱 권한도 철회하려면 '
                '<a href="https://www.pathofexile.com/my-account/applications">공식 앱 관리 화면</a>에서 해제하세요.</p>'
                f'<p><a href="{escape(self.path, quote=True)}">계정 목록</a></p>')
        if result.get("status") != "ok":
            return self.page("요청이 만료되었거나 처리할 수 없습니다. 계정 화면을 다시 열어 주세요.", 400)
        return RedirectResponse(self.public_base + self.path, status_code=303)
