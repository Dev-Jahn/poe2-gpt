"""Evaluate complete support alternatives against one immutable skill instance."""
from __future__ import annotations
from typing import Annotated, Literal, TYPE_CHECKING
from pydantic import Field, model_validator
from .builds import DTO, PlayerStat, bounded_dto, BuildError
from .profiles import BuildRef, Digest
from .subjects import CalculationTarget
from .experiment_models import Edit, ExperimentRequest, ExperimentID, SetSupports
from .calculation_config import CalculationConfiguration
from .combat_models import CombatScenario
from .catalog_models import CatalogRequest, CatalogPage
from .workflow_store import WorkflowError
from .game_terms import name_fields

if TYPE_CHECKING:
    from .workflows import WorkflowService


class SupportAlternative(DTO):
    support_gem_ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=160)]], Field(max_length=5)]
    proposed_socket_capacity: Annotated[int, Field(ge=0, le=5)]

    @model_validator(mode='after')
    def capacity(self):
        if len(set(self.support_gem_ids)) != len(self.support_gem_ids): raise ValueError('duplicate_support_gem')
        if len(self.support_gem_ids) > self.proposed_socket_capacity: raise ValueError('support_capacity_exceeded')
        return self


class SupportPortfolioRequest(DTO):
    base_build_id: BuildRef
    base_snapshot_digest: Digest
    tree_revision: Annotated[str, Field(pattern=r'^[0-9]+_[0-9]+$', max_length=24)]
    engine_data_commit: Annotated[str, Field(pattern=r'^[0-9a-f]{40}$')]
    target: CalculationTarget
    configuration: CalculationConfiguration | None = None
    combat_scenario: CombatScenario | None = None
    observed_socket_capacity: Annotated[int, Field(ge=0, le=5)]
    common_edits: Annotated[list[Edit], Field(max_length=24)] = Field(default_factory=list)
    ordinary_points_available: Annotated[int, Field(ge=0, le=128)] = 0
    ascendancy_points_available: Annotated[int, Field(ge=0, le=8)] = 0
    alternatives: Annotated[list[SupportAlternative], Field(min_length=1, max_length=6)]
    persist_decisions: bool = False

    @model_validator(mode='after')
    def clear_target(self):
        for edit in self.common_edits:
            if isinstance(edit,SetSupports) and edit.skill_instance_id == self.target.skill_instance_id:
                raise ValueError('portfolio_supports_defined_by_alternative')
        return self


class SupportIdentity(DTO):
    catalog_id: str
    name: str
    name_ko: str | None
    translation_source: str | None


class SupportComparison(DTO):
    index: int
    experiment_id: ExperimentID
    calculation_id: str
    plan_digest: Digest
    supports: Annotated[list[SupportIdentity], Field(max_length=5)]
    proposed_socket_capacity: int
    additional_sockets_required: int
    socket_upgrade_cost_known: Literal[False] = False
    total_purchase_cost: None = None
    metrics: Annotated[list[PlayerStat], Field(max_length=8)]
    marginal_metrics: Annotated[list[PlayerStat], Field(max_length=8)]
    validation: Literal['pass', 'fail', 'indeterminate', 'not_evaluated']
    objective_metric_covered: bool
    calculation_certified: bool
    objective_rank: int | None = None
    ranking_scope: Literal['exact_supplied_alternatives_same_subject_and_scenario'] = 'exact_supplied_alternatives_same_subject_and_scenario'


class SupportPortfolio(DTO):
    base_build_id: BuildRef
    target: CalculationTarget
    comparisons: Annotated[list[SupportComparison], Field(max_length=6)]
    objective_metric: Literal['CombinedDPS', 'MinionCombinedDPS']
    primary_experiment_id: ExperimentID | None
    evaluated_alternatives: int
    worker_invocations: Literal[1] = 1
    saved_build_modified: Literal[False] = False
    all_support_combinations_explored: Literal[False] = False
    comparisons_truncated: bool = False
    full_plan_detail_tool: Literal['get_build_plan'] = 'get_build_plan'
    # Each retained plan is independently retrievable even if labels are paged.
    experiment_ids: Annotated[list[ExperimentID], Field(max_length=6)]
    next_action: Literal['price_socket_and_gem_bill_then_validate_joint_purchase_plan'] = 'price_socket_and_gem_bill_then_validate_joint_purchase_plan'


async def compare(request: SupportPortfolioRequest, workflow: WorkflowService, owner: str) -> SupportPortfolio:
    if request.target.actor_ref not in {'player','minion'}: raise WorkflowError('portfolio_actor_unavailable')
    wanted = sorted({identifier for alt in request.alternatives for identifier in alt.support_gem_ids})
    identities = {}
    for start in range(0,len(wanted),20):
        offset = 0
        while True:
            page = await workflow.engine.static_request('/catalog',CatalogRequest(build_id=request.base_build_id,
                entity_type='gem',catalog_ids=wanted[start:start+20],offset=offset,limit=10,level_limit=1),CatalogPage)
            for gem in page.gems:
                if not gem.support: raise WorkflowError('portfolio_entity_is_not_support')
                labels = name_fields(gem.name)
                identities[gem.catalog_id] = SupportIdentity(catalog_id=gem.catalog_id,name=gem.name,
                    name_ko=labels['name_ko'],translation_source=labels['name_source_ko'])
            if page.next_offset is None: break
            offset = page.next_offset
    if set(identities) != set(wanted): raise WorkflowError('portfolio_support_not_in_pinned_catalog')
    plans = [ExperimentRequest(base_build_id=request.base_build_id,base_snapshot_digest=request.base_snapshot_digest,
        tree_revision=request.tree_revision,engine_data_commit=request.engine_data_commit,target=request.target,
        configuration=request.configuration,combat_scenario=request.combat_scenario,
        ordinary_points_available=request.ordinary_points_available,ascendancy_points_available=request.ascendancy_points_available,
        edits=[*request.common_edits,SetSupports(type='set_supports',skill_instance_id=request.target.skill_instance_id,
            support_gem_ids=alt.support_gem_ids,observed_socket_capacity=alt.proposed_socket_capacity,
            socket_capacity_evidence='planned_upgrade' if alt.proposed_socket_capacity > request.observed_socket_capacity else 'user_reported',
            original_observed_socket_capacity=request.observed_socket_capacity)],
        persist_decision=request.persist_decisions) for alt in request.alternatives]
    results = await workflow.create_variants(owner,plans)
    objective: Literal['CombinedDPS','MinionCombinedDPS'] = 'CombinedDPS' if request.target.actor_ref == 'player' else 'MinionCombinedDPS'
    metrics = {objective,'ManaCost','ESCost','ManaPerSecondCost','ESPerSecondCost','AreaOfEffectRadius','Life','EnergyShield'}
    comparisons = []
    for index,(alt,result) in enumerate(zip(request.alternatives,results,strict=True)):
        document = workflow.store.get(owner,result.experiment_id)
        after = document.calculation.result
        covered = bool(after and after.subject and after.subject.status == 'matched'
            and any(c.stat == objective and c.status == 'pass' for c in after.metric_coverage))
        comparisons.append(SupportComparison(index=index,experiment_id=result.experiment_id,
            calculation_id=result.calculation_id,plan_digest=result.plan_digest,supports=[identities[i] for i in alt.support_gem_ids],
            proposed_socket_capacity=alt.proposed_socket_capacity,additional_sockets_required=max(0,alt.proposed_socket_capacity-request.observed_socket_capacity),
            metrics=[s for s in after.stats if s.name in metrics] if after else [],
            marginal_metrics=[s for s in document.calculation.deltas if s.name in metrics],
            validation=result.candidate_validation,calculation_certified=result.certified,objective_metric_covered=covered))
    eligible = [row for row in comparisons if row.calculation_certified and row.objective_metric_covered
        and any(s.name == objective for s in row.metrics)]
    eligible.sort(key=lambda row:(-next(s.value for s in row.metrics if s.name == objective),row.index))
    for rank,row in enumerate(eligible,1): row.objective_rank = rank
    response = SupportPortfolio(base_build_id=request.base_build_id,target=request.target,comparisons=comparisons,
        objective_metric=objective,primary_experiment_id=eligible[0].experiment_id if eligible else None,
        evaluated_alternatives=len(results),experiment_ids=[r.experiment_id for r in results])
    while True:
        try: return bounded_dto(response)
        except BuildError:
            if len(response.comparisons) <= 1: raise
            response.comparisons.pop()
            response.comparisons_truncated = True
