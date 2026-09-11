"""Compare complete native paths against one declared skill and weapon context."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .builds import DTO, PlayerStat, StatName, bounded_dto
from .catalog_models import NodeID, PassiveRouteRequest, PassiveRoute
from .experiment_models import ExperimentRequest, AllocatePassives, RefundPassives, AttributeChoice, Edit
from .profiles import ProfileRequest
from .workflows import WorkflowService
from .workflow_store import WorkflowError
from .capabilities import digest


class PathAlternative(DTO):
    target_node_ids: Annotated[list[NodeID],Field(min_length=1,max_length=4)]
    allocation_mode: Literal[0,1,2] = 0


class PassiveTemplate(ExperimentRequest):
    edits: Annotated[list[Edit],Field(max_length=28)] = Field(default_factory=list)


class PassivePortfolioRequest(DTO):
    template: PassiveTemplate
    alternatives: Annotated[list[PathAlternative],Field(min_length=1,max_length=6)]
    refund_node_ids: Annotated[list[NodeID],Field(max_length=32)] = Field(default_factory=list)
    attribute_choices: Annotated[list[AttributeChoice],Field(max_length=64)] = Field(default_factory=list)
    objective_metric: StatName = 'EnergyShield'

    @model_validator(mode='after')
    def scope(self):
        if len(self.template.edits)>28:raise ValueError('passive_portfolio_common_edit_limit')
        if any(e.type in {'allocate_passives','refund_passives','set_ascendancy'} for e in self.template.edits):
            raise ValueError('tree_edits_are_defined_by_path_alternatives')
        if len(set(self.refund_node_ids))!=len(self.refund_node_ids):raise ValueError('duplicate_refund')
        if len({a.node_id for a in self.attribute_choices})!=len(self.attribute_choices):raise ValueError('duplicate_attribute_choice')
        if len({a.model_dump_json() for a in self.alternatives})!=len(self.alternatives):raise ValueError('duplicate_path_alternative')
        return self


class PathComparison(DTO):
    index: int
    target_node_ids: list[NodeID]
    allocation_mode: Literal[0,1,2]
    status: str
    total_new_path_nodes: int
    ordinary_points_delta: int
    ascendancy_points_delta: int
    weapon_set_points_delta: int
    experiment_id: str | None = None
    plan_digest: str | None = None
    calculation_id: str | None = None
    objective_value: float | None = None
    marginal_gain: float | None = None
    gain_per_new_path_point: float | None = None
    objective_covered: bool = False
    equipment_valid: bool = False
    transition_verified: bool = False
    objective_rank: int | None = None
    resources: Annotated[list[PlayerStat],Field(max_length=5)] = Field(default_factory=list)
    route_detail_tool: Literal['plan_passive_route'] = 'plan_passive_route'
    full_plan_tool: Literal['get_build_plan'] = 'get_build_plan'


class PassivePortfolio(DTO):
    base_build_id: str
    target_context_digest: str
    objective_metric: StatName
    comparisons: Annotated[list[PathComparison],Field(max_length=6)]
    native_worker_invocations: int
    primary_experiment_id: str | None
    search_scope: Literal['full_shortest_paths_for_supplied_targets_and_allocation_modes'] = 'full_shortest_paths_for_supplied_targets_and_allocation_modes'
    global_optimum_proven: Literal[False] = False
    comparison_scope: Literal['same_target_weapon_set_and_scenario_including_common_edits'] = 'same_target_weapon_set_and_scenario_including_common_edits'
    cost_scope: Literal['every_new_travel_and_target_node_with_shared_native_point_pools'] = 'every_new_travel_and_target_node_with_shared_native_point_pools'
    jewel_effects: Literal['unchanged_private_jewels_recalculated_at_each_joint_endpoint'] = 'unchanged_private_jewels_recalculated_at_each_joint_endpoint'
    prices_known: Literal[False] = False


async def compare(request: PassivePortfolioRequest, workflow: WorkflowService, owner: str) -> PassivePortfolio:
    template=request.template
    profile=await workflow.engine.profile(ProfileRequest(build_id=template.base_build_id))
    if profile.snapshot_digest!=template.base_snapshot_digest or profile.engine_data_commit!=template.engine_data_commit:
        raise WorkflowError('passive_portfolio_source_mismatch')
    rows=[];plans=[];indices=[]
    choices={c.node_id:c for c in request.attribute_choices}
    for index,alternative in enumerate(request.alternatives):
        weapon_budget=(template.weapon_set_1_points_available if alternative.allocation_mode==1 else template.weapon_set_2_points_available)
        query=PassiveRouteRequest(build_id=template.base_build_id,tree_revision=template.tree_revision,
            target_node_ids=alternative.target_node_ids,refund_node_ids=request.refund_node_ids,
            ordinary_points_available=min(64,template.ordinary_points_available),ascendancy_points_available=template.ascendancy_points_available,
            allocation_mode=alternative.allocation_mode,weapon_set_points_available=weapon_budget)
        route=await workflow.engine.static_request('/passive-route',query,PassiveRoute)
        row=PathComparison(index=index,target_node_ids=alternative.target_node_ids,allocation_mode=alternative.allocation_mode,
            status=route.status,total_new_path_nodes=route.total_steps,ordinary_points_delta=route.ordinary_points_delta,
            ascendancy_points_delta=route.ascendancy_points_delta,weapon_set_points_delta=route.weapon_set_points_delta)
        rows.append(row)
        if route.status!='route_found':continue
        steps=list(route.steps)
        while route.next_offset is not None:
            query=query.model_copy(update={'offset':route.next_offset})
            route=await workflow.engine.static_request('/passive-route',query,PassiveRoute)
            steps.extend(route.steps)
        if len(steps)>64:row.status='path_exceeds_bounded_changeset';continue
        if any(s.attribute_choice_required and s.node_id not in choices for s in steps):
            row.status='attribute_choice_required';continue
        if any(s.point_pool=='ascendancy' for s in steps):
            row.status='ascendancy_requires_separate_typed_plan';continue
        edits=list(template.edits)
        if request.refund_node_ids:edits.append(RefundPassives(type='refund_passives',node_ids=request.refund_node_ids))
        if steps:edits.append(AllocatePassives(type='allocate_passives',node_ids=[s.node_id for s in steps],
            allocation_mode=alternative.allocation_mode,attribute_choices=[choices[s.node_id] for s in steps if s.attribute_choice_required]))
        if not edits:row.status='already_allocated_no_changes';continue
        plans.append(ExperimentRequest.model_validate({**template.model_dump(),'edits':[e.model_dump() for e in edits]}));indices.append(index)
    results=await workflow.create_variants(owner,plans) if plans else []
    for index,result in zip(indices,results,strict=True):
        row=rows[index];document=workflow.store.get(owner,result.experiment_id);snapshot=document.calculation.result
        row.experiment_id=result.experiment_id;row.plan_digest=result.plan_digest;row.calculation_id=result.calculation_id
        row.status=result.audit.status
        if snapshot is None:continue
        matched=bool(snapshot.subject and snapshot.subject.status=='matched')
        row.objective_covered=matched and any(c.stat==request.objective_metric and c.status=='pass' for c in snapshot.metric_coverage)
        row.equipment_valid=snapshot.equipment_validity=='pass'
        row.transition_verified=document.audit.transition_validation in {'no_equipment_transition','verified'}
        row.objective_value=next((s.value for s in snapshot.stats if s.name==request.objective_metric),None)
        row.marginal_gain=next((s.value for s in document.calculation.deltas if s.name==request.objective_metric),None)
        row.gain_per_new_path_point=row.marginal_gain/row.total_new_path_nodes if row.marginal_gain is not None and row.total_new_path_nodes else None
        row.resources=[s for s in snapshot.stats if s.name in {'Life','Mana','EnergyShield','SpiritUnreserved','EnergyShieldRegenRecovery'}]
    eligible=sorted([r for r in rows if r.objective_covered and r.equipment_valid and r.transition_verified and r.objective_value is not None],
        key=lambda r:(-(r.objective_value or 0),r.total_new_path_nodes,r.index))
    for rank,row in enumerate(eligible,1):row.objective_rank=rank
    return bounded_dto(PassivePortfolio(base_build_id=template.base_build_id,target_context_digest=digest({
        'target':template.target.model_dump(),'configuration':template.configuration.model_dump() if template.configuration else None,
        'scenario':template.combat_scenario.model_dump() if template.combat_scenario else None}),
        objective_metric=request.objective_metric,comparisons=rows,native_worker_invocations=int(bool(plans)),
        primary_experiment_id=eligible[0].experiment_id if eligible else None))
