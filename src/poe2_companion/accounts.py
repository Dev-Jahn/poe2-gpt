"""Closed account projections and per-member private broker client.

Credentials and OAuth callbacks never pass through model-facing tools.
"""
from __future__ import annotations

import hashlib
from typing import Annotated, Any, Literal

import httpx
from pydantic import Field

from .access import Principal
from .builds import DTO
from .equipment import Price
from .trade import SearchID

AccountID = Annotated[str, Field(pattern=r"^acct_[0-9a-f]{32}$")]
IntentID = Annotated[str, Field(pattern=r"^travel_[0-9a-f]{32}$")]
Provider = Literal["ggg", "kakao"]
Label = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f<>]+$")]


class AccountPageRequest(DTO):
    offset: Annotated[int, Field(ge=0, le=16)] = 0
    limit: Annotated[int, Field(ge=1, le=10)] = 5


class AccountRequest(DTO):
    account_id: AccountID


class RegisterAccountRequest(DTO):
    provider: Provider = "ggg"
    account_name: Label


class AccountLinkRequest(DTO):
    provider: Provider = "ggg"


class AccountView(DTO):
    account_id: AccountID
    provider: Provider
    display_name: Label
    verified: bool
    default_for_travel: bool
    auto_refresh: bool
    provider_configured: bool = False
    session_status: Literal["unverified", "active", "refresh_pending", "reauth_required", "disconnected"]
    renewal_status: Literal["available", "expiring", "unavailable", "disabled"]
    access_expires_at: int | None = None
    refresh_absolute_expires_at: int | None = None
    last_verified_at: int | None = None
    travel_capability: Literal["official_site_only"] = "official_site_only"
    next_action: Literal["none", "link_account", "reauthenticate", "reconnect", "enable_refresh", "wait_for_refresh", "configure_provider"]


class AccountPage(DTO):
    status: Literal["ok", "authentication_required", "identity_mismatch", "broker_unavailable"] = "ok"
    records: list[AccountView]
    total: int
    next_offset: int | None = None


class AccountResult(DTO):
    status: Literal["ok", "not_found", "limit_reached", "authentication_required", "identity_mismatch", "broker_unavailable"]
    account: AccountView | None = None


class AccountLinkResult(DTO):
    status: Literal["ready", "provider_not_configured", "provider_not_supported", "authentication_required", "identity_mismatch", "broker_unavailable"]
    url: str | None = None
    travel_link_supported: Literal[False] = False


class TravelRequest(DTO):
    search_id: SearchID
    listing_ref: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    account_id: AccountID | None = None


class TravelResultRequest(DTO):
    intent_id: IntentID


class TravelResult(DTO):
    status: Literal["prepared", "expired", "cancelled", "not_found", "account_selection_required",
                    "account_unavailable", "listing_unavailable", "search_unavailable",
                    "provider_not_supported",
                    "authentication_required", "identity_mismatch", "broker_unavailable"]
    mode: Literal["official_site"] = "official_site"
    intent_id: IntentID | None = None
    account_id: AccountID | None = None
    account_name: Label | None = None
    listing_ref: str | None = None
    quoted_price: Price | None = None
    expires_at: int | None = None
    expires_at_scope: Literal["receipt_only"] = "receipt_only"
    url: str | None = None
    game_action_executed: Literal[False] = False
    website_account_verified: Literal[False] = False


ACCOUNT_INPUTS: dict[str, type[DTO]] = {
    "get_game_accounts": AccountPageRequest,
    "register_game_account": RegisterAccountRequest,
    "begin_game_account_link": AccountLinkRequest,
    "set_default_game_account": AccountRequest,
    "get_game_connection_status": AccountRequest,
    "prepare_hideout_travel": TravelRequest,
    "get_hideout_travel_result": TravelResultRequest,
}


class BrokerError(Exception):
    """Only fixed public error codes may leave the private adapter."""


def principal_key(principal: Principal) -> str:
    return hashlib.sha256((principal.issuer + "\0" + principal.subject).encode()).hexdigest()


class AccountClient:
    def __init__(self, socket: str, *, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=socket), base_url="http://account-broker",
            timeout=20, trust_env=False, follow_redirects=False)

    async def close(self) -> None:
        await self.http.aclose()

    async def call(self, operation: str, payload: dict[str, Any], principal: Principal | None) -> dict[str, Any]:
        if principal is None:
            raise BrokerError("authentication_required")
        try:
            async with self.http.stream("POST", "/rpc", json={
                "operation": operation, "principal": principal_key(principal), "payload": payload,
            }) as response:
                body = bytearray()
                async for part in response.aiter_bytes():
                    body.extend(part)
                    if len(body) > 65536:
                        raise ValueError()
                if response.status_code == 403:
                    raise BrokerError("identity_mismatch")
                if response.status_code != 200:
                    raise ValueError()
                import json
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError()
                return data
        except (httpx.HTTPError, ValueError, TypeError):
            raise BrokerError("broker_unavailable") from None
