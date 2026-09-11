"""A joint swap's lost suppliers and corrective requirements, without fake prices."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .builds import DTO, StatName, bounded_dto
from .experiment_models import ExperimentID, EquipItem, UnequipItem
from .workflow_store import DecisionStore, WorkflowError
from .subjects import SubjectBinding


class MetricFloor(DTO):
    metric: StatName
    minimum: Annotated[float,Field(ge=-1e12,le=1e12,allow_inf_nan=False)]


class DependencyRequest(DTO):
    experiment_id: ExperimentID
    floors: Annotated[list[MetricFloor],Field(max_length=12)] = Field(default_factory=list)

    @model_validator(mode='after')
    def distinct(self):
        if len({f.metric for f in self.floors})!=len(self.floors):raise ValueError('duplicate_metric_floor')
        return self


class LostSupply(DTO):
    metric: StatName
    baseline: float
    candidate: float
    change: float
    scope: Literal['joint_changeset_difference_not_single_item_causal_attribution'] = 'joint_changeset_difference_not_single_item_causal_attribution'


class CorrectionRequirement(DTO):
    metric: str
    minimum_additional: float
    requirement_origin: Literal['native_requirement','user_metric_floor','native_nonnegative_spirit_reservation']
    resolved_purchase_cost: None = None
    next_action: Literal['find_gear_passive_or_gem_correction_and_recalculate_joint_plan'] = 'find_gear_passive_or_gem_correction_and_recalculate_joint_plan'


class DependencyResult(DTO):
    experiment_id: str
    subject: SubjectBinding | None
    lost_supplies: Annotated[list[LostSupply],Field(max_length=20)]
    corrective_bill: Annotated[list[CorrectionRequirement],Field(max_length=16)]
    unknown_user_floors: Annotated[list[StatName],Field(max_length=12)]
    lost_mechanics: Annotated[list[str],Field(max_length=32)]
    original_item_slots_changed: Annotated[list[str],Field(max_length=10)]
    final_equipment_validity: Literal['pass','fail','indeterminate']
    actual_transition_status: str
    complete_package_cost_known: Literal[False] = False
    alone_is_purchase_recommendation: Literal[False] = False


def analyze(request: DependencyRequest,store: DecisionStore,owner: str) -> DependencyResult:
    document=store.get(owner,request.experiment_id)
    before,after=document.calculation.baseline,document.calculation.result
    if after is None:raise WorkflowError('joint_changeset_not_evaluated')
    old={s.name:s.value for s in before.stats};new={s.name:s.value for s in after.stats}
    suppliers: list[StatName]=['Str','Dex','Int','FireResist','ColdResist','LightningResist','ChaosResist','Spirit','SpiritUnreserved',
        'Life','Mana','EnergyShield','LifeRegen','ManaRegen','EnergyShieldRegen','LifeLeechRate','ManaLeechRate','EnergyShieldLeechRate','EnergyShieldRecharge']
    net_metrics: list[tuple[StatName,StatName]]=[('LifeRegen','LifeRegenRecovery'),('ManaRegen','ManaRegenRecovery'),('EnergyShieldRegen','EnergyShieldRegenRecovery')]
    for base,net in net_metrics:
        if net in old and net in new:
            suppliers[suppliers.index(base)]=net
    losses=[LostSupply(metric=n,baseline=old[n],candidate=new[n],change=new[n]-old[n]) for n in suppliers
        if n in old and n in new and new[n]<old[n]]
    corrections: dict[str,CorrectionRequirement]={}
    if after.requirements:
        for source in after.requirements.sources:
            if source.attribute_requirements_ignored:continue
            for attr in ['strength','dexterity','intelligence']:
                needed=max(0,getattr(source.modified_attributes,attr)-getattr(source.satisfying_attributes,attr))
                metric={'strength':'Str','dexterity':'Dex','intelligence':'Int'}[attr]
                if needed>0 and (metric not in corrections or needed>corrections[metric].minimum_additional):
                    corrections[metric]=CorrectionRequirement(metric=metric,minimum_additional=needed,requirement_origin='native_requirement')
    unknown=[]
    for floor in request.floors:
        if floor.metric not in new:unknown.append(floor.metric);continue
        needed=max(0,floor.minimum-new[floor.metric])
        if needed>0 and (floor.metric not in corrections or needed>corrections[floor.metric].minimum_additional):
            corrections[floor.metric]=CorrectionRequirement(metric=floor.metric,minimum_additional=needed,requirement_origin='user_metric_floor')
    if new.get('SpiritUnreserved',0)<0:
        corrections['SpiritUnreserved']=CorrectionRequirement(metric='SpiritUnreserved',minimum_additional=-new['SpiritUnreserved'],
            requirement_origin='native_nonnegative_spirit_reservation')
    active=lambda s:{m.mechanic for m in s.mechanics if m.status not in {'inactive','unsupported'}}
    return bounded_dto(DependencyResult(experiment_id=request.experiment_id,subject=after.subject,lost_supplies=losses,
        corrective_bill=list(corrections.values()),unknown_user_floors=unknown,lost_mechanics=sorted(active(before)-active(after))[:32],
        original_item_slots_changed=sorted({e.slot for e in document.request.edits if isinstance(e,(EquipItem,UnequipItem))}),
        final_equipment_validity=after.equipment_validity or after.validation,
        actual_transition_status=document.audit.equipment_transition.status if document.audit.equipment_transition else document.audit.transition_validation))
