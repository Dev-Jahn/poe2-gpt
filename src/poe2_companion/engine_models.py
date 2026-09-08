"""Closed numeric protocol shared by MCP and the isolated PoB worker.

No model-facing code/XML/path/text input or output fields exist here.
"""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .builds import DTO, StatName, PlayerStat
from .equipment import Price, LeagueName, unique

ENGINE_COMMIT = "fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15"
ENGINE_DATA_COMMIT = "b3282b7a9111ed6c4ec6be643edf0806d7beb675"
ENGINE_COMPATIBILITY = "forbidden-rites-0.5.5-v1"
BuildID = Annotated[str, Field(pattern=r"^bld_[0-9a-f]{32}$", max_length=36)]
SearchID = Annotated[str, Field(pattern=r"^ts_[0-9a-f]{32}$", max_length=35)]
EngineSlot = Literal["helmet", "body_armour", "gloves", "boots", "belt", "amulet", "ring_left", "ring_right", "weapon_main", "weapon_off"]
Number = Annotated[float, Field(ge=-1e15, le=1e15, allow_inf_nan=False)]
IssueCode = Literal["level_requirement", "attribute_requirement", "class_requirement", "slot_incompatible", "item_not_equipped",
    "gem_level_requirement", "unparsed_modifier", "unknown_item_base", "unknown_gem", "engine_item_warning", "reservation_invalid",
    "equip_sequence_unverified", "custom_modifiers_present", "ignored_limits", "unsupported_tree_version", "unsupported_slot", "configuration_override",
    "skill_unusable", "scenario_calculation_failed", "duplicate_physical_item", "unparsed_passive", "unknown_passive", "unknown_rune", "unsupported_skill_stat"]


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


class EngineCalculation(DTO):
    build_id: BuildID
    engine_commit: Literal[ENGINE_COMMIT] = ENGINE_COMMIT
    engine_data_commit: Literal[ENGINE_DATA_COMMIT] = ENGINE_DATA_COMMIT
    engine_compatibility: Literal[ENGINE_COMPATIBILITY] = ENGINE_COMPATIBILITY
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
    enabled: bool
    reachable: bool
    engine_commit: Literal[ENGINE_COMMIT] = ENGINE_COMMIT
    engine_data_commit: Literal[ENGINE_DATA_COMMIT] = ENGINE_DATA_COMMIT
    engine_compatibility: Literal[ENGINE_COMPATIBILITY] = ENGINE_COMPATIBILITY
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
