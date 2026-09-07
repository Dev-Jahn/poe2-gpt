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
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

BUILD_ID_RE = re.compile(r"bld_[0-9a-f]{32}\Z")
MAX_PROJECTION_BYTES = 128 * 1024
MAX_TOOL_JSON_BYTES = 8192
BASE_CLASSES = ("Warrior", "Mercenary", "Ranger", "Huntress", "Monk", "Druid",
                "Sorceress", "Witch", "Marauder", "Duelist", "Shadow", "Templar", "Unknown")
ClassName = Literal["Warrior", "Mercenary", "Ranger", "Huntress", "Monk", "Druid",
                    "Sorceress", "Witch", "Marauder", "Duelist", "Shadow", "Templar", "Unknown"]
StatName = Literal["Life", "LifeUnreserved", "Mana", "ManaUnreserved", "EnergyShield", "Armour", "Evasion",
                   "FireResist", "ColdResist", "LightningResist", "ChaosResist", "BlockChance", "SpellBlockChance",
                   "Str", "Dex", "Int", "TotalDPS", "CombinedDPS", "FullDPS", "Speed", "CritChance", "CritMultiplier"]
STAT_NAMES = set(StatName.__args__)


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


class BuildSummary(DTO):
    build_id: Annotated[str, Field(pattern=r"^bld_[0-9a-f]{32}$", max_length=36)]
    imported_at_epoch: Annotated[int, Field(ge=0, le=100000000000)]
    class_name: ClassName
    level: Annotated[int, Field(ge=1, le=100)]
    target_version: Annotated[list[Annotated[int, Field(ge=0, le=999)]], Field(min_length=1, max_length=4)] | None
    stats: Annotated[list[PlayerStat], Field(max_length=22)]
    counts: Counts
    stats_origin: Literal["saved_pob_export_not_recalculated"] = "saved_pob_export_not_recalculated"
    counts_scope: Literal["all_saved_loadouts_not_active_only"] = "all_saved_loadouts_not_active_only"
    live_character: Literal[False] = False
    arbitrary_text_omitted: Literal[True] = True


class TreeSpec(DTO):
    index: Annotated[int, Field(ge=0, le=99)]
    node_ids: Annotated[list[Annotated[int, Field(ge=0, le=2147483647)]], Field(max_length=2000)]


class Projection(DTO):
    schema_version: Literal[1] = 1
    summary: BuildSummary
    trees: Annotated[list[TreeSpec], Field(max_length=100)]


class NodePage(DTO):
    build_id: Annotated[str, Field(pattern=r"^bld_[0-9a-f]{32}$", max_length=36)]
    spec_index: Annotated[int, Field(ge=0, le=99)]
    node_ids: Annotated[list[Annotated[int, Field(ge=0, le=2147483647)]], Field(max_length=100)]
    total: Annotated[int, Field(ge=0, le=2000)]
    next_offset: Annotated[int, Field(ge=0, le=2000)] | None


def check_id(value: str):
    if not isinstance(value, str) or not BUILD_ID_RE.fullmatch(value):
        raise BuildError("invalid_build_reference")


def bounded_dto(value: DTO):
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
        return bounded_dto(self.load(build_id).summary)

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
