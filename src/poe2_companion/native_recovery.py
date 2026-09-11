"""Bind a finite scenario to retained native resource and skill-cost metrics."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .builds import DTO, bounded_dto
from .subjects import CalculationTarget
from .engine_models import EngineSnapshot
from .recovery import RecoveryRequest, RecoveryResult, DamageEvent, RecoveryFlow, Resource, Seconds, analyze
from .workflow_store import WorkflowError


class InitialResource(DTO):
    resource: Resource
    fraction_of_capacity: Annotated[float,Field(ge=0,le=1,allow_inf_nan=False)] = 1.
    initial_recharge_delay_remaining: Seconds = 0.


class NativeRecoveryRequest(DTO):
    calculation_id: Annotated[str,Field(pattern=r'^calc_[0-9a-f]{32}$')]
    side: Literal['baseline','result'] = 'result'
    target: CalculationTarget
    scenario: Literal['no_hit','continuous_hits','ritual','boss_no_adds','custom']
    duration_seconds: Annotated[float,Field(gt=0,le=120,allow_inf_nan=False)]
    resources: Annotated[list[InitialResource],Field(min_length=1,max_length=3)]
    incoming_hits: Annotated[list[DamageEvent],Field(max_length=128)] = Field(default_factory=list)
    attack_times: Annotated[list[Seconds],Field(max_length=128)] = Field(default_factory=list)
    # Flow rates and schedules remain explicit; instantaneous native leech
    # potential alone cannot establish duration, kill credit or hit uptime.
    flows: Annotated[list[RecoveryFlow],Field(max_length=32)] = Field(default_factory=list)
    mana_leech_expires_at_full: bool | None = None
    inputs_evidence: Literal['user_supplied_hypothesis','user_observed_schedule'] = 'user_supplied_hypothesis'

    @model_validator(mode='after')
    def unique_resources(self):
        if len({r.resource for r in self.resources})!=len(self.resources):raise ValueError('duplicate_resource')
        return self


class ParameterBinding(DTO):
    parameter: str
    metric: str
    value: float
    evidence: Literal['certified_for_snapshot','native_estimate_unresolved_dependencies']


class NativeRecoveryResult(DTO):
    calculation_id: str
    status: Literal['scenario_integrated','subject_mismatch','missing_native_parameters']
    bindings: Annotated[list[ParameterBinding],Field(max_length=12)]
    missing_parameters: Annotated[list[str],Field(max_length=12)]
    recovery: RecoveryResult | None
    flow_schedule_is_native_proven: Literal[False] = False
    incoming_damage_is_post_mitigation_input: Literal[True] = True
    live_character_confirmed: Literal[False] = False


def bind(request: NativeRecoveryRequest,snapshot: EngineSnapshot) -> NativeRecoveryResult:
    subject=snapshot.subject.evaluated if snapshot.subject and snapshot.subject.status!='unavailable' else None
    target=request.target
    if not subject or (subject.skill_instance_id,subject.actor_ref,subject.weapon_set_id)!=(target.skill_instance_id,target.actor_ref,target.weapon_set_id) or (
            target.component_ref and subject.component_ref!=target.component_ref) or (
            target.actor_owner_instance_id and subject.actor_owner_instance_id!=target.actor_owner_instance_id) or target.actor_ref!='player':
        return NativeRecoveryResult(calculation_id=request.calculation_id,status='subject_mismatch',bindings=[],missing_parameters=[],recovery=None)
    values: dict[str,float]={s.name:s.value for s in snapshot.stats}
    certified={r.stat for r in snapshot.metric_coverage if r.status=='pass'}
    bindings=[];missing=[]
    def value(parameter: str,metric: str,allow_negative: bool=False) -> float:
        number=values.get(metric)
        if number is None or (number<0 and not allow_negative):missing.append(metric);return 0.
        bindings.append(ParameterBinding(parameter=parameter,metric=metric,value=number,evidence=
            'certified_for_snapshot' if metric in certified else 'native_estimate_unresolved_dependencies'))
        return number
    states=[]
    for row in request.resources:
        capacity,regen={'life':('LifeUnreserved','LifeRegenRecovery'),'mana':('ManaUnreserved','ManaRegenRecovery'),
            'energy_shield':('EnergyShield','EnergyShieldRegenRecovery')}[row.resource]
        maximum=value(row.resource+'.maximum',capacity)
        net_regen=value(row.resource+'.net_regeneration_per_second',regen,True)
        state={'resource':row.resource,'maximum':maximum,'initial':maximum*row.fraction_of_capacity,
            'regeneration_per_second':max(0.,net_regen),'degeneration_per_second':max(0.,-net_regen),
            'initial_recharge_delay_remaining':row.initial_recharge_delay_remaining}
        if row.resource=='energy_shield':
            state.update(recharge_per_second=value('energy_shield.recharge_per_second','EnergyShieldRecharge'),
                recharge_delay_seconds=value('energy_shield.recharge_delay_seconds','EnergyShieldRechargeDelay'))
        states.append(state)
    attacks=[]
    if request.attack_times:
        mana=value('attack.mana_cost','ManaCost');es=value('attack.energy_shield_cost','ESCost')
        if values.get('LifeCost',0)>0:missing.append('life_cost_schedule_unsupported')
        attacks=[{'at':t,'mana_cost':mana,'energy_shield_cost':es} for t in request.attack_times]
    if missing:
        return NativeRecoveryResult(calculation_id=request.calculation_id,status='missing_native_parameters',bindings=bindings,missing_parameters=missing,recovery=None)
    try:
        query=RecoveryRequest.model_validate(dict(calculation_id=request.calculation_id,side=request.side,scenario=request.scenario,
            duration_seconds=request.duration_seconds,resources=states,incoming_hits=request.incoming_hits,attacks=attacks,
            flows=request.flows,mana_leech_expires_at_full=request.mana_leech_expires_at_full,inputs_evidence=request.inputs_evidence))
    except ValueError:raise WorkflowError('native_recovery_schedule_incompatible_with_resources') from None
    recovery=analyze(query,snapshot)
    recovery.uncertainty=[u for u in recovery.uncertainty if u!='resource_parameters_are_explicit_inputs']
    recovery.uncertainty.append('native_parameter_coverage_is_reported_separately')
    return bounded_dto(NativeRecoveryResult(calculation_id=request.calculation_id,status=
        'scenario_integrated' if recovery.status=='scenario_integrated' else 'subject_mismatch',
        bindings=bindings,missing_parameters=[],recovery=recovery))
