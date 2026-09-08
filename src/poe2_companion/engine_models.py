"""Closed numeric protocol shared by MCP and the isolated PoB worker.

No model-facing code/XML/path/text input or output fields exist here.
"""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .builds import DTO, StatName, PlayerStat
from .equipment import Price, LeagueName, unique
from . import __version__

ENGINE_COMMIT = "fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15"
ENGINE_DATA_COMMIT = "b3282b7a9111ed6c4ec6be643edf0806d7beb675"
ENGINE_COMPATIBILITY = "forbidden-rites-0.5.5-v2"
# Public output metadata has a stable schema across engine/data updates.
# Exact pin equality remains enforced by worker health and EngineClient.status.
EngineCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$", min_length=40, max_length=40)]
EngineCompatibility = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$", min_length=1, max_length=64)]
BuildID = Annotated[str, Field(pattern=r"^bld_[0-9a-f]{32}$", max_length=36)]
SearchID = Annotated[str, Field(pattern=r"^ts_[0-9a-f]{32}$", max_length=35)]
EngineSlot = Literal["helmet", "body_armour", "gloves", "boots", "belt", "amulet", "ring_left", "ring_right", "weapon_main", "weapon_off"]
Number = Annotated[float, Field(ge=-1e15, le=1e15, allow_inf_nan=False)]
IssueCode = Literal["level_requirement", "attribute_requirement", "class_requirement", "slot_incompatible", "item_not_equipped",
    "gem_level_requirement", "unparsed_modifier", "unknown_item_base", "unknown_gem", "engine_item_warning", "reservation_invalid",
    "equip_sequence_unverified", "custom_modifiers_present", "ignored_limits", "unsupported_tree_version", "unsupported_slot", "configuration_override",
    "skill_unusable", "scenario_calculation_failed", "duplicate_physical_item", "unparsed_passive", "unknown_passive", "unknown_rune", "unsupported_skill_stat",
    "unsupported_item_transformation", "stonefist_passive_missing", "charge_sustain_unverified", "ally_charge_state_unverified", "conditional_recoup_unverified",
    "companion_limit_exceeded", "duplicate_companion_type", "unique_companion_limit_exceeded", "unique_companion_not_allowed",
    "companion_identity_unverified", "unsupported_companion_mechanic", "missing_companion_data", "missing_combat_assumption", "unsupported_weapon_context", "granted_skill_source_unresolved"]
CanonicalSkillID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_]+$", min_length=1, max_length=120)]


class EngineRequest(DTO):
    build_id: BuildID


class Replacement(DTO):
    slot: EngineSlot
    # ID of an item already present in the private saved build; zero means remove.
    saved_item_id: Annotated[int, Field(ge=0, le=1000000)]


class CompareRequest(EngineRequest):
    replacements: Annotated[list[Replacement], Field(min_length=1, max_length=3)]

    @model_validator(mode="after")
    def distinct(self):
        unique(self.replacements, "slot")
        ids = [v.saved_item_id for v in self.replacements if v.saved_item_id]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_physical_item")
        return self


class RequirementIssue(DTO):
    code: IssueCode
    slot: EngineSlot | None = None
    stat: Literal["Level", "Str", "Dex", "Int"] | None = None
    required: Number | None = None
    available: Number | None = None
    passive_node_id: Annotated[int, Field(ge=0, le=2147483647)] | None = None
    skill_id: CanonicalSkillID | None = None
    skill_stat_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_%+.-]+$", min_length=1, max_length=180)] | None = None


class MechanicMetric(DTO):
    name: Literal[
        "glove_attribute_exemption", "already_transformed",
        "power_extra_charge_chance", "frenzy_extra_charge_chance", "endurance_extra_charge_chance",
        "power_grant_chance_per_hit", "frenzy_grant_chance_per_hit", "endurance_grant_chance_per_hit",
        "charge_retention_chance", "expected_removed_fraction",
        "power_charges_configured", "frenzy_charges_configured", "endurance_charges_configured",
        "power_charges_counted_for_consumption", "frenzy_charges_counted_for_consumption", "endurance_charges_counted_for_consumption",
        "life_recoup_percent_per_deflected_hit", "recoup_duration_seconds", "deflect_chance", "energy_shield_recharge_delay",
        "regulation_interval_seconds", "regulation_removals_per_charge_type_per_second",
        "same_type_extra_charge_chance", "random_type_extra_charge_chance",
        "bone_offering_life_minimum", "bone_offering_life_maximum",
        "pain_offering_life_minimum", "pain_offering_life_maximum",
        "soul_offering_life_minimum", "soul_offering_life_maximum",
        "active_companion_types", "companion_limit", "exempt_companion_types", "unique_tamed_beasts",
        "unlimited_companion_types", "unique_tamed_beast_movement_speed_increase", "gold_quantity_increase", "unverified_tamed_beasts",
        "spirit_vessel_life_minimum", "spirit_vessel_life_maximum", "spirit_vessel_socketed_skills_minimum", "spirit_vessel_socketed_skills_maximum",
        "spirit_vessel_damage_more_minimum", "spirit_vessel_damage_more_maximum", "wolf_pack_size", "hyena_pack_size"]
    value: Number


class MechanicResult(DTO):
    mechanic: Literal["stonefist", "charge_gain", "charge_consumption", "charge_regulation", "charge_skill_gain",
        "ally_charges", "deflected_recoup", "offering_life", "companion_composition", "natural_order", "economy_effects", "tamed_beast_modifiers", "spirit_vessel", "companion_pack_size"]
    status: Literal["calculated", "partial", "unsupported", "requires_configuration", "inactive"]
    skill_id: CanonicalSkillID | None = None
    metrics: Annotated[list[MechanicMetric], Field(max_length=8)] = Field(default_factory=list)
    required_inputs: Annotated[list[Literal["transformed_glove_data", "stonefist_passive", "charge_gain_events",
        "charge_consumption_events", "ally_presence", "ally_charge_events", "incoming_hit_sequence", "azmeri_spirit", "captured_beast_modifiers"]], Field(max_length=8)] = Field(default_factory=list)


class EquippedItem(DTO):
    slot: EngineSlot
    saved_item_id: Annotated[int, Field(ge=1, le=1000000)] | None = None
    origin: Literal["saved_build", "trade_candidate"] = "saved_build"
    level_required: Annotated[int, Field(ge=0, le=100)]


class SelectedSkill(DTO):
    # Names come exclusively from the pinned engine data, never saved labels.
    skill_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_]+$", max_length=120)]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    gem_name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    name_ko: Annotated[str, Field(max_length=160)] | None = None
    name_source_ko: Annotated[str, Field(max_length=1024)] | None = None
    actor: Literal["player", "minion"]


class EngineSnapshot(DTO):
    stats: Annotated[list[PlayerStat], Field(max_length=26)]
    equipped: Annotated[list[EquippedItem], Field(max_length=10)]
    issues: Annotated[list[RequirementIssue], Field(max_length=16)]
    issue_count: Annotated[int, Field(ge=0, le=1000000)]
    issues_truncated: bool = False
    validation: Literal["pass", "fail", "indeterminate"]
    equip_order: Annotated[list[EngineSlot], Field(max_length=3)] = Field(default_factory=list)
    active_weapon_set: Literal[1, 2]
    main_skill_group: Annotated[int, Field(ge=0, le=10000)]
    selected_skill: SelectedSkill | None = None
    full_dps_enabled: bool = False
    mechanics: Annotated[list[MechanicResult], Field(max_length=16)] = Field(default_factory=list)
    mechanic_count: Annotated[int, Field(ge=0, le=1000000)] = 0
    mechanics_truncated: bool = False


class EngineCalculation(DTO):
    build_id: BuildID
    engine_commit: EngineCommit = Field(default_factory=lambda: ENGINE_COMMIT, validate_default=True)
    engine_data_commit: EngineCommit = Field(default_factory=lambda: ENGINE_DATA_COMMIT, validate_default=True)
    engine_compatibility: EngineCompatibility = Field(default_factory=lambda: ENGINE_COMPATIBILITY, validate_default=True)
    calculated_at_epoch: int
    baseline: EngineSnapshot
    result: EngineSnapshot | None = None
    deltas: Annotated[list[PlayerStat], Field(max_length=26)] = Field(default_factory=list)
    character_recalculated: Literal[True] = True
    scope: Literal["saved_configuration_active_weapon_set"] = "saved_configuration_active_weapon_set"
    live_character: Literal[False] = False
    baseline_source: Literal["privately_imported_pob"] = "privately_imported_pob"
    character_league_verified: Literal[False] = False


class EngineStatus(DTO):
    server_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$", max_length=32)] = Field(default_factory=lambda: __version__, validate_default=True)
    enabled: bool
    reachable: bool
    engine_commit: EngineCommit = Field(default_factory=lambda: ENGINE_COMMIT, validate_default=True)
    engine_data_commit: EngineCommit = Field(default_factory=lambda: ENGINE_DATA_COMMIT, validate_default=True)
    engine_compatibility: EngineCompatibility = Field(default_factory=lambda: ENGINE_COMPATIBILITY, validate_default=True)
    transport: Literal["private_unix_socket"] = "private_unix_socket"
    raw_payload_tools: Literal[False] = False


class CharacterWeight(DTO):
    stat: StatName
    weight: Annotated[float, Field(gt=0, le=1e6, allow_inf_nan=False)]
    cap: Number | None = None


class CharacterConstraint(DTO):
    stat: StatName
    minimum: Number


class EngineTradeRequest(EngineRequest):
    league: LeagueName = "Forbidden Rites"
    search_ids: Annotated[list[SearchID], Field(min_length=1, max_length=4)]
    budget: Price
    mode: Literal["maximize_score", "minimize_cost"] = "maximize_score"
    weights: Annotated[list[CharacterWeight], Field(max_length=8)] = Field(default_factory=list)
    constraints: Annotated[list[CharacterConstraint], Field(max_length=8)] = Field(default_factory=list)
    max_changes: Annotated[int, Field(ge=1, le=3)] = 1
    reserve_percent: Annotated[float, Field(ge=0, le=99, allow_inf_nan=False)] = 0
    max_listing_age_seconds: Annotated[int, Field(ge=1, le=600)] = 300
    # Explicit selection prevents silently pruning a combinatorial search.
    candidate_refs: Annotated[list[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]], Field(max_length=32)] | None = None

    @model_validator(mode="after")
    def distinct(self):
        if len(self.search_ids) != len(set(self.search_ids)):
            raise ValueError("duplicate_search")
        unique(self.weights, "stat")
        unique(self.constraints, "stat")
        if self.mode == "maximize_score" and not self.weights or self.mode == "minimize_cost" and not self.constraints:
            raise ValueError("explicit_objective_required")
        return self


class TradeChange(DTO):
    slot: EngineSlot
    listing_ref: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EngineTradeResult(DTO):
    calculation: EngineCalculation
    changes: Annotated[list[TradeChange], Field(max_length=3)]
    cost: Number
    currency: Literal["exalted", "chaos", "divine"]
    remaining_budget: Number
    score_gain: Number
    feasible: bool
    evaluated_combinations: int
    failed_requirements: int
    indeterminate_combinations: int
    excluded_listings: int
    exact_within_evaluated_candidates: Literal[True] = True
    live_availability_verified: Literal[False] = False
    fx_retrieved_at_epoch: int | None = None


class EngineError(Exception):
    pass


SAFE_ENGINE_ERRORS = {"engine_unavailable", "engine_timeout", "engine_busy", "engine_invalid_request", "engine_invalid_build",
    "engine_calculation_failed", "engine_protocol_error", "engine_candidate_space_too_large", "engine_missing_metric",
    "engine_no_candidates", "engine_unknown_candidate", "engine_currency_unavailable", "engine_version_mismatch"}
