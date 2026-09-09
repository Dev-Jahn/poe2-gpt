"""Explicit public contracts for price provenance and arithmetic quotations."""
from typing import Annotated, Generic, Literal, TypeVar
from pydantic import Field
from .builds import DTO

PositivePrice = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Data = TypeVar('Data')


class Warning(DTO):
    code: str
    message: str


class Snapshot(DTO):
    retrieved_at: str
    cache_age_seconds: PositivePrice
    delivery: Literal['network','cache','stale_cache']
    stale: bool


class CategorySnapshot(Snapshot):
    category: str


class Envelope(Snapshot, Generic[Data]):
    data: Data
    warning: Warning | None = None


class League(DTO):
    value: str
    short_name: str
    is_current: bool
    base_currency_api_id: str | None
    base_currency_base_item_type_id: str | None
    base_currency_text: str


class Leagues(DTO):
    leagues: list[League]
    source_url: str


class Category(DTO):
    api_id: str
    label: str


class ReferenceCurrency(DTO):
    api_id: str | None
    base_item_type_id: str | None
    text: str
    relative_price: PositivePrice


class Categories(DTO):
    league: League
    categories: list[Category]
    reference_currencies: list[ReferenceCurrency]
    source_urls: list[str]


class DisplayName(DTO):
    name: str
    name_ko: str | None
    name_source_ko: str | None


class PriceUnit(DisplayName):
    id: str


class CurrencyItem(DisplayName):
    item_id: int
    api_id: str | None
    base_item_type_id: str | None
    category: str
    unit_price: PositivePrice | None
    price_status: Literal['available','unavailable']
    source_quantity: int | None
    latest_history_bucket_at: str | None
    source_url: str


class Prices(DTO):
    league: str
    league_slug: str
    realm: Literal['poe2']
    category: str
    reference_currency: PriceUnit
    price_semantics: str
    source_updated_at: None
    source_time_note: str
    source_urls: list[str]
    items: Annotated[list[CurrencyItem], Field(max_length=100)]
    matched_total: int
    offset: int
    next_offset: int | None


class PriceResponse(Envelope[Prices]):
    metadata_snapshot: Snapshot


class FailedCategory(Warning):
    category: str


class CurrencySearch(DTO):
    league: str
    reference_currency: str
    query: str
    items: Annotated[list[CurrencyItem], Field(max_length=100)]
    matched_total: int
    truncated: bool
    complete: bool
    failed_categories: list[FailedCategory]
    snapshots: list[CategorySnapshot]
    source_updated_at: None
    note: str


class ValuedItem(CurrencyItem):
    quantity: PositivePrice
    estimated_total: PositivePrice | None


class CurrencyQuote(DTO):
    league: str
    realm: Literal['poe2']
    reference_currency: PriceUnit
    items: Annotated[list[ValuedItem], Field(max_length=30)]
    estimated_total: PositivePrice | None
    complete: bool
    stale: bool
    source_updated_at: None
    snapshots: list[CategorySnapshot]
    note: str
