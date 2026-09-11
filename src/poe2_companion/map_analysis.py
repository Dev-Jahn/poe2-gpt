"""Explicit map modifiers and observed-run economics, never invented drop rates."""
from __future__ import annotations
import secrets
import time
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .builds import DTO, bounded_dto
from .capabilities import digest
from .engine_models import EngineSnapshot
from .equipment import LeagueName, Currency
from .profiles import Digest
from .recovery import RecoveryRequest, RecoveryResult, analyze as recovery
from .workflow_store import DecisionStore, WorkflowError

RULE_SOURCE = 'https://poe2db.tw/us/Waystones'
RULE_RETRIEVED = '2026-09-11'
# Effect meanings agree with pinned ModMap.lua; its tiers/ranges differ from
# current extracted game data. Never reuse the native hand-written roll table.
RULES = {
    'map:less_life_es_recovery': ('Life/ES recovery rate is reduced; mana is outside this modifier.',20,40),
    'map:less_cooldown_recovery': ('Cooldown recovery is reduced; re-evaluate cooldown-dependent skill uptime.',15,30),
    'map:reduced_extra_critical_damage': ('Enemies mitigate extra critical damage; critical uptime alone does not preserve DPS.',15,30),
    'map:reduced_maximum_resistances': ('Maximum resistance is reduced; previous elemental damage tolerance is not reusable.',3,10),
}
RuleID = Literal['map:less_life_es_recovery','map:less_cooldown_recovery',
    'map:reduced_extra_critical_damage','map:reduced_maximum_resistances']
RunID = Annotated[str, Field(pattern=r'^run_[0-9a-f]{32}$')]
Amount = Annotated[float, Field(ge=0,le=1e12,allow_inf_nan=False)]


class MapModifier(DTO):
    rule_id: RuleID
    source: Literal['waystone','tablet'] = 'waystone'
    magnitude_percent: Annotated[float, Field(ge=0,le=100,allow_inf_nan=False)]
    effect_multiplier: Annotated[float, Field(ge=0,le=5,allow_inf_nan=False)] = 1.0
    evidence: Literal['user_transcribed_item','user_supplied_hypothesis']


class MapRequest(DTO):
    tier: Annotated[int, Field(ge=1,le=16)]
    encounter: Literal['mapping','ritual','boss_no_adds','breach','expedition']
    game_patch: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+\.[0-9]+[a-z]?$')]
    modifiers: Annotated[list[MapModifier], Field(max_length=8)] = Field(default_factory=list)
    unknown_modifier_text: Annotated[list[Annotated[str, Field(max_length=240)]], Field(max_length=12)] = Field(default_factory=list)
    confined_space: bool | None = None
    pack_density: Literal['low','ordinary','high','unknown'] = 'unknown'
    recovery_scenario: RecoveryRequest | None = None
    recovery_parameters_already_include_map_modifiers: bool = False

    @model_validator(mode='after')
    def context(self) -> Self:
        if self.encounter == 'ritual' and self.recovery_scenario and self.recovery_scenario.scenario not in {'ritual','continuous_hits'}:
            raise ValueError('ritual_requires_repeated_hit_scenario')
        if self.encounter == 'boss_no_adds' and self.recovery_scenario and self.recovery_scenario.scenario != 'boss_no_adds':
            raise ValueError('boss_requires_no_adds_scenario')
        return self


class MapInteraction(DTO):
    rule_id: RuleID
    source: Literal['waystone','tablet']
    status: Literal['source_semantics_matched','source_or_roll_unverified']
    effective_magnitude_percent: float
    explanation: str
    source_url: str
    source_checked_on: str
    source_declared_patch: None = None
    native_roll_table_reused: Literal[False] = False


class MapAnalysis(DTO):
    tier: int
    encounter: str
    game_patch: str
    assumptions_digest: Digest
    interactions: list[MapInteraction]
    unknown_modifier_count: int
    required_actions: list[str]
    recovery: RecoveryResult | None
    map_rule_patch_certified: Literal[False] = False
    safe_from_tier_alone: Literal[False] = False
    safe_to_run_certified: Literal[False] = False
    drop_probabilities_available: Literal[False] = False


def analyze(request: MapRequest, snapshot: EngineSnapshot | None = None) -> MapAnalysis:
    interactions=[]
    actions=['confirm_item_modifiers_and_current_patch','validate_damage_schedule_in_game']
    scenario=request.recovery_scenario.model_copy(deep=True) if request.recovery_scenario else None
    for mod in request.modifiers:
        explanation,low,high=RULES[mod.rule_id]
        matched=mod.source=='waystone' and low<=mod.magnitude_percent<=high
        magnitude=mod.magnitude_percent*mod.effect_multiplier
        interactions.append(MapInteraction(rule_id=mod.rule_id,source=mod.source,
            status='source_semantics_matched' if matched else 'source_or_roll_unverified',
            effective_magnitude_percent=magnitude,explanation=explanation,source_url=RULE_SOURCE,source_checked_on=RULE_RETRIEVED))
        if not matched: actions.append('verify_modifier_source_or_roll')
        if mod.rule_id=='map:less_life_es_recovery':
            actions.append('compare_deficit_limited_recovery_under_hits')
            if scenario and not request.recovery_parameters_already_include_map_modifiers:
                # This is a stated mathematical scenario, not certification of
                # current patch or actual map-effect multiplier.
                factor=max(0.0,1.0-magnitude/100)
                for resource in scenario.resources:
                    if resource.resource in {'life','energy_shield'}:
                        resource.regeneration_per_second*=factor
                        resource.recharge_per_second*=factor
                for flow in scenario.flows:
                    if flow.resource in {'life','energy_shield'}: flow.potential_per_second*=factor
        elif mod.rule_id=='map:reduced_extra_critical_damage': actions.append('recalculate_critical_damage_for_this_enemy')
        elif mod.rule_id=='map:less_cooldown_recovery': actions.append('recalculate_cooldowns_and_rotation')
        else: actions.append('recalculate_resistances_and_incoming_damage')
    if request.unknown_modifier_text: actions.append('resolve_unknown_modifiers_before_safety_claim')
    if request.encounter=='ritual' or request.confined_space or request.pack_density=='high':
        actions.append('use_explicit_repeated_hits_not_no_hit_recharge')
    if scenario is None: actions.append('supply_recovery_scenario_for_sustain_evaluation')
    if scenario is not None and snapshot is None: raise WorkflowError('map_recovery_calculation_required')
    result=recovery(scenario,snapshot) if scenario is not None and snapshot is not None else None
    return bounded_dto(MapAnalysis(tier=request.tier,encounter=request.encounter,game_patch=request.game_patch,
        assumptions_digest=digest(request.model_dump(mode='json')),interactions=interactions,
        unknown_modifier_count=len(request.unknown_modifier_text),required_actions=list(dict.fromkeys(actions)),recovery=result))


class RunObservationRequest(DTO):
    league: LeagueName
    encounter_key: Annotated[str, Field(pattern=r'^[a-z][a-z0-9_:-]{1,79}$')]
    scenario_digest: Digest
    observed_at_epoch: Annotated[int, Field(ge=0,le=100000000000)]
    duration_seconds: Annotated[float, Field(gt=0,le=86400,allow_inf_nan=False)]
    deaths: Annotated[int, Field(ge=0,le=1000)]
    reference_currency: Currency = 'divine'
    entry_and_consumable_cost: Amount
    realized_loot_proceeds: Amount
    unsold_loot_ask_low: Amount = 0.0
    unsold_loot_ask_high: Amount = 0.0
    evidence: Literal['user_observed_completed_run']
    persist_observation: bool = False

    @model_validator(mode='after')
    def range(self) -> Self:
        if self.unsold_loot_ask_low>self.unsold_loot_ask_high: raise ValueError('unsold_ask_interval_invalid')
        return self


class RunObservation(DTO):
    run_id: RunID
    request: RunObservationRequest
    artifact_digest: Digest
    created_at_epoch: int
    expires_at_epoch: int
    independently_verified: Literal[False] = False


class RunSummary(DTO):
    run_id: RunID
    artifact_digest: Digest
    expires_at_epoch: int
    realized_net: float
    unsold_loot_is_realized_income: Literal[False] = False


class ProfitRequest(DTO):
    run_ids: Annotated[list[RunID], Field(min_length=1,max_length=100)]
    @model_validator(mode='after')
    def distinct(self) -> Self:
        if len(set(self.run_ids)) != len(self.run_ids): raise ValueError('duplicate_run_observation')
        return self


class ProfitAnalysis(DTO):
    sample_count: int
    league: str
    encounter_key: str
    scenario_digest: Digest
    reference_currency: str
    observed_cost: float
    observed_realized_proceeds: float
    observed_realized_net: float
    observed_seconds: float
    deaths: int
    realized_net_per_hour: float
    observed_run_net_min: float
    observed_run_net_max: float
    hypothetical_net_with_unsold_asks_low: float
    hypothetical_net_with_unsold_asks_high: float
    sample_size_warning: Literal['few_runs','observed_sample_still_not_population']
    interval_method: Literal['observed_range_not_confidence_interval'] = 'observed_range_not_confidence_interval'
    future_drop_rate_estimated: Literal[False] = False
    asking_prices_are_realized_sales: Literal[False] = False


class RunReference(DTO):
    run_id: RunID


def record(request: RunObservationRequest, store: DecisionStore, owner: str) -> RunSummary:
    now=int(time.time())
    if request.observed_at_epoch>now+300: raise WorkflowError('run_observation_timestamp_in_future')
    value=RunObservation(run_id='run_'+secrets.token_hex(16),request=request,artifact_digest='0'*64,
        created_at_epoch=now,expires_at_epoch=now+(90*86400 if request.persist_observation else 3600))
    value.artifact_digest=digest(value.model_dump(mode='json',exclude={'artifact_digest'}))
    store.save_artifact(owner,'encounter_observation',value.run_id,value,value.expires_at_epoch,request.persist_observation)
    return RunSummary(run_id=value.run_id,artifact_digest=value.artifact_digest,expires_at_epoch=value.expires_at_epoch,
        realized_net=request.realized_loot_proceeds-request.entry_and_consumable_cost)


def profit(request: ProfitRequest, store: DecisionStore, owner: str) -> ProfitAnalysis:
    runs=[store.get_artifact(owner,'encounter_observation',identifier,RunObservation).request for identifier in request.run_ids]
    contexts={(r.league,r.encounter_key,r.scenario_digest,r.reference_currency) for r in runs}
    if len(contexts)!=1: raise WorkflowError('profit_run_context_mismatch')
    first=runs[0]
    cost=sum(r.entry_and_consumable_cost for r in runs)
    proceeds=sum(r.realized_loot_proceeds for r in runs)
    seconds=sum(r.duration_seconds for r in runs)
    nets=[r.realized_loot_proceeds-r.entry_and_consumable_cost for r in runs]
    return ProfitAnalysis(sample_count=len(runs),league=first.league,encounter_key=first.encounter_key,
        scenario_digest=first.scenario_digest,reference_currency=first.reference_currency,observed_cost=cost,
        observed_realized_proceeds=proceeds,observed_realized_net=proceeds-cost,observed_seconds=seconds,
        deaths=sum(r.deaths for r in runs),realized_net_per_hour=(proceeds-cost)*3600/seconds,
        observed_run_net_min=min(nets),observed_run_net_max=max(nets),
        hypothetical_net_with_unsold_asks_low=proceeds-cost+sum(r.unsold_loot_ask_low for r in runs),
        hypothetical_net_with_unsold_asks_high=proceeds-cost+sum(r.unsold_loot_ask_high for r in runs),
        sample_size_warning='few_runs' if len(runs)<20 else 'observed_sample_still_not_population')
