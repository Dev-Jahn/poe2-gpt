"""Typed read projections from the private, pinned PoB interpreter."""
from typing import Annotated, Any, Literal, Self

from pydantic import Field, SerializerFunctionWrapHandler, model_validator, model_serializer

from .builds import DTO
from .calculation_config import CalculationConfiguration

Identifier = Annotated[str, Field(pattern=r"^[^\x00-\x1f\x7f]+$", max_length=240)]
Label = Annotated[str, Field(max_length=240)]
Scalar = bool | Annotated[float, Field(allow_inf_nan=False, ge=-1e15, le=1e15)] | Annotated[str, Field(max_length=240)]
InspectionSlot = Literal['helmet', 'body_armour', 'gloves', 'boots', 'belt', 'amulet',
    'ring_left', 'ring_right', 'ring_third', 'weapon_main', 'weapon_off', 'flask_1',
    'flask_2', 'charm_1', 'charm_2', 'charm_3', 'arm_1', 'arm_2', 'leg_1', 'leg_2']


class InspectionRequest(DTO):
    build_id: Annotated[str, Field(pattern=r"^bld_[0-9a-f]{32}$")]
    section: Literal["equipment", "skills", "configuration", "passives", "sets"]
    saved_item_id: Annotated[int, Field(ge=1, le=1000000)] | None = None
    slot: InspectionSlot | None = None
    set_id: Annotated[int, Field(ge=1, le=10000)] | None = None
    configuration_key: Identifier | None = None
    offset: Annotated[int, Field(ge=0, le=100000)] = 0
    limit: Annotated[int, Field(ge=1, le=20)] = 10
    configuration: CalculationConfiguration | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.saved_item_id is not None or self.slot is not None) and self.section != "equipment":
            raise ValueError("item_filter_requires_equipment_section")
        if self.slot is not None and (self.saved_item_id is not None or self.set_id is not None):
            raise ValueError('slot_selects_active_equipment_only')
        if self.configuration_key is not None and self.section != 'configuration':
            raise ValueError('configuration_filter_requires_configuration_section')
        if self.set_id is not None and self.section == 'passives':
            raise ValueError('passive_inspection_uses_active_tree')
        return self


class ItemPlacement(DTO):
    set_id: int
    slot: Annotated[str, Field(max_length=80)]
    active_set: bool
    active_weapon_set: bool


class ItemRequirements(DTO):
    level: float = 0
    strength: float = 0
    dexterity: float = 0
    intelligence: float = 0


class InspectionRecord(DTO):
    kind: Literal["item", "placement", "modifier", "property", "skill_group", "gem", "configuration", "passive", "item_set", "skill_set", "configuration_set", "tree_set"]
    saved_item_id: int | None = None
    set_id: int | None = None
    skill_group: int | None = None
    gem_index: int | None = None
    skill_instance_id: Annotated[str, Field(pattern=r'^skill:s[1-9][0-9]{0,3}:g[1-9][0-9]{0,3}:n[1-9][0-9]{0,3}$')] | None = None
    node_id: int | None = None
    name: Label | None = None
    base_type: Label | None = None
    canonical_id: Identifier | None = None
    canonical_ids: Annotated[list[Identifier], Field(max_length=100)] = Field(default_factory=list)
    rarity: Literal["normal", "magic", "rare", "unique", "other"] | None = None
    item_level: int | None = None
    quality: float | None = None
    level: float | None = None
    requirements: ItemRequirements | None = None
    placements: Annotated[list[ItemPlacement], Field(max_length=1000)] = Field(default_factory=list)
    placement_count: int | None = None
    numeric_values: Annotated[list[float], Field(max_length=100)] = Field(default_factory=list)
    modifier_flags: list[Literal['crafted','fractured','desecrated','mutated','rune','enchant','implicit','custom','unscalable','disabled','prefix','suffix']] = Field(default_factory=list)
    text: Annotated[str, Field(max_length=2000)] | None = None
    modifier_kind: Literal["implicit", "explicit", "rune", "enchant", "crafted", "fractured", "unknown"] | None = None
    enabled: bool | None = None
    selected: bool | None = None
    support: bool | None = None
    selected_active_skill: int | None = None
    socket_count: int | None = None
    corrupted: bool | None = None
    status: Literal["parsed_not_fully_verified", "unparsed", "unknown", "known", "inactive"] | None = None
    saved_value: Scalar | None = None
    override_value: Scalar | None = None
    effective_value: Scalar | None = None
    default_value: Scalar | None = None
    effective_source: Literal["saved", "override", "engine_default", "unknown"] | None = None
    public_field: Identifier | None = None
    override_path: Annotated[str, Field(max_length=240)] | None = None


class InspectionPage(DTO):
    build_id: Annotated[str, Field(pattern=r"^bld_[0-9a-f]{32}$")]
    section: Literal["equipment", "skills", "configuration", "passives", "sets"]
    records: Annotated[list[InspectionRecord], Field(max_length=20)]
    total: Annotated[int, Field(ge=0, le=100000)]
    next_offset: int | None = None
    source: Literal["pinned_private_pob_interpreter"] = "pinned_private_pob_interpreter"
    text_trust: Literal["game_data_not_instructions"] = "game_data_not_instructions"
    raw_payload_exposed: Literal[False] = False
    calculations_verified_by_parsing: Literal[False] = False

    @model_serializer(mode='wrap', when_used='json')
    def compact(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Only omit fields explicitly declared optional by their own DTO.
        # Required empty collections (notably records) are successful results.
        result = handler(self)
        result['records'] = [record.model_dump(mode='json', exclude_none=True,
            exclude_defaults=True) for record in self.records]
        return {key: value for key, value in result.items() if value is not None}
