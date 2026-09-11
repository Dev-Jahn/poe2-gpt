"""Native requirement provenance; equipment/gem maxima and support totals differ."""
from __future__ import annotations
from typing import Annotated, Literal, TYPE_CHECKING
from pydantic import Field
from .builds import DTO, bounded_dto, BuildError
from .subjects import SubjectBinding

if TYPE_CHECKING:
    from .engine_models import EngineSnapshot

Value = Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)]


class Attributes(DTO):
    strength: Value = 0
    dexterity: Value = 0
    intelligence: Value = 0


class RequirementSource(DTO):
    kind: Literal['equipment', 'native_gem', 'support_total']
    saved_item_id: Annotated[int, Field(ge=1, le=1000000)] | None = None
    slot: Annotated[str, Field(max_length=80)] | None = None
    skill_instance_id: Annotated[str, Field(max_length=100)] | None = None
    skill_id: Annotated[str, Field(max_length=120)] | None = None
    support: bool = False
    native_level: Annotated[int, Field(ge=1, le=100)] | None = None
    effective_level: Annotated[int, Field(ge=1, le=1000)] | None = None
    character_level_required: Annotated[int, Field(ge=0, le=1000)] = 0
    base_attributes: Attributes
    modified_attributes: Attributes
    satisfying_attributes: Attributes
    attribute_requirements_ignored: bool
    satisfied: bool


class RequirementBreakdown(DTO):
    available: Attributes
    engine_required: Attributes
    equipment_maximum: Attributes
    native_gem_maximum: Attributes
    support_sum: Attributes
    sources: Annotated[list[RequirementSource], Field(max_length=10000)]
    aggregation: Literal['max_equipment_max_native_gems_sum_supports'] = 'max_equipment_max_native_gems_sum_supports'
    weapon_scope: Literal['pinned_engine_active_skill_set_support_count'] = 'pinned_engine_active_skill_set_support_count'
    own_attributes_prove_initial_equip: Literal[False] = False


class RequirementsRequest(DTO):
    calculation_id: Annotated[str, Field(pattern=r'^calc_[0-9a-f]{32}$')]
    side: Literal['baseline', 'result'] = 'baseline'
    offset: Annotated[int, Field(ge=0, le=10000)] = 0
    limit: Annotated[int, Field(ge=1, le=8)] = 5


class RequirementsPage(DTO):
    calculation_id: str
    side: Literal['baseline', 'result']
    subject: SubjectBinding | None
    summary: RequirementBreakdown
    total: int
    next_offset: int | None
    transition_order: Annotated[list[str], Field(max_length=32)]
    final_equipment_validity: Literal['pass', 'fail', 'indeterminate']
    detail_scope: Literal['native_calculation_requirements_not_live_equipment'] = 'native_calculation_requirements_not_live_equipment'


def page(request: RequirementsRequest, snapshot: EngineSnapshot) -> RequirementsPage:
    from .engine_models import EngineError
    if snapshot.requirements is None:
        raise EngineError('calculation_expired_or_unavailable')
    summary = snapshot.requirements.model_copy(deep=True)
    total = len(summary.sources)
    summary.sources = summary.sources[request.offset:request.offset + request.limit]
    result = RequirementsPage(calculation_id=request.calculation_id, side=request.side,
        subject=snapshot.subject, summary=summary, total=total,
        next_offset=request.offset + len(summary.sources) if request.offset + len(summary.sources) < total else None,
        transition_order=list(snapshot.equip_order),
        final_equipment_validity=snapshot.equipment_validity or snapshot.validation)
    while True:
        try:
            return bounded_dto(result)
        except BuildError:
            if len(summary.sources) <= 1:
                raise
            summary.sources.pop()
            result.next_offset = request.offset + len(summary.sources)
