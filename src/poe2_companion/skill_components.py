"""Independent actor/component calculations; no unproved rotation sum."""
import time
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .builds import DTO, PlayerStat, bounded_dto, tool_json_bytes
from .profiles import BuildRef
from .subjects import CalculationTarget, SubjectBinding
from .calculation_config import CalculationConfiguration
from .combat_models import CombatScenario
from .engine_models import EngineCalculation, EngineRequest
from .engine_protocol import WorkerRequest
from .engine import EngineClient, calculation_context


class ComponentRequest(DTO):
    build_id: BuildRef
    targets: Annotated[list[CalculationTarget],Field(min_length=1,max_length=6)]
    configuration: CalculationConfiguration | None = None
    combat_scenario: CombatScenario | None = None
    offset: Annotated[int,Field(ge=0,le=100)] = 0
    limit: Annotated[int,Field(ge=1,le=6)] = 3

    @model_validator(mode='after')
    def unique(self):
        keys=[t.model_dump_json() for t in self.targets]
        if len(keys)!=len(set(keys)):raise ValueError('duplicate_component_target')
        return self


class ComponentRow(DTO):
    requested_index: int
    subject: SubjectBinding
    calculation_id: str
    diagnostics_expires_at_epoch: int
    metrics: Annotated[list[PlayerStat],Field(max_length=6)]
    metric_coverage: Literal['all_displayed_metrics_certified','contains_unresolved_metrics','unavailable']
    validation: Literal['pass','fail','indeterminate']


class ComponentBreakdown(DTO):
    build_id: BuildRef
    total_components: int
    next_offset: int | None
    components: Annotated[list[ComponentRow],Field(max_length=6)]
    aggregation_scope: Literal['independent_native_component_snapshots'] = 'independent_native_component_snapshots'
    combined_rotation_dps: None = None
    reason_sum_unavailable: Literal['simultaneous_uptime_trigger_copy_and_rotation_ownership_not_proven'] = 'simultaneous_uptime_trigger_copy_and_rotation_ownership_not_proven'
    resource_cost_scope: Literal['selected_component_player_cost_or_explicit_minion_metrics'] = 'selected_component_player_cost_or_explicit_minion_metrics'


async def calculate(request: ComponentRequest,engine: EngineClient) -> ComponentBreakdown:
    worker=await engine.batch(WorkerRequest(build_id=request.build_id,configuration=request.configuration,
        combat_scenario=request.combat_scenario,component_targets=request.targets,
        component_offset=request.offset,component_limit=request.limit))
    rows=[]
    for part in worker.components:
        snapshot=part.snapshot
        assert snapshot.subject is not None and snapshot.subject.requested is not None
        context=EngineRequest(build_id=request.build_id,target=snapshot.subject.requested,
            configuration=request.configuration,combat_scenario=request.combat_scenario)
        receipt=EngineCalculation(build_id=request.build_id,calculated_at_epoch=int(time.time()),baseline=snapshot,
            **calculation_context(context))
        engine.receipts.retain(receipt,context)
        assert receipt.calculation_id is not None and receipt.diagnostics_expires_at_epoch is not None
        actor=snapshot.subject.requested.actor_ref
        names=({'MinionTotalDPS','MinionCombinedDPS','MinionSpeed'} if actor in {'minion','spirit_vessel'} else
            {'TotalDPS','CombinedDPS','Speed','ManaCost','ESCost','CritChance'})
        metrics=[s for s in snapshot.stats if s.name in names]
        covered={c.stat for c in snapshot.metric_coverage if c.status=='pass'}
        rows.append(ComponentRow(requested_index=part.requested_index,subject=snapshot.subject,
            calculation_id=receipt.calculation_id,diagnostics_expires_at_epoch=receipt.diagnostics_expires_at_epoch,
            metrics=metrics,metric_coverage='unavailable' if not metrics else
            'all_displayed_metrics_certified' if all(s.name in covered for s in metrics) else 'contains_unresolved_metrics',validation=snapshot.validation))
    result=ComponentBreakdown(build_id=request.build_id,total_components=worker.component_total,
        next_offset=request.offset+len(rows) if request.offset+len(rows)<worker.component_total else None,components=rows)
    while tool_json_bytes(result)>8192 and len(result.components)>1:
        result.components.pop();result.next_offset=request.offset+len(result.components)
    return bounded_dto(result)
