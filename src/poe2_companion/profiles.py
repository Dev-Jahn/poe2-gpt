"""Calculation-free, bounded identity projections. Raw payloads stay private."""
from typing import Annotated, Literal

from pydantic import Field

from .builds import DTO, Counts, ClassName, BuildEquipment, BuildReader, BuildError, bounded_dto
from .inspection import InspectionRecord
from .catalog_models import NativeCatalog

Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
BuildRef = Annotated[str, Field(pattern=r'^bld_[0-9a-f]{32}$')]
SkillInstanceID = Annotated[str, Field(pattern=r'^skill:s[1-9][0-9]{0,3}:g[1-9][0-9]{0,3}:n[1-9][0-9]{0,3}$')]


class ProfileRequest(DTO):
    build_id: BuildRef
    changed_since_build_id: BuildRef | None = None
    skill_instance_ids: Annotated[list[SkillInstanceID], Field(max_length=12)] = Field(default_factory=list)
    offset: Annotated[int, Field(ge=0, le=10000)] = 0
    limit: Annotated[int, Field(ge=1, le=12)] = 6


class NativeAttributes(DTO):
    strength: Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)] = 0
    dexterity: Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)] = 0
    intelligence: Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)] = 0


class SkillInstance(DTO):
    skill_instance_id: SkillInstanceID
    skill_id: Annotated[str, Field(pattern=r'^[A-Za-z0-9_]+$', max_length=120)]
    name: Annotated[str, Field(max_length=240)]
    skill_set_id: int
    group_index: int
    gem_index: int
    gem_catalog_id: Annotated[str, Field(max_length=160)] | None = None
    native_character_level_required: int | None = None
    native_attributes_before_modifiers: NativeAttributes | None = None
    native_level: int
    quality: float
    enabled: bool
    active_set: bool
    saved_main_group: bool
    support: bool
    origin: Literal['socketed', 'granted']
    # Actor ownership is established during evaluation, never guessed from a name.
    actor_verification: Literal['requires_evaluation'] = 'requires_evaluation'


class ProfileSlot(DTO):
    slot: Annotated[str, Field(max_length=80)]
    saved_item_id: Annotated[int, Field(ge=1, le=1000000)] | None = None
    empty: bool
    augment_socket_capacity: Annotated[int, Field(ge=0, le=32)]
    empty_augment_sockets: Annotated[int, Field(ge=0, le=32)]


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
    equipment_slots: Annotated[list[ProfileSlot], Field(max_length=10)] = Field(default_factory=list)


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
    projection_schema_revision: Literal['static-v2'] = 'static-v2'
    metadata: ProfileMetadata
    skill_instances: Annotated[list[SkillInstance], Field(max_length=12)]
    total_skill_instances: int
    next_offset: int | None = None
    changed_since: Literal['same_content', 'different_content', 'not_requested']
    source: Literal['private_native_loaders_without_combat_calculation'] = 'private_native_loaders_without_combat_calculation'
    content_is_live_state: Literal[False] = False
    calculated_metrics_available: Literal[False] = False
    requirement_scope: Literal['native_per_gem_values_only_aggregate_and_build_modifiers_require_calculation'] = 'native_per_gem_values_only_aggregate_and_build_modifiers_require_calculation'
    raw_payload_exposed: Literal[False] = False
    next_action: Literal['select_discovered_skill_instance_for_calculation'] = 'select_discovered_skill_instance_for_calculation'


class SavedProfileFallback(DTO):
    build_id: BuildRef
    status: Literal['partial_saved_projection'] = 'partial_saved_projection'
    source: Literal['immutable_import_projection_without_native_interpretation'] = 'immutable_import_projection_without_native_interpretation'
    imported_at_epoch: int
    class_name: ClassName
    level: int
    counts: Counts
    equipment: BuildEquipment | None
    native_unavailable_reason: Literal['not_configured','engine_busy','engine_unavailable','engine_timeout','engine_calculation_failed']
    unavailable: list[str]
    content_is_live_state: Literal[False] = False
    calculated_metrics_available: Literal[False] = False
    raw_payload_exposed: Literal[False] = False
    next_action: Literal['configure_private_engine','retry_static_profile_after_worker_recovers']
    equipment_detail_tool: Literal['get_saved_build_equipment'] = 'get_saved_build_equipment'


def saved_fallback(reader: BuildReader, request: ProfileRequest, reason) -> SavedProfileFallback:
    summary=reader.summary(request.build_id)
    unavailable=['native_skill_instances','effective_modifiers','snapshot_digest','derived_metrics','changed_since_comparison']
    try: equipment=reader.equipment(request.build_id,limit=5)
    except BuildError as exc:
        if str(exc)!='equipment_projection_unavailable':raise
        equipment=None;unavailable.append('equipment_projection')
    return bounded_dto(SavedProfileFallback(build_id=request.build_id,imported_at_epoch=summary.imported_at_epoch,
        class_name=summary.class_name,level=summary.level,counts=summary.counts,equipment=equipment,
        native_unavailable_reason=reason,unavailable=unavailable,
        next_action='configure_private_engine' if reason=='not_configured' else 'retry_static_profile_after_worker_recovers'))
