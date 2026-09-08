"""Bounded hypothetical combat schedules; never PoB text or measured telemetry.

A caller provides the event schedule. The engine supplies item, passive and
compatible skill parameters. No result changes the PoB snapshot or estimates
DPS by multiplying independent charge-state probabilities.
"""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .builds import DTO

Time = Annotated[float, Field(ge=0, le=120, allow_inf_nan=False)]
Amount = Annotated[float, Field(ge=0, le=1e15, allow_inf_nan=False)]
ChargeType = Literal["power", "frenzy", "endurance"]
SkillGroup = Annotated[int, Field(ge=1, le=10000)]


class InitialCharge(DTO):
    count: Annotated[int, Field(ge=0, le=20)] = 0
    # Remaining lifetime of this type at time zero, not an assumed fresh gain.
    remaining_seconds: Time = 0

    @model_validator(mode="after")
    def lifetime(self):
        if self.count > 0 and self.remaining_seconds <= 0:
            raise ValueError("initial_charge_lifetime_required")
        return self


class InitialCharges(DTO):
    power: InitialCharge = Field(default_factory=InitialCharge)
    frenzy: InitialCharge = Field(default_factory=InitialCharge)
    endurance: InitialCharge = Field(default_factory=InitialCharge)


class InitialMountainTeachings(DTO):
    count: Annotated[int, Field(ge=0, le=30)] = 0
    remaining_seconds: Annotated[float, Field(ge=0, le=20, allow_inf_nan=False)] = 0

    @model_validator(mode="after")
    def lifetime(self):
        if self.count > 0 and self.remaining_seconds <= 0:
            raise ValueError("initial_teaching_lifetime_required")
        return self


class EnemyImmobilised(DTO):
    kind: Literal["enemy_immobilised"]
    at_seconds: Time
    # Effective monster Power, including rarity and applicable Power changes.
    enemy_power: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]


class MountainAttackUse(DTO):
    """One qualifying attack use or sustain event, not one event per hit."""
    kind: Literal["mountain_attack_use"]
    at_seconds: Time
    skill_group: SkillGroup


class MountainHit(DTO):
    kind: Literal["mountain_hit"]
    at_seconds: Time
    # Total enemy hit after Armour/Resistances but before damage-taken mods.
    damage_after_mitigation: Annotated[float, Field(ge=0, le=1e7, allow_inf_nan=False)]
    other_damage_taken_multiplier: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    deflected: bool = False


class ExternalChargeGain(DTO):
    kind: Literal["external_charge_gain"]
    at_seconds: Time
    charge_type: ChargeType
    # A supplied qualifying gain before the character's additional-charge rolls.
    amount: Annotated[int, Field(ge=1, le=20)]


class KillingPalmKill(DTO):
    kind: Literal["killing_palm_kill"]
    at_seconds: Time
    skill_group: SkillGroup
    rarity: Literal["normal_magic", "rare", "unique"]


class ArmourFullyBroken(DTO):
    kind: Literal["armour_fully_broken"]
    at_seconds: Time
    skill_group: SkillGroup


class FlickerUse(DTO):
    kind: Literal["flicker_use"]
    at_seconds: Time
    skill_group: SkillGroup
    # Explicit occupied time. No inference from static PoB attack speed, which
    # can depend on the very charge states being simulated.
    duration_seconds: Annotated[float, Field(gt=0, le=30, allow_inf_nan=False)]


class AllyHit(DTO):
    kind: Literal["ally_hit"]
    at_seconds: Time
    allies_in_presence: bool


class IncomingHit(DTO):
    kind: Literal["incoming_hit"]
    at_seconds: Time
    # Actual damage after mitigation. No second application of DeflectEffect.
    damage_taken: Annotated[float, Field(ge=0, le=1e7, allow_inf_nan=False)]
    deflected: bool


class CompanionRedirectedHit(DTO):
    kind: Literal["companion_redirected_hit"]
    at_seconds: Time
    skill_group: SkillGroup
    # Actual damage redirected to this eligible companion, not owner hit size.
    damage_taken: Annotated[float, Field(ge=0, le=1e7, allow_inf_nan=False)]


CombatEvent = Annotated[
    ExternalChargeGain | KillingPalmKill | ArmourFullyBroken | FlickerUse | AllyHit | IncomingHit | CompanionRedirectedHit | EnemyImmobilised | MountainAttackUse | MountainHit,
    Field(discriminator="kind"),
]


class CombatScenario(DTO):
    horizon_seconds: Annotated[float, Field(gt=0, le=120, allow_inf_nan=False)]
    initial_charges: InitialCharges = Field(default_factory=InitialCharges)
    initial_mountain_teachings: InitialMountainTeachings = Field(default_factory=InitialMountainTeachings)
    # Random-charge wording does not disclose the server's RNG implementation.
    # The named model makes the simulator's stochastic assumptions explicit.
    gain_roll_model: Literal["independent_nonrecursive_per_event", "independent_nonrecursive_per_base_charge"]
    # Required when Charge Regulation is enabled, since its existing tick phase
    # cannot be recovered from an exported build. It may lie beyond the horizon.
    regulation_first_tick_seconds: Time | None = None
    events: Annotated[list[CombatEvent], Field(max_length=64)] = Field(default_factory=list)

    @model_validator(mode="after")
    def schedule(self):
        previous = -1.0
        occupied_until = -1.0
        for event in self.events:
            if event.at_seconds < previous or event.at_seconds > self.horizon_seconds:
                raise ValueError("invalid_combat_event_schedule")
            previous = event.at_seconds
            if event.kind in ("flicker_use", "killing_palm_kill", "mountain_attack_use") and event.at_seconds < occupied_until:
                raise ValueError("overlapping_player_skill_events")
            if event.kind == "flicker_use":
                occupied_until = event.at_seconds + event.duration_seconds
                if occupied_until > self.horizon_seconds:
                    raise ValueError("flicker_window_exceeds_horizon")
        return self


class ChargeProjection(DTO):
    charge_type: ChargeType
    maximum: Annotated[int, Field(ge=0, le=20)]
    expected_final: Amount
    probability_nonzero_at_end: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    expected_seconds_nonzero: Amount
    expected_generated: Amount
    expected_wasted_at_cap: Amount
    expected_blocked: Amount
    expected_removed: Amount
    expected_expired: Amount


class FlickerProjection(DTO):
    uses: Annotated[int, Field(ge=0, le=64)]
    expected_charges_counted: Amount
    expected_strikes: Amount
    assumed_occupied_seconds: Time


class AllyGrantProjection(DTO):
    charge_type: ChargeType
    expected_grants_per_eligible_ally: Amount


class RecoupProjection(DTO):
    # Potential recovery excludes overheal, death, dynamic recovery modifiers,
    # and resource caps; it is not an observed recovered-Life total.
    potential_total: Amount
    potential_by_horizon: Amount
    potential_per_second_at_horizon: Amount
    duration_seconds: Annotated[float, Field(gt=0, le=1e6, allow_inf_nan=False)]


CombatScenarioIssue = Literal[
    "invalid_scenario_skill", "missing_regulation_phase", "unsupported_charge_configuration",
    "invalid_initial_charge_state", "scenario_budget_exceeded", "invalid_combat_event_schedule",
    "unsupported_recoup_configuration", "unsupported_scenario_mechanic",
]


class MountainTeachingsProjection(DTO):
    expected_final: Amount
    probability_active_at_end: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    expected_seconds_active: Amount
    expected_generated: Amount
    expected_wasted_at_cap: Amount
    expected_removed: Amount
    expected_expired: Amount
    expected_damage_taken: Amount
    expected_damage_prevented: Amount
    expected_attacks_benefiting: Amount


class CombatScenarioResult(DTO):
    scenario_scope: Literal["hypothetical_supplied_event_schedule"] = "hypothetical_supplied_event_schedule"
    status: Literal["calculated", "unsupported"]
    horizon_seconds: Time
    gain_roll_model: Literal["independent_nonrecursive_per_event", "independent_nonrecursive_per_base_charge"]
    assumptions: Annotated[list[Literal[
        "independent_nonrecursive_bonus_rolls", "uniform_random_charge_type",
        "retention_roll_per_skill_use", "expiry_before_same_time_events",
        "regulation_before_same_time_events", "gain_refreshes_duration_at_cap",
        "static_build_modifiers", "supplied_flicker_occupation_windows",
        "ally_results_are_grant_attempts", "uncapped_potential_recoup",
    ]], Field(max_length=10)]
    snapshot_dps_unchanged: Literal[True] = True
    charges: Annotated[list[ChargeProjection], Field(max_length=3)] = Field(default_factory=list)
    flicker: FlickerProjection | None = None
    ally_grants: Annotated[list[AllyGrantProjection], Field(max_length=3)] = Field(default_factory=list)
    deflected_recoup: RecoupProjection | None = None
    companion_recoup: RecoupProjection | None = None
    mountain_teachings: MountainTeachingsProjection | None = None
    issues: Annotated[list[CombatScenarioIssue], Field(max_length=8)] = Field(default_factory=list)
