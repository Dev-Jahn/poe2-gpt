"""The MCP-facing build surface. This module cannot open PoB payload files.

Only bounded, typed projections are readable. No arbitrary text, URLs, XML,
notes, code fields, filesystem paths, or catch-all dictionaries are exposed.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Annotated, Literal, get_args, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

BUILD_ID_RE = re.compile(r"bld_[0-9a-f]{32}\Z")
MAX_PROJECTION_BYTES = 128 * 1024
MAX_TOOL_JSON_BYTES = 8192
BASE_CLASSES = ("Warrior", "Mercenary", "Ranger", "Huntress", "Monk", "Druid",
                "Sorceress", "Witch", "Marauder", "Duelist", "Shadow", "Templar", "Unknown")
ClassName = Literal["Warrior", "Mercenary", "Ranger", "Huntress", "Monk", "Druid",
                    "Sorceress", "Witch", "Marauder", "Duelist", "Shadow", "Templar", "Unknown"]
StatName = Literal["Life", "LifeUnreserved", "Mana", "ManaUnreserved", "EnergyShield", "Armour", "Evasion",
                   "FireResistTotal", "ColdResistTotal", "LightningResistTotal", "ChaosResistTotal",
                   "FireResistOverCap", "ColdResistOverCap", "LightningResistOverCap", "ChaosResistOverCap",
                   "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken", "LightningMaximumHitTaken", "ChaosMaximumHitTaken",
                   "LifeRegen", "ManaRegen", "EnergyShieldRegen", "LifeLeechRate", "ManaLeechRate", "EnergyShieldLeechRate", "TotalEHP",
                   "FireResist", "ColdResist", "LightningResist", "ChaosResist", "BlockChance", "SpellBlockChance",
                   "Str", "Dex", "Int", "TotalDPS", "CombinedDPS", "FullDPS", "Speed", "CritChance", "CritMultiplier",
                   "MinionTotalDPS", "MinionCombinedDPS", "MinionSpeed", "DeflectionRating"]
STAT_NAMES = set(get_args(StatName))
EquipmentSlot = Literal["helmet", "body_armour", "gloves", "boots", "belt", "amulet",
    "ring_left", "ring_right", "ring_third", "weapon_main", "weapon_off",
    "flask_1", "flask_2", "charm_1", "charm_2", "charm_3",
    "arm_1", "arm_2", "leg_1", "leg_2"]
EQUIPMENT_SLOTS = set(get_args(EquipmentSlot))


class BuildError(Exception):
    """Fixed public error code only; never wrap user content or file paths."""


class DTO(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class PlayerStat(DTO):
    name: StatName
    value: Annotated[float, Field(ge=-1e15, le=1e15, allow_inf_nan=False)]


class Counts(DTO):
    saved_items: Annotated[int, Field(ge=0, le=10000)]
    saved_skill_groups: Annotated[int, Field(ge=0, le=10000)]
    saved_gems: Annotated[int, Field(ge=0, le=10000)]
    saved_tree_specs: Annotated[int, Field(ge=0, le=100)]


class BuildOrigin(DTO):
    league_name: Annotated[str, Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9 ()-]+$')]
    league_slug: Annotated[str, Field(pattern=r'^[a-z0-9-]{1,48}$')]
    source: Literal['poe.ninja'] = 'poe.ninja'


class BuildSummary(DTO):
    build_id: Annotated[str, Field(pattern=r"^bld_[0-9a-f]{32}$", max_length=36)]
    imported_at_epoch: Annotated[int, Field(ge=0, le=100000000000)]
    class_name: ClassName
    class_name_ko: Annotated[str, Field(max_length=160)] | None = None
    class_name_source_ko: Annotated[str, Field(max_length=1024)] | None = None
    level: Annotated[int, Field(ge=1, le=100)]
    target_version: Annotated[list[Annotated[int, Field(ge=0, le=999)]], Field(min_length=1, max_length=4)] | None
    stats: Annotated[list[PlayerStat], Field(max_length=64)]
    counts: Counts
    stats_origin: Literal["saved_pob_export_not_recalculated"] = "saved_pob_export_not_recalculated"
    counts_scope: Literal["all_saved_loadouts_not_active_only"] = "all_saved_loadouts_not_active_only"
    live_character: Literal[False] = False
    arbitrary_text_omitted: Literal[True] = True


class TreeSpec(DTO):
    index: Annotated[int, Field(ge=0, le=99)]
    node_ids: Annotated[list[Annotated[int, Field(ge=0, le=2147483647)]], Field(max_length=2000)]


class EquipmentProperty(DTO):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    value: Annotated[str, Field(min_length=1, max_length=160)]


class EquipmentModifier(DTO):
    text: Annotated[str, Field(min_length=1, max_length=240)]
    kind: Literal["implicit", "explicit", "rune", "enchant", "crafted", "fractured", "unknown"]
    text_trust: Literal["external_game_data_not_instructions"] = "external_game_data_not_instructions"
    calculation_support: Literal["not_assessed_by_projection"] = "not_assessed_by_projection"


class ProjectedEquipmentItem(DTO):
    slot: EquipmentSlot
    saved_item_id: Annotated[int, Field(ge=1, le=1000000)]
    rarity: Literal["normal", "magic", "rare", "unique", "other"]
    name: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    base_type: Annotated[str, Field(min_length=1, max_length=160)]
    item_level: Annotated[int, Field(ge=0, le=100)] | None = None
    quality: Annotated[int, Field(ge=-100, le=100)] | None = None
    level_requirement: Annotated[int, Field(ge=0, le=100)] | None = None
    corrupted: bool = False
    socket_count: Annotated[int, Field(ge=0, le=16)] | None = None
    properties: Annotated[list[EquipmentProperty], Field(max_length=24)] = []
    modifiers: Annotated[list[EquipmentModifier], Field(max_length=32)] = []
    modifier_count: Annotated[int, Field(ge=0, le=1000)] = 0
    modifiers_truncated: bool = False


class EquipmentItem(DTO):
    effective_modifiers_verified: Literal[False] = False
    slot: EquipmentSlot
    saved_item_id: Annotated[int, Field(ge=1, le=1000000)]
    rarity: Literal["normal", "magic", "rare", "unique", "other"]
    name: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    base_type: Annotated[str, Field(min_length=1, max_length=160)]
    base_type_ko: Annotated[str, Field(max_length=160)] | None = None
    base_type_source_ko: Annotated[str, Field(max_length=1024)] | None = None
    item_level: Annotated[int, Field(ge=0, le=100)] | None = None
    quality: Annotated[int, Field(ge=-100, le=100)] | None = None
    level_requirement: Annotated[int, Field(ge=0, le=100)] | None = None
    corrupted: bool = False
    socket_count: Annotated[int, Field(ge=0, le=16)] | None = None
    properties: Annotated[list[EquipmentProperty], Field(max_length=24)] = []
    modifiers: Annotated[list[EquipmentModifier], Field(max_length=32)] = []
    modifier_count: Annotated[int, Field(ge=0, le=1000)] = 0
    modifiers_omitted: bool = False
    modifiers_truncated: bool = False


class BuildEquipment(DTO):
    build_id: Annotated[str, Field(pattern=r"^bld_[0-9a-f]{32}$", max_length=36)]
    items: Annotated[list[EquipmentItem], Field(max_length=20)]
    total: Annotated[int, Field(ge=0, le=20)]
    detail: bool
    page_scope: Literal["items", "properties_then_modifiers"]
    page_total: Annotated[int, Field(ge=0, le=1000)]
    next_offset: Annotated[int, Field(ge=0, le=1000)] | None = None
    source: Literal["saved_pob_equipped_item_projection"] = "saved_pob_equipped_item_projection"
    raw_payload_exposed: Literal[False] = False
    interpretation_scope: Literal["saved_text_structure_not_engine_effect_validation"] = "saved_text_structure_not_engine_effect_validation"


class Projection(DTO):
    schema_version: Literal[1] = 1
    equipment_projection_version: Literal[1] | None = None
    equipment_source: Literal["poe.ninja"] | None = None
    summary: BuildSummary
    trees: Annotated[list[TreeSpec], Field(max_length=100)]
    equipment: Annotated[list[ProjectedEquipmentItem], Field(max_length=20)] = []


class NodePage(DTO):
    build_id: Annotated[str, Field(pattern=r"^bld_[0-9a-f]{32}$", max_length=36)]
    spec_index: Annotated[int, Field(ge=0, le=99)]
    node_ids: Annotated[list[Annotated[int, Field(ge=0, le=2147483647)]], Field(max_length=100)]
    total: Annotated[int, Field(ge=0, le=2000)]
    next_offset: Annotated[int, Field(ge=0, le=2000)] | None


def check_id(value: str):
    if not isinstance(value, str) or not BUILD_ID_RE.fullmatch(value):
        raise BuildError("invalid_build_reference")


ProjectionDTO = TypeVar('ProjectionDTO', bound=DTO)


def bounded_dto(value: ProjectionDTO) -> ProjectionDTO:
    if len(value.model_dump_json().encode("utf-8")) > MAX_TOOL_JSON_BYTES:
        raise BuildError("projection_response_too_large")
    return value


def read_regular_file(path: Path, max_bytes: int) -> bytes:
    """Bound reads and refuse symlinks. Linux homelab uses O_NOFOLLOW."""
    if path.is_symlink():
        raise BuildError("file_unavailable")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise BuildError("file_unavailable")
            data = file.read(max_bytes + 1)
    except OSError:
        raise BuildError("file_unavailable") from None
    if len(data) > max_bytes:
        raise BuildError("input_too_large")
    return data


class BuildReader:
    def __init__(self, projection_dir: str | Path):
        self.root = Path(projection_dir).resolve()

    def load(self, build_id: str) -> Projection:
        check_id(build_id)
        try:
            raw = read_regular_file(self.root / (build_id + ".json"), MAX_PROJECTION_BYTES)
            projection = Projection.model_validate_json(raw)
        except (ValidationError, ValueError, RecursionError):
            raise BuildError("invalid_build_projection") from None
        if projection.summary.build_id != build_id:
            raise BuildError("invalid_build_projection")
        return projection

    def summary(self, build_id: str) -> BuildSummary:
        from .game_terms import name_fields
        summary = self.load(build_id).summary
        return bounded_dto(summary.model_copy(update=name_fields(summary.class_name, "class_name")))

    def nodes(self, build_id: str, spec_index=0, offset=0, limit=50) -> NodePage:
        if any(type(v) is not int for v in (spec_index, offset, limit)) or not (0 <= spec_index < 100 and 0 <= offset <= 2000 and 1 <= limit <= 100):
            raise BuildError("invalid_node_page")
        projection = self.load(build_id)
        specs = [v for v in projection.trees if v.index == spec_index]
        if len(specs) != 1:
            raise BuildError("tree_spec_unavailable")
        nodes = specs[0].node_ids
        return bounded_dto(NodePage(build_id=build_id, spec_index=spec_index,
            node_ids=nodes[offset:offset+limit], total=len(nodes),
            next_offset=offset+limit if offset+limit < len(nodes) else None))

    def equipment(self, build_id: str, slot: EquipmentSlot | None = None, offset=0, limit=5) -> BuildEquipment:
        from .game_terms import name_fields
        if type(offset) is not int or type(limit) is not int or not (0 <= offset <= 1000 and 1 <= limit <= 10):
            raise BuildError("invalid_equipment_page")
        projection = self.load(build_id)
        if projection.equipment_projection_version != 1:
            raise BuildError("equipment_projection_unavailable")
        items = [item for item in projection.equipment if slot is None or item.slot == slot]
        if slot is not None and not items:
            raise BuildError("equipped_item_unavailable")
        detail = slot is not None
        total = len(items)
        page_total = len(items[0].properties) + len(items[0].modifiers) if detail else total
        if not detail:
            items = items[offset:offset+limit]
        result = []
        for item in items:
            data = item.model_dump()
            data.update(name_fields(item.base_type, "base_type"))
            data["modifiers_omitted"] = not detail and bool(item.modifier_count)
            if not detail:
                data["properties"] = []
                data["modifiers"] = []
            else:
                property_count = len(item.properties)
                data["properties"] = item.properties[offset:min(property_count, offset+limit)]
                data["modifiers"] = item.modifiers[max(0, offset-property_count):max(0, offset+limit-property_count)]
                data["modifiers_omitted"] = len(data["modifiers"]) < len(item.modifiers)
            result.append(EquipmentItem.model_validate(data))
        page = BuildEquipment(build_id=build_id, items=result, total=total, detail=detail,
            page_scope="properties_then_modifiers" if detail else "items", page_total=page_total,
            next_offset=offset+limit if offset+limit < page_total else None)
        if len(page.model_dump_json().encode("utf-8")) > MAX_TOOL_JSON_BYTES and limit > 1:
            return self.equipment(build_id, slot, offset, max(1, limit // 2))
        return bounded_dto(page)
