"""Typed, offline equipment snapshots and exact optimization of item-stat proxies.

No GGG internal API calls, website session cookies, raw items or PoB payloads.
The provider boundary is a validated snapshot; acquisition is user-operated.
"""
from __future__ import annotations

import itertools
import math
import re
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import unquote

from pydantic import Field, ValidationError, model_validator

from .builds import DTO, BuildError, bounded_dto, read_regular_file
from .scout import Scout

Currency = Literal["exalted", "chaos", "divine"]
Slot = Literal["helmet", "body_armour", "gloves", "boots", "belt", "amulet", "ring_left", "ring_right"]
Metric = Literal["flat_life", "flat_mana", "fire_resistance", "cold_resistance", "lightning_resistance",
                 "chaos_resistance", "strength", "dexterity", "intelligence", "item_armour",
                 "item_evasion", "item_energy_shield", "movement_speed"]
METRICS = set(Metric.__args__)
Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$", max_length=32)]
DatasetID = Annotated[str, Field(pattern=r"^gear_[0-9a-f]{32}$", max_length=37)]
LeagueName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 '\-]{0,79}$", max_length=80)]
Number = Annotated[float, Field(ge=-1e7, le=1e7, allow_inf_nan=False)]
MAX_DATASET_BYTES = 512 * 1024
MAX_COMBINATIONS = 200000
DATASET_RE = re.compile(r"gear_[0-9a-f]{32}\Z")
POLICY_URL = "https://www.pathofexile.com/developer/docs#resources"
TRADE_URL = "https://www.pathofexile.com/trade2"


def dec(value) -> Decimal:
    return Decimal(str(value))


def unique(rows, attr):
    if len({getattr(r, attr) for r in rows}) != len(rows):
        raise ValueError("duplicate_equipment_field")


class Stat(DTO):
    metric: Metric
    value: Number


class AggregateStat(DTO):
    metric: Metric
    value: Annotated[float, Field(ge=-1.6e8, le=1.6e8, allow_inf_nan=False)]


class Price(DTO):
    amount: Annotated[float, Field(gt=0, le=1e9, allow_inf_nan=False)]
    currency: Currency


class Equipped(DTO):
    key: Key
    slot: Slot
    stats: Annotated[list[Stat], Field(max_length=13)]

    @model_validator(mode="after")
    def consistent(self):
        unique(self.stats, "metric")
        return self


class Candidate(DTO):
    key: Key
    eligible_slots: Annotated[list[Slot], Field(min_length=1, max_length=2)]
    rarity: Literal["normal", "magic", "rare", "unique"] = "rare"
    corrupted: bool = False
    required_level: Annotated[int, Field(ge=0, le=100)] = 0
    unscored_modifier_count: Annotated[int, Field(ge=0, le=800)] = 0
    stats: Annotated[list[Stat], Field(max_length=13)]
    price: Price | None
    observed_at_epoch: Annotated[int, Field(ge=0, le=100000000000)]
    # Optional physical listing identity, used to reject duplicated observations.
    listing_ref: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", max_length=64)] | None = None
    source_search_url: Annotated[str, Field(max_length=220)] | None = None

    @model_validator(mode="after")
    def consistent(self):
        unique(self.stats, "metric")
        slots = set(self.eligible_slots)
        if len(slots) != len(self.eligible_slots) or (len(slots) > 1 and slots != {"ring_left", "ring_right"}):
            raise ValueError("invalid_eligible_slots")
        if self.source_search_url is not None and not re.fullmatch(
            r"https://www\.pathofexile\.com/trade2/search/(?:poe2/)?[A-Za-z0-9%'\-]{1,120}/[A-Za-z0-9]{1,20}", self.source_search_url
        ):
            raise ValueError("invalid_official_search_url")
        return self


class EquipmentInput(DTO):
    schema_version: Literal[1] = 1
    league: LeagueName
    build_id: Annotated[str, Field(pattern=r"^bld_[0-9a-f]{32}$", max_length=36)] | None = None
    origin: Literal["user_snapshot", "synthetic_example"] = "user_snapshot"
    metric_scope: Literal["sum_of_selected_item_values_not_character_stats"] = "sum_of_selected_item_values_not_character_stats"
    current: Annotated[list[Equipped], Field(min_length=1, max_length=8)]
    candidates: Annotated[list[Candidate], Field(max_length=160)]

    @model_validator(mode="after")
    def consistent(self):
        unique(self.current, "slot")
        keys = [x.key for x in [*self.current, *self.candidates]]
        refs = [x.listing_ref for x in self.candidates if x.listing_ref]
        if len(set(keys)) != len(keys) or len(set(refs)) != len(refs):
            raise ValueError("duplicate_item_or_listing")
        slots = {v.slot for v in self.current}
        for c in self.candidates:
            if not slots.intersection(c.eligible_slots):
                raise ValueError("candidate_has_no_current_slot")
            if c.source_search_url and unquote(c.source_search_url.split("/")[-2]) != self.league:
                raise ValueError("listing_league_mismatch")
        return self


class Dataset(EquipmentInput):
    origin: Literal["user_snapshot", "synthetic_example", "trade_snapshot"]
    dataset_id: DatasetID
    imported_at_epoch: Annotated[int, Field(ge=0, le=100000000000)]


class ProviderStatus(DTO):
    direct_equipment_api: bool = False
    adapter_implemented: Literal[True] = True
    acquisition: Literal["experimental_trade2_web_api_with_snapshot_fallback"] = "experimental_trade2_web_api_with_snapshot_fallback"
    browser_url: Literal["https://www.pathofexile.com/trade2"] = TRADE_URL
    policy_url: Literal["https://www.pathofexile.com/developer/docs#resources"] = POLICY_URL
    checked_on: Literal["2026-09-06"] = "2026-09-06"
    documented_developer_api: Literal[False] = False
    oauth_registration_needed_for_this_client: Literal[False] = False
    challenge_handling: Literal["stop_and_report_no_automatic_bypass"] = "stop_and_report_no_automatic_bypass"


class StatRange(DTO):
    metric: Metric
    minimum: Number | None = None
    maximum: Number | None = None

    @model_validator(mode="after")
    def bounds(self):
        if self.minimum is None and self.maximum is None:
            raise ValueError("empty_stat_range")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("reversed_stat_range")
        return self


class SearchFilters(DTO):
    slot: Slot
    price_max: Price | None = None
    rarity: Literal["any", "normal", "magic", "rare", "unique"] = "any"
    corrupted: bool | None = None
    required_level_max: Annotated[int, Field(ge=0, le=100)] = 100
    stats: Annotated[list[StatRange], Field(max_length=13)] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_metrics(self):
        unique(self.stats, "metric")
        return self


class SearchPlanRequest(DTO):
    league: LeagueName = "Forbidden Rites"
    filters: SearchFilters


class SearchPlan(DTO):
    integration: ProviderStatus
    league: LeagueName
    filters: SearchFilters
    search_executed: Literal[False] = False
    url_contains_filters: Literal[False] = False
    action: Literal["enter_filters_in_official_trade_UI_then_import_selected_candidates"] = "enter_filters_in_official_trade_UI_then_import_selected_candidates"
    item_stat_labels: Annotated[list[Metric], Field(max_length=13)]


class SnapshotQuery(DTO):
    dataset_id: DatasetID
    filters: SearchFilters
    reference_currency: Currency = "exalted"
    max_listing_age_seconds: Annotated[int, Field(ge=60, le=86400)] = 3600
    offset: Annotated[int, Field(ge=0, le=160)] = 0
    limit: Annotated[int, Field(ge=1, le=5)] = 5


class DatasetRequest(DTO):
    dataset_id: DatasetID


class DatasetSummary(DTO):
    dataset_id: DatasetID
    build_id: Annotated[str, Field(pattern=r"^bld_[0-9a-f]{32}$", max_length=36)] | None
    league: LeagueName
    origin: Literal["user_snapshot", "synthetic_example", "trade_snapshot"]
    imported_at_epoch: int
    current_slots: list[Slot]
    candidate_count: int
    available_metrics: list[Metric]
    live_listings: Literal[False] = False
    metric_scope: Literal["sum_of_selected_item_values_not_character_stats"] = "sum_of_selected_item_values_not_character_stats"


class FX(DTO):
    reference_currency: Currency
    rates: dict[Currency, Annotated[float, Field(gt=0, allow_inf_nan=False)]]
    source: Literal["same_currency_no_conversion", "poe2scout_reference_currencies"]
    retrieved_at: str | None
    source_updated_at: None = None
    executable_exchange_rate: Literal[False] = False


class CandidateRow(DTO):
    key: Key
    eligible_slots: list[Slot]
    stats: list[Stat]
    original_price: Price
    normalized_price: float
    observed_at_epoch: int
    source_search_url: str | None
    availability_verified: Literal[False] = False


class CandidatePage(DTO):
    dataset_id: DatasetID
    league: LeagueName
    origin: Literal["user_snapshot", "synthetic_example", "trade_snapshot"]
    fx: FX
    items: list[CandidateRow]
    matched_total: int
    next_offset: int | None
    excluded_counts: dict[Literal["stale", "missing_price", "missing_metrics", "filter_mismatch"], int]
    live_search: Literal[False] = False


class Weight(DTO):
    metric: Metric
    weight: Annotated[float, Field(gt=0, le=1e6, allow_inf_nan=False)]
    score_cap: Number | None = None


class Constraint(DTO):
    metric: Metric
    minimum_total: Number | None = None
    minimum_gain: Number | None = None

    @model_validator(mode="after")
    def meaningful(self):
        if self.minimum_total is None and self.minimum_gain is None:
            raise ValueError("empty_constraint")
        return self


class OptimizeRequest(DTO):
    dataset_id: DatasetID
    budget: Price
    mode: Literal["maximize_score", "minimize_cost"] = "maximize_score"
    weights: Annotated[list[Weight], Field(max_length=13)] = Field(default_factory=list)
    constraints: Annotated[list[Constraint], Field(max_length=13)] = Field(default_factory=list)
    candidate_keys: Annotated[list[Key], Field(min_length=1, max_length=80)] | None = None
    max_changes: Annotated[int, Field(ge=0, le=8)] = 2
    max_listing_age_seconds: Annotated[int, Field(ge=60, le=86400)] = 3600
    reserve_percent: Annotated[float, Field(ge=0, le=99, allow_inf_nan=False)] = 0
    top_k: Annotated[int, Field(ge=1, le=3)] = 3

    @model_validator(mode="after")
    def meaningful(self):
        unique(self.weights, "metric")
        unique(self.constraints, "metric")
        if self.mode == "maximize_score" and not self.weights:
            raise ValueError("explicit_weights_required")
        if self.mode == "minimize_cost" and not self.constraints:
            raise ValueError("explicit_constraints_required")
        if self.candidate_keys is not None and len(set(self.candidate_keys)) != len(self.candidate_keys):
            raise ValueError("duplicate_candidate_key")
        return self


class Change(DTO):
    slot: Slot
    previous_key: Key
    candidate_key: Key
    normalized_price: float


class UpgradePlan(DTO):
    cost: float
    budget_remaining: float
    score_gain: float
    changes: list[Change]
    item_totals: list[AggregateStat]
    item_deltas: list[AggregateStat]
    no_change: bool
    unscored_modifier_count: int


class UpgradeResult(DTO):
    dataset_id: DatasetID
    build_id: str | None
    league: LeagueName
    origin: Literal["user_snapshot", "synthetic_example", "trade_snapshot"]
    mode: Literal["maximize_score", "minimize_cost"]
    fx: FX
    budget_available: float
    baseline_item_totals: list[AggregateStat]
    plans: list[UpgradePlan]
    combinations_examined: int
    feasible_combinations: int
    eligible_candidates: int
    excluded_counts: dict[Literal["stale", "missing_price", "missing_metrics"], int]
    exact_within_eligible_candidates: Literal[True] = True
    output_truncated: bool = False
    metric_scope: Literal["sum_of_selected_item_values_not_character_stats"] = "sum_of_selected_item_values_not_character_stats"
    character_recalculated: Literal[False] = False
    equipment_requirements_verified: Literal[False] = False
    live_availability_verified: Literal[False] = False
    resale_credit_included: Literal[False] = False


class EquipmentService:
    def __init__(self, directory: str | Path, scout: Scout, clock=time.time):
        self.root, self.scout, self.clock = Path(directory).resolve(), scout, clock

    def load(self, dataset_id: str) -> Dataset:
        if not isinstance(dataset_id, str) or not DATASET_RE.fullmatch(dataset_id):
            raise BuildError("invalid_equipment_reference")
        try:
            data = Dataset.model_validate_json(read_regular_file(self.root/(dataset_id+".json"), MAX_DATASET_BYTES))
        except (ValidationError, ValueError, RecursionError):
            raise BuildError("invalid_equipment_snapshot") from None
        if data.dataset_id != dataset_id or data.imported_at_epoch > self.clock()+300 or any(c.observed_at_epoch > self.clock()+300 for c in data.candidates):
            raise BuildError("invalid_equipment_snapshot")
        return data

    def summary(self, request: DatasetRequest) -> DatasetSummary:
        data = self.load(request.dataset_id)
        return bounded_dto(DatasetSummary(dataset_id=data.dataset_id, build_id=data.build_id, league=data.league,
            origin=data.origin, imported_at_epoch=data.imported_at_epoch, current_slots=[v.slot for v in data.current],
            candidate_count=len(data.candidates), available_metrics=sorted({s.metric for c in [*data.current,*data.candidates] for s in c.stats})))

    async def fx(self, league: str, currencies: set[str], reference: Currency) -> FX:
        if currencies <= {reference}:
            return FX(reference_currency=reference, rates={reference:1.0}, source="same_currency_no_conversion", retrieved_at=None)
        catalog = await self.scout.catalog(league, allow_stale=False)
        refs = {v["api_id"]:v["relative_price"] for v in catalog["data"]["reference_currencies"]}
        if any(not refs.get(c) or not math.isfinite(refs[c]) for c in currencies | {reference}):
            raise BuildError("currency_conversion_unavailable")
        return FX(reference_currency=reference, rates={c:float(dec(refs[c])/dec(refs[reference])) for c in currencies | {reference}},
            source="poe2scout_reference_currencies", retrieved_at=catalog["retrieved_at"])

    def eligible(self, data: Dataset, age: int, required: set[str]):
        rows, excluded = [], Counter()
        for c in data.candidates:
            if self.clock() - c.observed_at_epoch > age:
                excluded["stale"] += 1
            elif c.price is None:
                excluded["missing_price"] += 1
            elif not required <= {s.metric for s in c.stats}:
                excluded["missing_metrics"] += 1
            else:
                rows.append(c)
        return rows, excluded

    async def search(self, request: SnapshotQuery) -> CandidatePage:
        data, f = self.load(request.dataset_id), request.filters
        candidates, excluded = self.eligible(data, request.max_listing_age_seconds, {s.metric for s in f.stats})
        filtered = []
        for c in candidates:
            values = {s.metric:s.value for s in c.stats}
            if f.slot not in c.eligible_slots or (f.rarity != "any" and c.rarity != f.rarity) or (f.corrupted is not None and c.corrupted != f.corrupted) or c.required_level > f.required_level_max or any(
                (s.minimum is not None and values[s.metric] < s.minimum) or (s.maximum is not None and values[s.metric] > s.maximum) for s in f.stats):
                excluded["filter_mismatch"] += 1
                continue
            filtered.append(c)
        currencies = {c.price.currency for c in filtered}
        if f.price_max:
            currencies.add(f.price_max.currency)
        fx = await self.fx(data.league, currencies, request.reference_currency)
        rows = []
        for c in filtered:
            price = dec(c.price.amount)*dec(fx.rates[c.price.currency])
            if f.price_max and price > dec(f.price_max.amount)*dec(fx.rates[f.price_max.currency]):
                excluded["filter_mismatch"] += 1
                continue
            rows.append((price, c))
        rows.sort(key=lambda row:(row[0],row[1].key))
        page = rows[request.offset:request.offset+request.limit]
        return bounded_dto(CandidatePage(dataset_id=data.dataset_id, league=data.league, origin=data.origin, fx=fx,
            items=[CandidateRow(key=c.key, eligible_slots=c.eligible_slots, stats=c.stats, original_price=c.price,
                normalized_price=float(p), observed_at_epoch=c.observed_at_epoch, source_search_url=c.source_search_url) for p,c in page],
            matched_total=len(rows), next_offset=request.offset+request.limit if request.offset+request.limit<len(rows) else None,
            excluded_counts=dict(excluded)))

    async def optimize(self, request: OptimizeRequest) -> UpgradeResult:
        return await self.optimize_data(self.load(request.dataset_id), request)

    async def optimize_data(self, data: Dataset, request: OptimizeRequest) -> UpgradeResult:
        if data.dataset_id != request.dataset_id:
            raise BuildError("invalid_equipment_reference")
        metrics = sorted({v.metric for v in [*request.weights,*request.constraints]})
        required = set(metrics)
        if any(not required <= {s.metric for s in c.stats} for c in data.current):
            raise BuildError("current_equipment_metrics_incomplete")
        if request.candidate_keys is not None:
            selected = set(request.candidate_keys)
            if not selected <= {c.key for c in data.candidates}:
                raise BuildError("unknown_candidate_key")
            data = data.model_copy(update={"candidates":[c for c in data.candidates if c.key in selected]})
        candidates, excluded = self.eligible(data, request.max_listing_age_seconds, required)
        fx = await self.fx(data.league, {c.price.currency for c in candidates}, request.budget.currency)
        costs = {c.key:dec(c.price.amount)*dec(fx.rates[c.price.currency]) for c in candidates}
        budget = dec(request.budget.amount)*(1-dec(request.reserve_percent)/100)
        current = sorted(data.current, key=lambda c:c.slot)
        choices = [[v for v in candidates if c.slot in v.eligible_slots and costs[v.key] <= budget] for c in current]
        slot_groups = [group for size in range(min(request.max_changes,len(current))+1)
                       for group in itertools.combinations(range(len(current)),size)]
        count = sum(math.prod(len(choices[i]) for i in group) for group in slot_groups)
        if count > MAX_COMBINATIONS:
            raise BuildError("candidate_space_too_large_narrow_candidates")
        values = {c.key:{s.metric:dec(s.value) for s in c.stats} for c in [*current,*candidates]}
        baseline = {m:sum((values[c.key][m] for c in current),Decimal(0)) for m in metrics}

        def score(totals):
            return sum((dec(w.weight)*(min(totals[w.metric],dec(w.score_cap)) if w.score_cap is not None else totals[w.metric]) for w in request.weights),Decimal(0))

        base_score = score(baseline)
        def selections():
            for group in slot_groups:
                for replacements in itertools.product(*(choices[i] for i in group)):
                    selected = list(current)
                    for i, replacement in zip(group,replacements):
                        selected[i] = replacement
                    yield selected

        best, examined, feasible = [], 0, 0
        for selected in selections():
            examined += 1
            if len({c.key for c in selected}) != len(selected):
                continue  # One physical ring cannot fill both ring slots.
            changes = [(old,new) for old,new in zip(current,selected) if old.key != new.key]
            if len(changes) > request.max_changes:
                continue
            cost = sum((costs[new.key] for _,new in changes),Decimal(0))
            if cost > budget:
                continue
            totals = {m:sum((values[c.key][m] for c in selected),Decimal(0)) for m in metrics}
            if any((c.minimum_total is not None and totals[c.metric] < dec(c.minimum_total)) or
                   (c.minimum_gain is not None and totals[c.metric]-baseline[c.metric] < dec(c.minimum_gain)) for c in request.constraints):
                continue
            feasible += 1
            gain = score(totals)-base_score
            tie = tuple(c.key for c in selected)
            rank = (-gain,cost,len(changes),tie) if request.mode == "maximize_score" else (cost,-gain,len(changes),tie)
            best.append((rank,cost,gain,changes,totals))
            best.sort(key=lambda x:x[0])
            del best[request.top_k:]
        plans = [UpgradePlan(cost=float(cost), budget_remaining=float(budget-cost), score_gain=float(gain),
            changes=[Change(slot=old.slot,previous_key=old.key,candidate_key=new.key,normalized_price=float(costs[new.key])) for old,new in changes],
            item_totals=[AggregateStat(metric=m,value=float(totals[m])) for m in metrics],
            item_deltas=[AggregateStat(metric=m,value=float(totals[m]-baseline[m])) for m in metrics], no_change=not changes,
            unscored_modifier_count=sum(new.unscored_modifier_count for _,new in changes))
            for _,cost,gain,changes,totals in best]
        result=UpgradeResult(dataset_id=data.dataset_id, build_id=data.build_id, league=data.league, origin=data.origin,
            mode=request.mode, fx=fx, budget_available=float(budget), baseline_item_totals=[AggregateStat(metric=m,value=float(baseline[m])) for m in metrics],
            plans=plans, combinations_examined=examined, feasible_combinations=feasible, eligible_candidates=len(candidates), excluded_counts=dict(excluded))
        # Leave room for the trade bridge's provenance wrapper inside 8 KiB.
        while len(result.model_dump_json().encode())>7000 and len(result.plans)>1:
            result.plans.pop()
            result.output_truncated=True
        return bounded_dto(result)


def prepare_search(request: SearchPlanRequest) -> SearchPlan:
    return bounded_dto(SearchPlan(integration=ProviderStatus(), league=request.league, filters=request.filters,
        item_stat_labels=[v.metric for v in request.filters.stats]))
