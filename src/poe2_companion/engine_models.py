"""Closed numeric protocol shared by MCP and the isolated PoB worker.

No model-facing code/XML/path/text input or output fields exist here.
"""
from typing import Annotated, Literal
from pydantic import Field, model_serializer, model_validator
from .requirements import RequirementBreakdown
from .builds import DTO, StatName, PlayerStat, BuildOrigin
from .equipment import Price, LeagueName, unique
from . import __version__
from .calculation_config import CalculationConfiguration, ConfigurationField
from .combat_models import CombatScenario, CombatScenarioResult
from .subjects import CalculationTarget, SubjectBinding

ENGINE_COMMIT = "fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15"
ENGINE_DATA_COMMIT = "b3282b7a9111ed6c4ec6be643edf0806d7beb675"
ENGINE_COMPATIBILITY = "forbidden-rites-0.5.5-v4"
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
    "companion_identity_unverified", "unsupported_companion_mechanic", "missing_companion_data", "missing_combat_assumption", "unsupported_weapon_context", "granted_skill_source_unresolved", "target_unavailable"]
CanonicalSkillID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_]+$", min_length=1, max_length=120)]


class EngineRequest(DTO):
    build_id: BuildID
    target: CalculationTarget | None = None
    configuration: CalculationConfiguration | None = None
    combat_scenario: CombatScenario | None = None


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
        "leech_recovery_uptime", "life_leech_uptime_scaled_active_rate", "mana_leech_uptime_scaled_active_rate", "energy_shield_leech_uptime_scaled_active_rate",
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
        "spirit_vessel_damage_more_minimum", "spirit_vessel_damage_more_maximum", "wolf_pack_size", "hyena_pack_size",
        "ghost_shroud_interval_seconds", "ghost_shroud_maximum", "ghost_shroud_evasion_percent_per_second",
        "ghost_shroud_base_es_regeneration_per_second", "energy_shield_regeneration_per_second", "recently_window_seconds",
        "ghost_shroud_recent_loss_configured", "bell_spawn_interval_seconds", "bell_spawn_rate_per_second",
        "bell_active_limit", "bell_hits_to_destroy", "bell_duration_seconds",
        "bell_shockwave_average_damage", "hollow_form_images_without_charge", "hollow_form_expected_images_with_charge",
        "hollow_form_cost_multiplier_per_image", "hollow_form_charge_retention_chance", "hollow_form_expected_charges_removed_per_charged_use",
        "hollow_form_socketed_attack_count", "hollow_form_unrounded_mana_cost_per_image", "hollow_form_average_damage_per_image",
        "hollow_form_channel_uses_per_second", "hollow_form_power_charge_use_fraction", "hollow_form_images_per_second",
        "hollow_form_expected_charges_removed_per_second", "hollow_form_unrounded_mana_per_second", "hollow_form_image_hit_dps",
        "tempest_bell_combo_required", "tempest_bell_combo_decay_seconds", "tempest_bell_shockwave_interval_seconds",
        "tempest_bell_shockwave_rate_limit_per_second", "wind_dancer_stage_interval_seconds", "wind_dancer_stage_gain_rate_per_second",
        "wind_dancer_maximum_stages", "wind_dancer_full_refill_seconds", "wind_dancer_configured_stages",
        "wind_dancer_evasion_more_percent", "refutation_stun_threshold", "refutation_stun_threshold_multiplier",
        "refutation_blockable_hit_block_chance", "refutation_light_stun_immunity", "refutation_buff_duration_seconds",
        "refutation_cycle_seconds", "refutation_maximum_uptime_percent", "refutation_ward_spent",
        "configured_tamed_beasts", "captured_beast_modifiers_applied", "captured_beast_modifiers_unimplemented",
        "natural_order_spirit_configured", "companion_armour_break_per_hit", "copied_skill_average_hit",
        "copied_skill_nominal_dps", "copied_skill_uses_per_second", "copied_skill_critical_chance",
        "copied_skill_hit_chance", "spirit_vessel_life", "spirit_vessel_armour",
        "spirit_vessel_evasion", "spirit_vessel_energy_shield", "spirit_vessel_fire_resist",
        "spirit_vessel_cold_resist", "spirit_vessel_lightning_resist", "spirit_vessel_chaos_resist",
        "impale_chance_percent", "impale_crit_chance_percent", "impale_hit_magnitude",
        "impale_crit_magnitude", "impales_inflicted_per_hit", "impales_stored_cap",
        "impale_extracted_hit_magnitude", "impale_extracted_crit_magnitude", "life_leech_per_hit",
        "mana_leech_per_hit", "energy_shield_leech_per_hit", "life_leech_active_rate",
        "mana_leech_active_rate", "energy_shield_leech_active_rate", "leech_resistance_percent",
        "leech_total_hit_damage_cap", "life_leech_per_use", "mana_leech_per_use",
        "energy_shield_leech_per_use", "mountain_maximum_stacks", "mountain_expiry_seconds",
        "mountain_attack_damage_more_percent", "mountain_stun_threshold_more_percent", "mountain_small_hit_damage_less_percent",
        "mountain_small_hit_threshold_life_percent", "mountain_configured_stacks", "tempest_bell_prior_hits_applied",
        "tempest_bell_damage_more_percent", "tempest_bell_fire_gain_percent", "tempest_bell_cold_gain_percent",
        "tempest_bell_lightning_gain_percent", "tempest_bell_knockback_area_more_percent", "tempest_bell_shockwave_area_radius",
        "maim_chance_percent", "blind_chance_percent", "cannot_inflict_blind",
        "enemy_maimed", "enemy_blinded", "maim_base_duration_seconds",
        "thrill_added_lightning_attack_percent", "thrill_shock_chance_increased_percent", "thrill_base_duration_seconds",
        "thrill_buff_active", "culling_threshold_increased_percent", "culling_buff_base_duration_seconds",
        "culling_buff_active", "culling_threshold_percent", "behead_modifiers_per_rare_kill",
        "behead_base_duration_seconds", "onslaught_active", "onslaught_source_count",
        "onslaught_highest_source_chance_percent", "onslaught_longest_source_base_duration_seconds", "curse_maximum_target_level",
        "curse_target_level", "curse_target_level_allowed", "curse_applied",
        "curse_applies_as_aura", "mark_targets_per_type", "charged_mark_trigger_chance_percent",
        "charged_mark_ground_duration_seconds", "charged_mark_ground_radius_metres", "charged_mark_ground_active",
        "charged_mark_triggered_skill_level", "rite_of_passage_possession_active", "rite_of_passage_base_possession_duration_seconds",
        "companion_aura_sources", "companion_aura_sources_configured", "companion_aura_sources_alive",
        "companion_aura_radius_metres", "player_beast_aura_physical_damage_increase",
        "player_beast_aura_attack_speed_increase", "minion_beast_aura_physical_damage_increase",
        "minion_beast_aura_attack_speed_increase", "companion_chill_minimum_percent",
        "companion_chill_hit_candidate_percent", "companion_chill_crit_candidate_percent"]
    value: Number


class MechanicResult(DTO):
    mechanic: Literal["stonefist", "charge_gain", "charge_consumption", "charge_regulation", "charge_skill_gain",
        "ally_charges", "deflected_recoup", "offering_life", "companion_composition", "natural_order", "economy_effects", "tamed_beast_modifiers", "spirit_vessel", "companion_pack_size",
        "ghost_dance", "hollow_focus", "hollow_form", "hollow_form_simulation", "tempest_bell", "wind_dancer", "refutation", "companion_hit_effects", "spirit_vessel_copied_attack", "spirit_vessel_defences", "impale_generation", "impale_extraction", "leech_recovery", "mountain_teachings", "tempest_bell_shockwave",
        "hit_effects", "thrill_of_the_kill", "culling_strike_buff", "behead", "onslaught",
        "curse_application", "charged_mark", "rite_of_passage", "companion_ally_auras", "companion_chill", "leech_uptime_scenario"]
    status: Literal["calculated", "partial", "unsupported", "requires_configuration", "inactive"]
    numerical_method: Literal["per_hit_distribution_integration"] | None = None
    numerical_accuracy: Literal["exact_for_supplied_hit_model", "quadrature_or_upstream_damage_approximation"] | None = None
    skill_id: CanonicalSkillID | None = None
    metrics: Annotated[list[MechanicMetric], Field(max_length=8)] = Field(default_factory=list)
    required_inputs: Annotated[list[Literal["transformed_glove_data", "stonefist_passive", "charge_gain_events",
        "charge_consumption_events", "ally_presence", "ally_charge_events", "incoming_hit_sequence", "azmeri_spirit", "captured_beast_modifiers",
        "ghost_shroud_lost_recently", "bell_hit_events", "hollow_form_channel_events", "hollow_form_socketed_skill", "tempest_bell_combo_events", "wind_dancer_stages", "companion_skill_rotation", "impale_sustain", "impale_magnitude", "leech_recovery_uptime", "leech_resistance_percent", "mountain_teachings", "tempest_bell_ailment_types", "tempest_bell_knockback_metres", "refutation_buff_state",
        "thrill_of_the_kill_active", "culling_strike_recent_cull", "stolen_rare_modifiers", "onslaught_active",
        "charged_mark_ground_active", "rite_of_passage_spirit", "spirit_summon_rotation", "slowing_debuffs", "companion_aura_sources"]], Field(max_length=8)] = Field(default_factory=list)


class EquippedItem(DTO):
    slot: EngineSlot
    saved_item_id: Annotated[int, Field(ge=1, le=1000000)] | None = None
    origin: Literal["saved_build", "trade_candidate"] = "saved_build"
    level_required: Annotated[int, Field(ge=0, le=100)]


class SelectedSkill(DTO):
    # Names come exclusively from the pinned engine data, never saved labels.
    skill_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_]+$", max_length=120)]
    # Display labels may be omitted under the tool byte budget. The canonical
    # skill_id and actor always remain, with the snapshot truncation marker.
    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    gem_name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    name_ko: Annotated[str, Field(max_length=160)] | None = None
    name_source_ko: Annotated[str, Field(max_length=1024)] | None = None
    actor: Literal["player", "minion"]


class MetricCoverage(DTO):
    stat: StatName
    status: Literal['pass', 'indeterminate']
    reason: Literal['all_rules_validated', 'unconditional_resource_dependency_verified', 'unresolved_dependency']


class EngineSnapshot(DTO):
    requirements: RequirementBreakdown | None = None
    requirements_truncated: bool = False
    subject: SubjectBinding | None = None
    origin: BuildOrigin | None = None
    stats: Annotated[list[PlayerStat], Field(max_length=64)]
    stat_count: int | None = None
    stats_truncated: bool = False
    equipped: Annotated[list[EquippedItem], Field(max_length=10)]
    issues: Annotated[list[RequirementIssue], Field(max_length=10000)]
    issue_count: Annotated[int, Field(ge=0, le=1000000)]
    issues_truncated: bool = False
    validation: Literal["pass", "fail", "indeterminate"]
    equipment_validity: Literal['pass', 'fail', 'indeterminate'] | None = None
    metric_coverage: list[MetricCoverage] = Field(default_factory=list)
    metric_coverage_truncated: bool = False
    equip_order: Annotated[list[EngineSlot], Field(max_length=3)] = Field(default_factory=list)
    active_weapon_set: Literal[1, 2]
    main_skill_group: Annotated[int, Field(ge=0, le=10000)]
    selected_skill: SelectedSkill | None = None
    selected_skill_labels_truncated: bool = False
    full_dps_enabled: bool = False
    mechanics: Annotated[list[MechanicResult], Field(max_length=10000)] = Field(default_factory=list)
    mechanic_count: Annotated[int, Field(ge=0, le=1000000)] = 0
    mechanics_truncated: bool = False
    combat_scenario: CombatScenarioResult | None = None
    combat_scenario_status: Literal["calculated", "unsupported"] | None = None
    combat_scenario_truncated: bool = False


class EngineCalculation(DTO):
    build_id: BuildID
    calculation_id: Annotated[str, Field(pattern=r"^calc_[0-9a-f]{32}$")] | None = None
    diagnostics_expires_at_epoch: int | None = None
    engine_commit: EngineCommit = Field(default_factory=lambda: ENGINE_COMMIT, validate_default=True)
    engine_data_commit: EngineCommit = Field(default_factory=lambda: ENGINE_DATA_COMMIT, validate_default=True)
    engine_compatibility: EngineCompatibility = Field(default_factory=lambda: ENGINE_COMPATIBILITY, validate_default=True)
    calculated_at_epoch: int
    baseline: EngineSnapshot
    result: EngineSnapshot | None = None
    deltas: Annotated[list[PlayerStat], Field(max_length=64)] = Field(default_factory=list)
    deltas_truncated: bool = False
    requested_metrics: Annotated[list[StatName], Field(max_length=16)] = Field(default_factory=list)
    character_recalculated: Literal[True] = True
    scope: Literal["saved_configuration_active_weapon_set", "explicit_configuration_active_weapon_set"] = "saved_configuration_active_weapon_set"
    configuration_fields: Annotated[list[ConfigurationField], Field(max_length=32)] = Field(default_factory=list)
    live_character: Literal[False] = False
    baseline_source: Literal["privately_imported_pob"] = "privately_imported_pob"
    character_league_verified: bool = False
    league_match: Literal['verified', 'user_declared', 'unknown'] = 'unknown'

    @model_serializer(mode="wrap", when_used="json")
    def compact_optional_metadata(self, handler):
        """Omit redundant optional JSON metadata without changing values.

        All omitted fields have explicit defaults in the output schema. DTO
        round trips restore them; statistics, statuses, counts, skill IDs and
        item references are never abbreviated, rounded or removed.
        """
        def compact(value):
            if isinstance(value, list):
                return [compact(entry) for entry in value]
            if isinstance(value, dict):
                result = {key: compact(entry) for key, entry in value.items() if entry is not None}
                if ("slot" in result and "level_required" in result
                        and result.get("origin") == "saved_build"):
                    result.pop("origin")
                defaults = {"stats_truncated": False, "metric_coverage_truncated": False,
                    "metric_coverage": [], "requested_metrics": [], "deltas_truncated": False,
                    "league_match": "unknown"}
                for key, default in defaults.items():
                    if key in result and result[key] == default:
                        result.pop(key)
                return result
            # JSON numbers have no separate integer/float type. Removing a
            # redundant .0 is exact; fractional floats retain every digit.
            if isinstance(value, float) and value.is_integer():
                return int(value)
            return value
        return compact(handler(self))


class EngineStatus(DTO):
    server_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$", max_length=32)] = Field(default_factory=lambda: __version__, validate_default=True)
    enabled: bool
    reachable: bool
    engine_commit: EngineCommit = Field(default_factory=lambda: ENGINE_COMMIT, validate_default=True)
    engine_data_commit: EngineCommit = Field(default_factory=lambda: ENGINE_DATA_COMMIT, validate_default=True)
    engine_compatibility: EngineCompatibility = Field(default_factory=lambda: ENGINE_COMPATIBILITY, validate_default=True)
    transport: Literal["private_unix_socket"] = "private_unix_socket"
    raw_payload_tools: Literal[False] = False


class EquipmentValidation(DTO):
    build_id: BuildID
    calculation_id: Annotated[str, Field(pattern=r'^calc_[0-9a-f]{32}$')] | None
    equipment_validity: Literal['pass','fail','indeterminate']
    overall_validation: Literal['pass','fail','indeterminate']
    issue_count: int
    issues: Annotated[list[RequirementIssue], Field(max_length=10)]
    issues_truncated: bool
    covered_metric_count: int
    unresolved_metric_count: int
    active_weapon_set: int
    configuration_fields: list[ConfigurationField]
    detail_tool: Literal['get_build_diagnostics'] = 'get_build_diagnostics'


class CharacterWeight(DTO):
    stat: StatName
    weight: Annotated[float, Field(gt=0, le=1e6, allow_inf_nan=False)]
    cap: Number | None = None


class CharacterConstraint(DTO):
    stat: StatName
    minimum: Number


class EngineTradeRequest(EngineRequest):
    declared_character_league: LeagueName | None = None
    league: LeagueName = "Forbidden Rites"
    search_ids: Annotated[list[SearchID], Field(min_length=1, max_length=4)]
    budget: Price
    mode: Literal["maximize_score", "minimize_cost", "restore_validity"] = "maximize_score"
    weights: Annotated[list[CharacterWeight], Field(max_length=8)] = Field(default_factory=list)
    constraints: Annotated[list[CharacterConstraint], Field(max_length=8)] = Field(default_factory=list)
    max_changes: Annotated[int, Field(ge=1, le=3, description='Maximum changed slots, counting both equip and unequip actions.')] = 1
    unequip_slots: Annotated[list[EngineSlot], Field(max_length=10, description='Slots allowed to become empty. Omit to consider all occupied slots; [] disables removal.')] | None = None
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
        if self.unequip_slots is not None and len(set(self.unequip_slots)) != len(self.unequip_slots):
            raise ValueError('duplicate_unequip_slot')
        if self.mode == "maximize_score" and not self.weights or self.mode == "minimize_cost" and not self.constraints:
            raise ValueError("explicit_objective_required")
        return self


class TradeChange(DTO):
    slot: EngineSlot
    action: Literal['equip', 'unequip'] = 'equip'
    listing_ref: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    normalized_cost: Annotated[float, Field(ge=0, le=1e15, allow_inf_nan=False)] = 0
    original_price: Price | None = None

    @model_validator(mode='after')
    def coherent(self):
        if self.action == 'equip' and self.listing_ref is None:
            raise ValueError('equip_requires_listing')
        if self.action == 'unequip' and (self.listing_ref is not None or self.normalized_cost != 0 or self.original_price is not None):
            raise ValueError('unequip_has_no_listing_or_cost')
        return self


class EngineTradeResult(DTO):
    calculation: EngineCalculation
    changes: Annotated[list[TradeChange], Field(max_length=3)]
    cost: Number
    currency: Literal["exalted", "chaos", "divine"]
    remaining_budget: Number
    score_gain: Number
    feasible: bool
    objective: Literal['maximize_score', 'minimize_cost', 'restore_validity'] = 'maximize_score'
    baseline_comparison_valid: bool = True
    recommendation_scope: Literal['retained_candidates_with_requested_metric_coverage'] = 'retained_candidates_with_requested_metric_coverage'
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
    "character_league_unverified", "character_league_mismatch",
    "calculation_expired_or_unavailable", "calculation_target_unavailable",
    "engine_calculation_failed", "engine_protocol_error", "engine_candidate_space_too_large", "engine_missing_metric",
    "engine_no_candidates", "engine_unknown_candidate", "engine_currency_unavailable", "engine_version_mismatch"}
