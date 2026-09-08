"""MCP-facing character schemas and private socket client. No raw provider data."""
from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Literal

import httpx
from pydantic import Field, field_validator

from .builds import DTO, BuildSummary, PlayerStat, bounded_dto


class CharacterError(Exception):
    pass


def safe_name(value: str, maximum: int = 64) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError("invalid_character_identifier")
    if any(unicodedata.category(c).startswith("C") or c in '/\\%?&<>\"' for c in value):
        raise ValueError("invalid_character_identifier")
    return value


def account_slug(value: str) -> str:
    safe_name(value)
    if not re.fullmatch(r"[^#]{1,54}[#-][0-9]{4,5}", value):
        raise ValueError("invalid_account_tag")
    return value.rsplit("#", 1)[0] + "-" + value.rsplit("#", 1)[1] if "#" in value else value


class AccountRequest(DTO):
    account_tag: Annotated[str, Field(min_length=6, max_length=64)]
    league: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")] | None = None
    offset: Annotated[int, Field(ge=0, le=1000)] = 0
    limit: Annotated[int, Field(ge=1, le=20)] = 20

    @field_validator("account_tag")
    @classmethod
    def account(cls, value):
        account_slug(value)
        return value


class CharacterRequest(DTO):
    account_tag: Annotated[str, Field(min_length=6, max_length=64)]
    league: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")] | None = None
    character_name: Annotated[str, Field(min_length=1, max_length=64)]

    @field_validator("account_tag")
    @classmethod
    def account(cls, value):
        account_slug(value)
        return value

    @field_validator("character_name")
    @classmethod
    def character(cls, value):
        return safe_name(value)


class CharacterIdentity(DTO):
    name: Annotated[str, Field(max_length=64)]
    league: Annotated[str, Field(max_length=48)]
    level: Annotated[int, Field(ge=1, le=100)] | None = None
    class_name: Annotated[str, Field(max_length=48)] | None = None

    @field_validator("name", "league", "class_name")
    @classmethod
    def identifiers(cls, value):
        return safe_name(value) if value is not None else None


class CharacterPage(DTO):
    account_slug: Annotated[str, Field(max_length=64)]
    characters: Annotated[list[CharacterIdentity], Field(max_length=20)]
    total: Annotated[int, Field(ge=0, le=1000)]
    next_offset: Annotated[int, Field(ge=0, le=1000)] | None = None
    retrieved_at_epoch: int
    source: Literal["poe.ninja"] = "poe.ninja"


class CharacterOverview(DTO):
    account_slug: Annotated[str, Field(max_length=64)]
    character: CharacterIdentity
    stats: Annotated[list[PlayerStat], Field(max_length=22)] = []
    pob_available: bool
    retrieved_at_epoch: int
    source_updated_at: Annotated[str, Field(max_length=40)] | None = None
    source: Literal["poe.ninja"] = "poe.ninja"
    live_game_state: Literal[False] = False


class CharacterImport(DTO):
    character: CharacterOverview
    build: BuildSummary
    reused: bool = False
    raw_payload_exposed: Literal[False] = False


class OpenAIFile(DTO):
    # All four properties are required in the schema by openai/fileParams;
    # only download_url and file_id are required in the value.
    download_url: Annotated[str, Field(min_length=1, max_length=8192)]
    file_id: Annotated[str, Field(min_length=1, max_length=200)]
    mime_type: Annotated[str, Field(max_length=100)] = "text/plain"
    file_name: Annotated[str, Field(max_length=200)] = "build.txt"


class AttachmentRequest(DTO):
    file: OpenAIFile


class AttachmentImport(DTO):
    build: BuildSummary
    reused: bool = False
    raw_payload_exposed: Literal[False] = False


class CharacterRefresh(DTO):
    status: Literal["requested", "cooldown", "authentication_required", "account_mismatch", "unavailable"]
    success: bool
    wait_seconds: Annotated[int, Field(ge=0, le=86400)] | None = None
    snapshot: CharacterOverview | None = None
    snapshot_error: Literal["character_unavailable"] | None = None
    # A successful POST is not proof that Ninja has completed a fresh GGG fetch.
    game_fetch_confirmed: Literal[False] = False


CHARACTER_INPUTS = {"list_account_characters": AccountRequest,
                    "get_character": CharacterRequest,
                    "refresh_character": CharacterRequest,
                    "import_pob_attachment": AttachmentRequest}
CHARACTER_OUTPUTS = {"list_account_characters": CharacterPage,
                     "get_character": CharacterImport,
                     "refresh_character": CharacterRefresh,
                     "import_pob_attachment": AttachmentImport}
CHARACTER_ERRORS = {"character_unavailable", "character_provider_busy", "character_rate_limited",
                    "character_not_found", "character_authentication_required", "character_schema_changed",
                    "character_import_unavailable", "character_storage_full", "invalid_character_request",
                    "character_ambiguous_league", "attachment_unavailable", "attachment_host_not_allowed",
                    "attachment_must_be_txt", "attachment_too_large"}


class CharacterClient:
    def __init__(self, socket: str, *, http=None):
        self.http = http or httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=socket),
            base_url="http://character-provider", timeout=60, trust_env=False, follow_redirects=False)

    async def close(self):
        await self.http.aclose()

    async def call(self, operation, request):
        try:
            async with self.http.stream("POST", "/" + operation, content=request.model_dump_json(),
                                        headers={"content-type": "application/json"}) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 8192:
                        raise CharacterError("character_unavailable")
                if response.status_code != 200:
                    import json
                    code = json.loads(body).get("code")
                    raise CharacterError(code if code in CHARACTER_ERRORS else "character_unavailable")
                return bounded_dto(CHARACTER_OUTPUTS[operation].model_validate_json(body))
        except CharacterError:
            raise
        except Exception:
            raise CharacterError("character_unavailable") from None
