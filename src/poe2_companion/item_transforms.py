"""Original/effective provenance and interval-only treatment of unrolled results."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .builds import DTO, StatName, bounded_dto
from .experiment_models import ExperimentID, SavedItemSource, RetainedItemSource
from .workflow_store import DecisionStore, WorkflowError
from .capabilities import digest


class FeasibleMetricEnvelope(DTO):
    metric: StatName
    lower: Annotated[float,Field(ge=-1e12,le=1e12,allow_inf_nan=False)]
    upper: Annotated[float,Field(ge=-1e12,le=1e12,allow_inf_nan=False)]
    preferred_direction: Literal['higher','lower'] = 'higher'
    evidence: Literal['user_supplied_hypothetical_character_metric_envelope']

    @model_validator(mode='after')
    def ordered(self):
        if self.lower>self.upper:raise ValueError('transformation_interval_reversed')
        return self


class TransformRequest(DTO):
    original_experiment_id: ExperimentID
    effective_experiment_ids: Annotated[list[ExperimentID],Field(max_length=4)] = Field(default_factory=list)
    mapping_family: Literal['stonefist_gloves'] = 'stonefist_gloves'
    association_evidence: Literal['user_reported_original_effective_relationship']
    unrolled_envelopes: Annotated[list[FeasibleMetricEnvelope],Field(max_length=6)] = Field(default_factory=list)

    @model_validator(mode='after')
    def distinct(self):
        if len(set(self.effective_experiment_ids))!=len(self.effective_experiment_ids):raise ValueError('duplicate_effective_variant')
        if len({r.metric for r in self.unrolled_envelopes})!=len(self.unrolled_envelopes):raise ValueError('duplicate_interval_metric')
        return self


class EffectiveVariant(DTO):
    experiment_id: str
    item: SavedItemSource | RetainedItemSource
    native_transformed_rolls_loaded: bool
    unresolved_metrics: Annotated[list[StatName],Field(max_length=16)]
    calculation_id: str | None
    evaluated_changeset_digest: str


class IntervalComparison(DTO):
    metric: StatName
    lower: float
    upper: float
    baseline: float | None
    ordering: Literal['strictly_better_under_supplied_envelope','strictly_worse_under_supplied_envelope','overlapping_or_equal','baseline_unavailable']
    midpoint_estimate: None = None
    game_feasible_bounds_verified: Literal[False] = False


class TransformResult(DTO):
    original_experiment_id: str
    original_item: SavedItemSource | RetainedItemSource
    effective_variants: Annotated[list[EffectiveVariant],Field(max_length=4)]
    unrolled_metric_intervals: Annotated[list[IntervalComparison],Field(max_length=6)]
    original_calculation_status: Literal['unresolved_transformation','already_transformed','mapping_not_active']
    affected_metrics: Annotated[list[StatName],Field(max_length=16)]
    required_input: Literal['actual_transformed_item_rolls_or_independently_verified_feasible_envelope'] | None
    provenance_link_evidence: Literal['user_reported_not_seed_reconstructed'] = 'user_reported_not_seed_reconstructed'
    original_values_eligible_for_ranking: Literal[False] = False
    all_supplied_bounds_dominate_baseline: bool
    ranking_scope: Literal['conditional_on_supplied_envelopes_not_a_verified_purchase_recommendation'] = 'conditional_on_supplied_envelopes_not_a_verified_purchase_recommendation'


def analyze(request: TransformRequest,store: DecisionStore,owner: str) -> TransformResult:
    original=store.get(owner,request.original_experiment_id)
    def source(doc):
        changes=[e for e in doc.request.edits if e.type=='equip_item' and e.slot=='gloves']
        if len(changes)!=1:raise WorkflowError('transformation_requires_one_identified_glove_edit')
        return changes[0].source
    original_source=source(original)
    def context(doc):
        value=doc.request.model_dump(mode='json',exclude={'edits','persist_decision','temporary_equipment','transition_state_budget'})
        value['other_edits']=[e.model_dump(mode='json') for e in doc.request.edits if not (e.type=='equip_item' and e.slot=='gloves')]
        return digest(value)
    status: Literal['unresolved_transformation','already_transformed','mapping_not_active']='mapping_not_active'
    snapshot=original.calculation.result
    mechanic=next((m for m in snapshot.mechanics if m.mechanic=='stonefist'),None) if snapshot else None
    if mechanic:
        transformed=any(m.name=='already_transformed' and m.value==1 for m in mechanic.metrics)
        status='already_transformed' if transformed and mechanic.status=='calculated' else 'unresolved_transformation'
    metrics: list[StatName]=['EnergyShield','Evasion','Armour','Life','Mana','TotalDPS','CombinedDPS','Str','Dex','Int',
        'FireResist','ColdResist','LightningResist','ChaosResist','EnergyShieldRegen','EnergyShieldLeechRate']
    variants=[]
    for identifier in request.effective_experiment_ids:
        doc=store.get(owner,identifier)
        if context(doc)!=context(original):raise WorkflowError('transformation_context_mismatch')
        item=source(doc);after=doc.calculation.result
        transformed=bool(after and any(m.mechanic=='stonefist' and m.status=='calculated' and
            any(v.name=='already_transformed' and v.value==1 for v in m.metrics) for m in after.mechanics))
        coverage={m.stat for m in after.metric_coverage if m.status=='pass'} if after else set()
        variants.append(EffectiveVariant(experiment_id=identifier,item=item,native_transformed_rolls_loaded=transformed,
            unresolved_metrics=[m for m in metrics if m not in coverage or not transformed],
            calculation_id=doc.calculation.calculation_id,evaluated_changeset_digest=doc.plan_digest))
    before={s.name:s.value for s in original.calculation.baseline.stats}
    intervals=[]
    for envelope in request.unrolled_envelopes:
        baseline=before.get(envelope.metric)
        ordering: Literal['strictly_better_under_supplied_envelope','strictly_worse_under_supplied_envelope','overlapping_or_equal','baseline_unavailable']
        if baseline is None:ordering='baseline_unavailable'
        elif (envelope.lower>baseline if envelope.preferred_direction=='higher' else envelope.upper<baseline):ordering='strictly_better_under_supplied_envelope'
        elif (envelope.upper<baseline if envelope.preferred_direction=='higher' else envelope.lower>baseline):ordering='strictly_worse_under_supplied_envelope'
        else:ordering='overlapping_or_equal'
        intervals.append(IntervalComparison(metric=envelope.metric,lower=envelope.lower,upper=envelope.upper,baseline=baseline,ordering=ordering))
    return bounded_dto(TransformResult(original_experiment_id=original.experiment_id,original_item=original_source,
        effective_variants=variants,unrolled_metric_intervals=intervals,original_calculation_status=status,affected_metrics=metrics,
        required_input=None if variants and all(v.native_transformed_rolls_loaded for v in variants) else 'actual_transformed_item_rolls_or_independently_verified_feasible_envelope',
        all_supplied_bounds_dominate_baseline=bool(intervals) and all(r.ordering=='strictly_better_under_supplied_envelope' for r in intervals)))
