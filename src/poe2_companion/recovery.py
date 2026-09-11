"""Deficit-limited recovery under explicit finite event schedules.

This is a deterministic scenario integrator, not a drop-rate, combat AI or
unobserved sustain estimator. Unknown leech expiry produces both bounds.
"""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .builds import DTO
from .subjects import Actor
from .engine_models import EngineSnapshot
from .capabilities import digest

Number = Annotated[float,Field(ge=0,le=1e12,allow_inf_nan=False)]
Seconds = Annotated[float,Field(ge=0,le=120,allow_inf_nan=False)]
Resource = Literal['life','mana','energy_shield']
Uncertainty = Literal['mana_leech_expiry_unknown','damage_schedule_is_assumed',
    'max_hit_not_derived_from_post_mitigation_schedule','resource_parameters_are_explicit_inputs',
    'native_parameter_coverage_is_reported_separately']


class ResourceState(DTO):
    resource: Resource
    maximum: Number
    initial: Number
    regeneration_per_second: Number
    recharge_per_second: Number = 0.0
    recharge_delay_seconds: Seconds = 0.0
    initial_recharge_delay_remaining: Seconds = 0.0

    @model_validator(mode='after')
    def bounded_initial(self) -> Self:
        if self.initial>self.maximum: raise ValueError('initial_exceeds_capacity')
        return self


class DamageEvent(DTO):
    at: Seconds
    resource: Resource
    post_mitigation_damage: Number
    interrupts_recharge: bool = True


class AttackEvent(DTO):
    at: Seconds
    mana_cost: Number = 0.0
    energy_shield_cost: Number = 0.0


class RecoveryFlow(DTO):
    kind: Literal['leech','recoup','regeneration']
    resource: Resource
    producer: Actor
    recipient: Actor
    starts_at: Seconds
    ends_at: Seconds
    potential_per_second: Number
    source_skill_instance_id: Annotated[str,Field(pattern=r'^skill:s[1-9][0-9]{0,3}:g[1-9][0-9]{0,3}:n[1-9][0-9]{0,3}$')]
    # A copied ES leech instance can share the uncertain lifetime of its
    # originating mana instance. This is an explicit scenario assumption.
    expires_with_full_mana: bool = False

    @model_validator(mode='after')
    def ordered(self) -> Self:
        if self.ends_at<=self.starts_at: raise ValueError('flow_interval_invalid')
        return self


class RecoveryRequest(DTO):
    calculation_id: Annotated[str,Field(pattern=r'^calc_[0-9a-f]{32}$')]
    side: Literal['baseline','result'] = 'result'
    scenario: Literal['no_hit','continuous_hits','ritual','boss_no_adds','custom']
    duration_seconds: Annotated[float,Field(gt=0,le=120,allow_inf_nan=False)]
    resources: Annotated[list[ResourceState],Field(min_length=1,max_length=3)]
    incoming_hits: Annotated[list[DamageEvent],Field(max_length=128)] = Field(default_factory=list)
    attacks: Annotated[list[AttackEvent],Field(max_length=128)] = Field(default_factory=list)
    flows: Annotated[list[RecoveryFlow],Field(max_length=32)] = Field(default_factory=list)
    mana_leech_expires_at_full: bool | None = None
    inputs_evidence: Literal['user_supplied_hypothesis','user_observed_schedule'] = 'user_supplied_hypothesis'

    @model_validator(mode='after')
    def consistent(self) -> Self:
        resources={r.resource for r in self.resources}
        if len(resources)!=len(self.resources): raise ValueError('duplicate_resource')
        if any(e.at>self.duration_seconds or e.resource not in resources for e in self.incoming_hits):
            raise ValueError('damage_outside_scenario')
        if any(e.at>self.duration_seconds or (e.mana_cost and 'mana' not in resources)
                or (e.energy_shield_cost and 'energy_shield' not in resources) for e in self.attacks):
            raise ValueError('attack_outside_scenario')
        if any(f.ends_at>self.duration_seconds or f.resource not in resources for f in self.flows):
            raise ValueError('flow_outside_scenario')
        if any(f.expires_with_full_mana and (f.kind!='leech' or 'mana' not in resources) for f in self.flows):
            raise ValueError('copied_leech_requires_mana_state')
        if self.scenario=='no_hit' and self.incoming_hits: raise ValueError('no_hit_scenario_has_hits')
        if self.scenario in {'continuous_hits','ritual'} and len(self.incoming_hits)<2:
            raise ValueError('repeated_hit_schedule_required')
        return self


class ResourceOutcome(DTO):
    resource: Resource
    minimum: float
    final: float
    effective_recovery: float
    wasted_recovery: float
    damage_exceeding_available_resource: float
    first_depleted_at: float | None
    recharge_active_seconds: float


class RecoveryCase(DTO):
    mana_leech_expires_at_full: bool
    outcomes: list[ResourceOutcome]
    scheduled_attacks: int
    affordable_attacks: int
    attack_resource_coverage: float | None


class RecoveryResult(DTO):
    calculation_id: str
    assumptions_digest: str
    status: Literal['scenario_integrated','subject_mismatch','missing_subject']
    cases: Annotated[list[RecoveryCase],Field(max_length=2)]
    uncertainty: Annotated[list[Uncertainty],Field(max_length=4)]
    next_action: Literal['inspect_skill_instances','use_matching_actor_and_skill','validate_schedule_in_game']
    guaranteed_sustain: Literal[False] = False
    numerical_method: Literal['piecewise_constant_event_integration_with_capacity_clipping'] = 'piecewise_constant_event_integration_with_capacity_clipping'


def integrate(request: RecoveryRequest, expires_at_full: bool) -> RecoveryCase:
    definitions={row.resource:row for row in request.resources}
    current={name:row.initial for name,row in definitions.items()}
    minimum=dict(current)
    effective={name:0.0 for name in definitions};wasted=dict(effective);overflow=dict(effective);recharge_time=dict(effective)
    depleted={name:0.0 if amount==0 else None for name,amount in current.items()}
    recharge_ready={name:row.initial_recharge_delay_remaining for name,row in definitions.items()}
    ended: set[int] = set()
    affordable=0
    times={0.0,request.duration_seconds}
    times.update(event.at for event in request.incoming_hits)
    times.update(event.at for event in request.attacks)
    for flow in request.flows: times.update([flow.starts_at,flow.ends_at])
    for row in request.resources: times.add(min(row.initial_recharge_delay_remaining,request.duration_seconds))
    for event in request.incoming_hits:
        if event.interrupts_recharge:
            times.add(min(event.at+definitions[event.resource].recharge_delay_seconds,request.duration_seconds))
    previous=0.0
    for stamp in sorted(times):
        cursor=previous
        while cursor<stamp:
            active=[(i,f) for i,f in enumerate(request.flows) if i not in ended and f.starts_at<=cursor<f.ends_at]
            linked=[i for i,f in active if f.kind=='leech' and (f.resource=='mana' or f.expires_with_full_mana)]
            if expires_at_full and 'mana' in current and current['mana']>=definitions['mana'].maximum:
                ended.update(linked);active=[(i,f) for i,f in active if i not in ended];linked=[]
            rates={name:row.regeneration_per_second+(row.recharge_per_second if cursor>=recharge_ready[name] else 0.)
                +sum(f.potential_per_second for _,f in active if f.resource==name) for name,row in definitions.items()}
            delta=stamp-cursor
            # Split exactly when mana becomes full, including in the middle
            # of an interval, before granting copied ES recovery afterwards.
            if expires_at_full and linked and rates.get('mana',0.)>0:
                delta=min(delta,max(0.,definitions['mana'].maximum-current['mana'])/rates['mana'])
            if delta<=0:
                ended.update(linked)
                continue
            for name,row in definitions.items():
                potential=rates[name]*delta
                recovered=min(max(0.0,row.maximum-current[name]),potential)
                current[name]+=recovered;effective[name]+=recovered;wasted[name]+=potential-recovered
                if row.recharge_per_second>0 and cursor>=recharge_ready[name]:recharge_time[name]+=delta
            cursor+=delta
        # A hit at the same timestamp precedes a planned attack. This ordering
        # is explicit and deterministic, not an inferred server combat tick.
        for event in request.incoming_hits:
            if event.at!=stamp: continue
            name=event.resource
            overflow[name]+=max(0.0,event.post_mitigation_damage-current[name])
            current[name]=max(0.0,current[name]-event.post_mitigation_damage)
            if event.interrupts_recharge: recharge_ready[name]=stamp+definitions[name].recharge_delay_seconds
        for attack in request.attacks:
            if attack.at!=stamp: continue
            costs: dict[Resource,float] = {'mana':attack.mana_cost,'energy_shield':attack.energy_shield_cost}
            if all(cost<=current.get(name,0.0) for name,cost in costs.items()):
                affordable+=1
                for name,cost in costs.items():
                    if name in current: current[name]-=cost
        for name,value in current.items():
            minimum[name]=min(minimum[name],value)
            if value==0 and depleted[name] is None: depleted[name]=stamp
        previous=stamp
    return RecoveryCase(mana_leech_expires_at_full=expires_at_full,
        outcomes=[ResourceOutcome(resource=name,minimum=minimum[name],final=current[name],effective_recovery=effective[name],
            wasted_recovery=wasted[name],damage_exceeding_available_resource=overflow[name],
            first_depleted_at=depleted[name],recharge_active_seconds=recharge_time[name]) for name in definitions],
        scheduled_attacks=len(request.attacks),affordable_attacks=affordable,
        attack_resource_coverage=affordable/len(request.attacks) if request.attacks else None)


def analyze(request: RecoveryRequest, snapshot: EngineSnapshot) -> RecoveryResult:
    uncertainty: list[Uncertainty] = ['resource_parameters_are_explicit_inputs','max_hit_not_derived_from_post_mitigation_schedule']
    if request.inputs_evidence=='user_supplied_hypothesis': uncertainty.append('damage_schedule_is_assumed')
    subject=snapshot.subject.evaluated if snapshot.subject and snapshot.subject.status!='unavailable' else None
    if subject is None:
        return RecoveryResult(calculation_id=request.calculation_id,assumptions_digest=digest(request.model_dump(mode='json')),
            status='missing_subject',cases=[],uncertainty=uncertainty,next_action='inspect_skill_instances')
    if any(flow.source_skill_instance_id!=subject.skill_instance_id or flow.producer!=subject.actor_ref
            or flow.recipient!='player' or flow.producer!='player' for flow in request.flows):
        return RecoveryResult(calculation_id=request.calculation_id,assumptions_digest=digest(request.model_dump(mode='json')),
            status='subject_mismatch',cases=[],uncertainty=uncertainty,next_action='use_matching_actor_and_skill')
    cases=[request.mana_leech_expires_at_full] if request.mana_leech_expires_at_full is not None else [True,False]
    if request.mana_leech_expires_at_full is None: uncertainty.append('mana_leech_expiry_unknown')
    return RecoveryResult(calculation_id=request.calculation_id,assumptions_digest=digest(request.model_dump(mode='json')),
        status='scenario_integrated',cases=[integrate(request,value) for value in cases],uncertainty=uncertainty,
        next_action='validate_schedule_in_game')
