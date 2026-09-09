"""Bounded calculation assumptions, never raw build edits or observed game state."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .builds import DTO

SkillID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_]+$", min_length=1, max_length=120)]
BeastModID = Annotated[str, Field(pattern=r"^PlayerMonster[A-Za-z0-9_]+$", max_length=160)]


class CapturedBeastModifiers(DTO):
    skill_group: Annotated[int, Field(ge=1, le=10000)]
    mod_ids: Annotated[list[BeastModID], Field(max_length=4)]
    complete: bool

    @model_validator(mode="after")
    def distinct(self):
        if len(self.mod_ids) != len(set(self.mod_ids)):
            raise ValueError("duplicate_captured_modifier")
        return self


class AuraRecipient(DTO):
    skill_group: Annotated[int, Field(ge=1, le=10000)]
    within_radius: bool


class CompanionAuraSource(DTO):
    skill_group: Annotated[int, Field(ge=1, le=10000)]
    source_alive: bool
    player_within_radius: bool
    minion_recipients: Annotated[list[AuraRecipient], Field(max_length=32)]

    @model_validator(mode="after")
    def distinct(self):
        groups=[row.skill_group for row in self.minion_recipients]
        if len(groups)!=len(set(groups)):
            raise ValueError("duplicate_aura_recipient")
        return self


class CalculationConfiguration(DTO):
    # Null retains the saved configuration. Explicit false/zero are meaningful.
    ghost_shroud_lost_recently: bool | None = None
    natural_order_spirit: Literal["unknown", "none", "owl", "serpent", "primate", "bear", "boar", "ox", "wolf", "stag", "cat"] | None = None
    captured_beast_mods: Annotated[list[CapturedBeastModifiers], Field(max_length=8)] | None = None
    spirit_vessel_skill_id: SkillID | None = None
    hollow_form_attack_skill_id: SkillID | None = None
    hollow_form_channel_uses_per_second: Annotated[float, Field(ge=0, le=30, allow_inf_nan=False)] | None = None
    hollow_form_power_charge_use_fraction: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    impale_magnitude: Annotated[float, Field(ge=0, le=1e9, allow_inf_nan=False)] | None = None
    leech_resistance_percent: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None = None
    leech_recovery_uptime: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    onslaught_active: bool | None = None
    thrill_of_the_kill_active: bool | None = None
    culling_strike_recent_cull: bool | None = None
    wind_dancer_stages: Annotated[int, Field(ge=0, le=3)] | None = None
    mountain_teachings: Annotated[int, Field(ge=0, le=30)] | None = None
    refutation_active: bool | None = None
    refutation_ward_spent: Annotated[float, Field(ge=0, le=1e6, allow_inf_nan=False)] | None = None

    tempest_bell_prior_hits: Annotated[int, Field(ge=0, le=100)] | None = None
    tempest_bell_ailment_types: Annotated[list[Literal["fire", "cold", "lightning"]], Field(max_length=3)] | None = None
    tempest_bell_knockback_metres: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None = None
    enemy_maimed: bool | None = None
    enemy_blinded: bool | None = None
    charged_mark_ground_active: bool | None = None
    rite_of_passage_spirit: Literal["none", "bear", "boar", "cat", "owl", "ox", "primate", "serpent", "stag", "wolf"] | None = None
    companion_aura_sources: Annotated[list[CompanionAuraSource], Field(max_length=8)] | None = None

    @model_validator(mode="after")
    def coherent(self):
        values = (self.hollow_form_attack_skill_id, self.hollow_form_channel_uses_per_second,
                  self.hollow_form_power_charge_use_fraction)
        if any(value is not None for value in values) and any(value is None for value in values):
            raise ValueError("complete_hollow_form_scenario_required")
        if self.captured_beast_mods is not None:
            groups = [row.skill_group for row in self.captured_beast_mods]
            if len(groups) != len(set(groups)):
                raise ValueError("duplicate_captured_beast_group")
        if (self.refutation_active is None) != (self.refutation_ward_spent is None):
            raise ValueError("complete_refutation_configuration_required")
        if self.tempest_bell_ailment_types is not None and len(self.tempest_bell_ailment_types) != len(set(self.tempest_bell_ailment_types)):
            raise ValueError("duplicate_tempest_bell_ailment_type")
        if self.companion_aura_sources is not None:
            groups=[row.skill_group for row in self.companion_aura_sources]
            if len(groups)!=len(set(groups)):
                raise ValueError("duplicate_aura_source")
        return self


ConfigurationField = Literal[
    "leech_recovery_uptime",
    "ghost_shroud_lost_recently", "natural_order_spirit", "captured_beast_mods",
    "spirit_vessel_skill_id", "hollow_form_attack_skill_id", "hollow_form_channel_uses_per_second",
    "hollow_form_power_charge_use_fraction", "impale_magnitude", "leech_resistance_percent",
    "onslaught_active", "thrill_of_the_kill_active", "culling_strike_recent_cull",
    "wind_dancer_stages", "mountain_teachings", "refutation_active", "refutation_ward_spent",
    "tempest_bell_prior_hits", "tempest_bell_ailment_types", "tempest_bell_knockback_metres",
    "enemy_maimed", "enemy_blinded", "charged_mark_ground_active", "rite_of_passage_spirit",
    "companion_aura_sources",
]
