"""Rule-scoped explanations. Presence in a catalog never certifies mechanics."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .builds import DTO, StatName, bounded_dto, tool_json_bytes
from .subjects import Actor, SubjectBinding
from .engine_models import ENGINE_COMMIT,ENGINE_DATA_COMMIT,EngineSnapshot

Charge=Literal['power','frenzy','endurance']
RuleID=Literal['critical_event_requires_nonzero_chance','player_kill_requires_player_credit',
    'self_blind_requires_infliction','charge_consumer_requires_matching_supply']


class ChargeSupply(DTO):
    producer: Actor
    recipient: Actor
    generated_type: Charge
    converted_type: Charge | None = None
    events_per_second: Annotated[float,Field(ge=0,le=10000,allow_inf_nan=False)]


class RiskRequest(DTO):
    calculation_id: Annotated[str,Field(pattern=r'^calc_[0-9a-f]{32}$')]
    side: Literal['baseline','result'] = 'result'
    intended_rules: Annotated[list[RuleID],Field(max_length=4)] = Field(default_factory=list)
    blind_source: Literal['self','other_actor','unknown'] = 'unknown'
    kill_credit_actor: Actor | None = None
    charge_supplies: Annotated[list[ChargeSupply],Field(max_length=16)] = Field(default_factory=list)
    consumed_charge_type: Charge | None = None
    consumer: Actor = 'player'
    required_charge_events_per_second: Annotated[float,Field(ge=0,le=10000,allow_inf_nan=False)] | None = None
    event_evidence: Literal['hypothesis','user_reported'] = 'hypothesis'
    automatic_checks: bool = True
    guaranteed_critical_target_exception: bool | None = None
    effect_offset: Annotated[int,Field(ge=0,le=34)] = 0
    effect_limit: Annotated[int,Field(ge=1,le=16)] = 8

    @model_validator(mode='after')
    def unique_rules(self) -> Self:
        if len(set(self.intended_rules))!=len(self.intended_rules): raise ValueError('duplicate_rule')
        return self


class EffectEdge(DTO):
    producer: Actor
    event_owner: Actor
    recipient: Actor
    event: Literal['kill','blind','charge_gain','charge_conversion','charge_consumption']
    resource_before: Charge | None = None
    resource_after: Charge | None = None
    rate: float | None = None
    evidence: Literal['hypothesis','user_reported','native_snapshot']


class RuleFinding(DTO):
    rule_id: RuleID
    status: Literal['blocked','conditional','satisfied_under_inputs']
    affected_metrics: Annotated[list[StatName],Field(max_length=8)]
    reason: Literal['zero_critical_chance','critical_chance_unavailable','non_player_kill_credit',
        'kill_credit_unknown','self_cannot_inflict_blind','external_blind_is_separate',
        'blind_source_unknown','charge_supply_missing','charge_supply_below_demand',
        'charge_rate_is_not_uptime','condition_satisfied_under_inputs','guaranteed_target_exception_requires_native_scenario']
    next_action: Literal['change_critical_source_and_recalculate','identify_event_owner',
        'declare_external_blind_source','restore_matching_charge_supply','supply_charge_consumption_rate',
        'validate_event_schedule','none']
    rule_revision: Literal['effect-graph-v1'] = 'effect-graph-v1'
    evidence_scope: Literal['native_snapshot','supplied_event_hypothesis','user_reported_event']
    triggered_by: Literal['requested_goal','native_snapshot_condition'] = 'requested_goal'
    native_rule_source: str = 'https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/tree/'+ENGINE_COMMIT+'/src/Modules'
    supplied_event_conversion_verified_as_game_rule: Literal[False] = False


class ScopedMetric(DTO):
    name: StatName
    value: float | None
    coverage: Literal['certified_for_snapshot','estimate_not_certified','unavailable']
    limitation: Literal['unresolved_dependency','requested_subject_unavailable'] | None = None


class ValidationAxes(DTO):
    identity: Literal['matched','saved_default','unavailable']
    equipment: Literal['pass','fail','indeterminate']
    requirements: Literal['pass','fail','indeterminate']
    mechanics: Literal['pass','fail','indeterminate']
    scenario_evidence: Literal['hypothesis','user_reported']
    freshness: Literal['immutable_snapshot_not_live_state'] = 'immutable_snapshot_not_live_state'


class RiskResult(DTO):
    calculation_id: str
    engine_commit: str = ENGINE_COMMIT
    engine_data_commit: str = ENGINE_DATA_COMMIT
    subject: SubjectBinding | None
    axes: ValidationAxes
    metrics: Annotated[list[ScopedMetric],Field(max_length=12)]
    findings: Annotated[list[RuleFinding],Field(max_length=4)]
    effect_graph: Annotated[list[EffectEdge],Field(max_length=34)]
    effect_graph_total: int
    next_effect_offset: int | None
    certified: bool
    global_confidence_score: None = None
    critical_chance_scope: Literal['selected_subject_and_configured_target_not_all_enemies'] = 'selected_subject_and_configured_target_not_all_enemies'


def analyze(request: RiskRequest, snapshot: EngineSnapshot) -> RiskResult:
    values={s.name:s.value for s in snapshot.stats}
    mechanics={(m.mechanic,v.name):v.value for m in snapshot.mechanics for v in m.metrics}
    findings=[];edges=[]
    rules=list(request.intended_rules)
    if request.automatic_checks:
        inferred: list[RuleID]=[]
        if values.get('CritChance')==0:inferred.append('critical_event_requires_nonzero_chance')
        if mechanics.get(('hit_effects','cannot_inflict_blind'))==1:inferred.append('self_blind_requires_infliction')
        if any(m.mechanic in {'thrill_of_the_kill','behead'} for m in snapshot.mechanics):inferred.append('player_kill_requires_player_credit')
        if any(m.mechanic in {'charge_regulation'} for m in snapshot.mechanics):inferred.append('charge_consumer_requires_matching_supply')
        rules.extend(rule for rule in inferred if rule not in rules)
    evidence='user_reported_event' if request.event_evidence=='user_reported' else 'supplied_event_hypothesis'
    def add(rule,status,reason,action,scope=evidence):
        findings.append(RuleFinding(rule_id=rule,status=status,reason=reason,next_action=action,
            affected_metrics=['TotalDPS','CombinedDPS'],evidence_scope=scope,
            triggered_by='requested_goal' if rule in request.intended_rules else 'native_snapshot_condition'))
    for rule in rules:
        if rule=='critical_event_requires_nonzero_chance':
            subject=snapshot.subject.evaluated if snapshot.subject else None
            chance=values.get('CritChance') if subject and subject.actor_ref=='player' else None
            if chance is None: add(rule,'conditional','critical_chance_unavailable','change_critical_source_and_recalculate','native_snapshot')
            elif chance==0 and request.guaranteed_critical_target_exception is True:
                add(rule,'conditional','guaranteed_target_exception_requires_native_scenario','validate_event_schedule')
            elif chance==0: add(rule,'blocked','zero_critical_chance','change_critical_source_and_recalculate','native_snapshot')
            else: add(rule,'satisfied_under_inputs','condition_satisfied_under_inputs','validate_event_schedule','native_snapshot')
        elif rule=='player_kill_requires_player_credit':
            credit=request.kill_credit_actor
            if credit is None: add(rule,'conditional','kill_credit_unknown','identify_event_owner')
            else:
                edges.append(EffectEdge(producer=credit,event_owner=credit,recipient='player',event='kill',evidence=request.event_evidence))
                add(rule,'satisfied_under_inputs' if credit=='player' else 'blocked',
                    'condition_satisfied_under_inputs' if credit=='player' else 'non_player_kill_credit',
                    'validate_event_schedule' if credit=='player' else 'identify_event_owner')
        elif rule=='self_blind_requires_infliction':
            cannot=mechanics.get(('hit_effects','cannot_inflict_blind'))
            if request.blind_source=='other_actor': add(rule,'conditional','external_blind_is_separate','validate_event_schedule')
            elif request.blind_source=='self' and cannot==1: add(rule,'blocked','self_cannot_inflict_blind','declare_external_blind_source','native_snapshot')
            elif request.blind_source=='self' and cannot==0: add(rule,'conditional','condition_satisfied_under_inputs','validate_event_schedule','native_snapshot')
            else: add(rule,'conditional','blind_source_unknown','declare_external_blind_source')
        else:
            supplied=0.0
            for supply in request.charge_supplies:
                actual=supply.converted_type or supply.generated_type
                edges.append(EffectEdge(producer=supply.producer,event_owner=supply.recipient,recipient=supply.recipient,
                    event='charge_conversion' if supply.converted_type else 'charge_gain',resource_before=supply.generated_type,
                    resource_after=actual,rate=supply.events_per_second,evidence=request.event_evidence))
                if supply.recipient==request.consumer and actual==request.consumed_charge_type: supplied+=supply.events_per_second
            demand=request.required_charge_events_per_second
            if request.consumed_charge_type is None or demand is None: add(rule,'conditional','charge_rate_is_not_uptime','supply_charge_consumption_rate')
            elif supplied==0 and demand>0: add(rule,'blocked','charge_supply_missing','restore_matching_charge_supply')
            elif supplied<demand: add(rule,'blocked','charge_supply_below_demand','restore_matching_charge_supply')
            else: add(rule,'conditional','charge_rate_is_not_uptime','validate_event_schedule')
    verified={r.stat for r in snapshot.metric_coverage if r.status=='pass'}
    identity=snapshot.subject.status if snapshot.subject else 'unavailable'
    primary: list[StatName] = ['Life','Mana','EnergyShield','TotalDPS','CombinedDPS','FireResist','ColdResist','LightningResist','ChaosResist','Str','Dex','Int']
    metrics=[]
    for name in primary:
        value=values.get(name)
        coverage: Literal['unavailable','certified_for_snapshot','estimate_not_certified'] = 'unavailable' if value is None else 'certified_for_snapshot' if name in verified else 'estimate_not_certified'
        limitation: Literal['requested_subject_unavailable','unresolved_dependency'] | None = 'requested_subject_unavailable' if identity=='unavailable' else 'unresolved_dependency' if name not in verified else None
        if identity=='unavailable':value=None;coverage='unavailable'
        metrics.append(ScopedMetric(name=name,value=value,coverage=coverage,limitation=limitation))
    requirement_codes={'level_requirement','attribute_requirement','gem_level_requirement','class_requirement','reservation_invalid'}
    requirements: Literal['pass','fail','indeterminate'] = 'fail' if any(i.code in requirement_codes for i in snapshot.issues) else 'pass' if snapshot.validation=='pass' else 'indeterminate'
    end=request.effect_offset+request.effect_limit
    result=RiskResult(calculation_id=request.calculation_id,subject=snapshot.subject,
        axes=ValidationAxes(identity=identity,equipment=snapshot.equipment_validity or snapshot.validation,
            requirements=requirements,mechanics=snapshot.validation,scenario_evidence=request.event_evidence),
        metrics=metrics,findings=findings,effect_graph=edges[request.effect_offset:end],effect_graph_total=len(edges),
        next_effect_offset=end if end<len(edges) else None,
        certified=snapshot.validation=='pass' and identity=='matched' and not findings)
    while tool_json_bytes(result)>8192 and result.effect_graph:
        result.effect_graph.pop();result.next_effect_offset=request.effect_offset+len(result.effect_graph)
    return bounded_dto(result)
