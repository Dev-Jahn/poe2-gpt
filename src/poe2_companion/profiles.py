"""Calculation-free, bounded identity projections. Raw payloads stay private."""
from typing import Annotated, Literal

from pydantic import Field

from .builds import DTO, Counts
from .inspection import InspectionRecord
from .catalog_models import NativeCatalog

Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
BuildRef = Annotated[str, Field(pattern=r'^bld_[0-9a-f]{32}$')]
SkillInstanceID = Annotated[str, Field(pattern=r'^skill:s[1-9][0-9]{0,3}:g[1-9][0-9]{0,3}:n[1-9][0-9]{0,3}$')]


class ProfileRequest(DTO):
    build_id: BuildRef
    changed_since_build_id: BuildRef | None = None
    offset: Annotated[int, Field(ge=0, le=10000)] = 0
    limit: Annotated[int, Field(ge=1, le=12)] = 6


class SkillInstance(DTO):
    skill_instance_id: SkillInstanceID
    skill_id: Annotated[str, Field(pattern=r'^[A-Za-z0-9_]+$', max_length=120)]
    name: Annotated[str, Field(max_length=240)]
    skill_set_id: int
    group_index: int
    gem_index: int
    native_level: int
    quality: float
    enabled: bool
    active_set: bool
    saved_main_group: bool
    support: bool
    origin: Literal['socketed', 'granted']
    # Actor ownership is established during evaluation, never guessed from a name.
    actor_verification: Literal['requires_evaluation'] = 'requires_evaluation'


class ProfileMetadata(DTO):
    level: int
    tree_version: Annotated[str, Field(max_length=24)]
    active_item_set_id: int
    active_skill_set_id: int
    active_tree_set_id: int
    active_configuration_set_id: int
    active_weapon_set_id: Literal[1, 2]
    saved_main_group: int
    counts: Counts


class StaticDocument(DTO):
    """Private socket response; full tables are never returned as one MCP result."""
    metadata: ProfileMetadata
    skills: Annotated[list[SkillInstance], Field(max_length=10000)]
    records: Annotated[list[InspectionRecord], Field(max_length=100000)]
    catalog: NativeCatalog | None = None


class BuildProfile(DTO):
    build_id: BuildRef
    snapshot_digest: Digest
    engine_commit: Annotated[str, Field(pattern=r'^[0-9a-f]{40}$')]
    engine_data_commit: Annotated[str, Field(pattern=r'^[0-9a-f]{40}$')]
    projection_schema_revision: Literal['static-v1'] = 'static-v1'
    metadata: ProfileMetadata
    skill_instances: Annotated[list[SkillInstance], Field(max_length=12)]
    total_skill_instances: int
    next_offset: int | None = None
    changed_since: Literal['same_content', 'different_content', 'not_requested']
    source: Literal['private_native_loaders_without_combat_calculation'] = 'private_native_loaders_without_combat_calculation'
    content_is_live_state: Literal[False] = False
    calculated_metrics_available: Literal[False] = False
    raw_payload_exposed: Literal[False] = False
    next_action: Literal['select_discovered_skill_instance_for_calculation'] = 'select_discovered_skill_instance_for_calculation'
