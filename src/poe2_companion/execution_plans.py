"""One human route, explicit prerequisites and observed-failure stop conditions."""
from __future__ import annotations
import secrets
import time
from typing import Annotated, Literal, Any, TYPE_CHECKING
from pydantic import Field
from .builds import DTO,bounded_dto,tool_json_bytes
from .capabilities import canonical,digest
from .catalog_models import CatalogRequest,CatalogPage
from .experiment_models import ExperimentID
from .inspection import InspectionRequest
from .observations import ObservationID,ObservationValue,keys,UnlockObservation,ResourceObservation
from .profiles import Digest,ProfileRequest
from .purchase_models import ComparisonID,PurchaseComparison
from .passive_execution import TreeAction,PassiveOrderRequest,PassiveOrderResult
from .workflow_store import DecisionStore,DecisionDocument,WorkflowError

if TYPE_CHECKING:
    from .workflows import WorkflowService

ExecutionID=Annotated[str,Field(pattern=r'^route_[0-9a-f]{32}$')]
Phase=Literal['prerequisite','prepare','apply','play_check','record']
SLOTS={'helmet':'투구','body_armour':'갑옷','gloves':'장갑','boots':'장화','belt':'허리띠','amulet':'목걸이',
    'ring_left':'왼쪽 반지','ring_right':'오른쪽 반지','weapon_main':'주무기','weapon_off':'보조무기'}


class ExecutionRequest(DTO):
    experiment_id: ExperimentID
    comparison_id: ComparisonID | None = None
    observation_ids: Annotated[list[ObservationID],Field(max_length=8)] = Field(default_factory=list)
    persist_plan: bool = False


class ExecutionStep(DTO):
    index: int
    phase: Phase
    instruction: Annotated[str,Field(max_length=5000)]
    edit_index: int | None = None
    entity_refs: Annotated[list[str],Field(max_length=128)] = Field(default_factory=list)
    temporary: bool = False
    executable_now: bool


class ExecutionDocument(DTO):
    execution_id: ExecutionID
    request: ExecutionRequest
    experiment_revision: int
    source_artifact_digest: Digest
    artifact_digest: Digest
    created_at_epoch: int
    expires_at_epoch: int
    blocking_reasons: list[str]
    risk_notes: list[str]
    steps: Annotated[list[ExecutionStep],Field(max_length=900)]
    original_step_order_is_equip_proof: Literal[False] = False
    game_state_verified: Literal[False] = False


class ExecutionSummary(DTO):
    execution_id: ExecutionID
    experiment_id: ExperimentID
    artifact_digest: Digest
    status: Literal['blocked','ready_for_user_execution']
    primary_route_count: Literal[0,1]
    next_steps: Annotated[list[ExecutionStep],Field(max_length=3)]
    blocking_reasons: list[str]
    risk_notes: list[str]
    stop_conditions: list[str]
    total_steps: int
    raw_game_actions_performed: Literal[False] = False


class ExecutionPageRequest(DTO):
    execution_id: ExecutionID
    section: Literal['steps','exact_json'] = 'steps'
    offset: Annotated[int,Field(ge=0,le=1000000)] = 0
    limit: Annotated[int,Field(ge=1,le=1000)] = 800


class ExecutionPage(DTO):
    execution_id: ExecutionID
    artifact_digest: Digest
    content: str
    total: int
    next_offset: int | None
    source_revision_changed: bool


class ExecutionReference(DTO):
    execution_id: ExecutionID


def observations(store: DecisionStore,owner: str,document: DecisionDocument,extra: list[str]) -> tuple[dict[str,ObservationValue],list[str]]:
    result: dict[str,ObservationValue]={};problems=[]
    for identifier in dict.fromkeys([*document.observation_ids,*extra]):
        try: row=store.get_observation(owner,identifier)
        except WorkflowError:
            problems.append('referenced_observation_expired_or_unavailable');continue
        if (row.request.base_build_id,row.request.base_snapshot_digest)!=(document.request.base_build_id,document.request.base_snapshot_digest):
            raise WorkflowError('execution_observation_snapshot_mismatch')
        for key,value in keys(row).items():
            if key in result and result[key]!=value: problems.append('conflicting_observation:'+key)
            result[key]=value
            if isinstance(value,ResourceObservation) and value.outcome in {'depleted','died'} and row.request.related_experiment_id==document.experiment_id:
                problems.append('adverse_outcome_reported:'+value.resource+':'+value.encounter)
    return result,list(dict.fromkeys(problems))


def risks(document: DecisionDocument) -> list[str]:
    after=document.calculation.result
    if after is None:return []
    before=document.calculation.baseline
    old: dict[str,float]={v.name:v.value for v in before.stats}
    new: dict[str,float]={v.name:v.value for v in after.stats}
    notes=[]
    for name in ['Life','EnergyShield','LifeRegen','EnergyShieldRegen','LifeRegenRecovery','EnergyShieldRegenRecovery','FireResist','ColdResist','LightningResist','SpiritUnreserved']:
        if name in old and name in new and new[name]<old[name]: notes.append(f'{name}: {old[name]:g} → {new[name]:g}')
    active=lambda snapshot:{m.mechanic for m in snapshot.mechanics if m.status in {'calculated','partial','requires_configuration'}}
    if 'ghost_dance' in active(before)-active(after): notes.append('Ghost Dance 회복 공급원이 제거됩니다. 반복 피격에서 ES 여유와 회복을 함께 확인하세요.')
    return notes


async def labels_for(workflow: WorkflowService,document: DecisionDocument) -> dict[str,str]:
    labels={}
    ids=sorted({edit.skill_instance_id for edit in document.request.edits if hasattr(edit,'skill_instance_id')})
    for start in range(0,len(ids),12):
        profile=await workflow.engine.profile(ProfileRequest(build_id=document.request.base_build_id,skill_instance_ids=ids[start:start+12],limit=12))
        if profile.snapshot_digest!=document.request.base_snapshot_digest: raise WorkflowError('execution_snapshot_mismatch')
        for skill in profile.skill_instances: labels[skill.skill_instance_id]=skill.name
    node_ids: set[int]=set()
    for edit in document.request.edits:
        for field in ['node_ids','allocate_node_ids','refund_node_ids']:
            node_ids.update(getattr(edit,field,[]))
        if edit.type=='instill_amulet': node_ids.add(edit.notable_node_id)
    for start in range(0,len(node_ids),20):
        wanted=sorted(node_ids)[start:start+20]
        offset=0
        while True:
            page=await workflow.engine.static_request('/catalog',CatalogRequest(build_id=document.request.base_build_id,
                entity_type='passive',node_ids=wanted,offset=offset,limit=10),CatalogPage)
            for node in page.passives: labels['node:'+str(node.node_id)]=node.name_ko or node.name
            if page.next_offset is None: break
            offset=page.next_offset
    saved_ids={e.source.saved_item_id for e in document.request.edits if e.type=='equip_item' and e.source.kind=='saved_item'}
    saved_ids.update(h.saved_item_id for h in document.request.temporary_equipment)
    transition=document.audit.equipment_transition
    if transition: saved_ids.update(a.saved_item_id for a in transition.actions if a.saved_item_id is not None)
    for identifier in sorted(saved_ids):
        page=await workflow.engine.inspect(InspectionRequest(build_id=document.request.base_build_id,section='equipment',saved_item_id=identifier,limit=1))
        row=next((r for r in page.records if r.kind=='item'),None)
        if row: labels['item:'+str(identifier)]=row.base_type or row.name or '저장 장비'
    for edit in document.request.edits:
        if edit.type=='equip_item' and edit.source.kind=='retained_trade_listing' and workflow.trade is not None:
            try:
                entry=workflow.trade.retained(edit.source.search_id)
                item=entry['rows'].get(edit.source.listing_ref)
                if item: labels[edit.source.listing_ref]=item.base_type_ko or item.base_type
            except Exception: pass
    support_ids=sorted({identifier for edit in document.request.edits if edit.type=='set_supports' for identifier in edit.support_gem_ids})
    rune_ids=sorted({edit.rune_catalog_id for edit in document.request.edits if edit.type=='socket_rune'})
    typed: list[tuple[Literal['gem','rune'],list[str]]]=[('gem',support_ids),('rune',rune_ids)]
    for kind,identifiers in typed:
        for start in range(0,len(identifiers),10):
            query=CatalogRequest(build_id=document.request.base_build_id,entity_type=kind,catalog_ids=identifiers[start:start+10],limit=10)
            offset=0
            while True:
                query.offset=offset
                page=await workflow.engine.static_request('/catalog',query,CatalogPage)
                for entity in [*page.gems,*page.runes]: labels[entity.catalog_id]=entity.name
                if page.next_offset is None:break
                offset=page.next_offset
    return labels


def edit_text(edit: Any,labels: dict[str,str]) -> tuple[str,list[str]]:
    if edit.type=='set_gem':
        state='' if edit.enabled is None else (' 활성화하세요.' if edit.enabled else ' 비활성화하세요.')
        return f'{labels.get(edit.skill_instance_id,"지정한 젬")}의 기본 레벨을 {edit.native_level}, 퀄리티를 {edit.quality}로 맞추세요.'+state,[edit.skill_instance_id]
    if edit.type=='set_supports':
        names=', '.join(labels.get(identifier,'이름 확인이 필요한 보조') for identifier in edit.support_gem_ids) or '보조 없음'
        return f'{labels.get(edit.skill_instance_id,"지정한 스킬")}의 보조 소켓 {edit.observed_socket_capacity}개를 확인한 뒤 구성하세요: {names}',[edit.skill_instance_id,*edit.support_gem_ids]
    if edit.type in {'allocate_passives','refund_passives','set_ascendancy'}:
        add=getattr(edit,'allocate_node_ids',getattr(edit,'node_ids',[]) if edit.type=='allocate_passives' else [])
        remove=getattr(edit,'refund_node_ids',getattr(edit,'node_ids',[]) if edit.type=='refund_passives' else [])
        parts=[]
        for verb,nodes in [('반환',remove),('할당',add)]:
            if nodes: parts.append(verb+': '+', '.join(labels.get('node:'+str(n),'노드 '+str(n)) for n in nodes))
        return ' / '.join(parts),['node:'+str(n) for n in [*remove,*add]]
    if edit.type=='unequip_item':return SLOTS[edit.slot]+' 슬롯을 비우세요.',[]
    if edit.type=='equip_item':
        key='item:'+str(edit.source.saved_item_id) if edit.source.kind=='saved_item' else edit.source.listing_ref
        return f'{SLOTS[edit.slot]}에 {labels.get(key,"지정한 장비")}를 장착하세요.',[key]
    if edit.type=='socket_rune':return f'{SLOTS[edit.slot]}의 {edit.socket_index+1}번 소켓에 {labels.get(edit.rune_catalog_id,"지정한 룬")}을 넣으세요.',[edit.rune_catalog_id]
    if edit.type=='instill_amulet':return f'목걸이에 {labels.get("node:"+str(edit.notable_node_id),"지정한 주요 노드")}를 주입하세요. 확인된 재료표를 사용하세요.',[edit.recipe_catalog_id]
    raise WorkflowError('execution_edit_unavailable')


async def create(request: ExecutionRequest,workflow: WorkflowService,owner: str) -> ExecutionSummary:
    if request.persist_plan and workflow.store.db is None: raise WorkflowError('workflow_persistence_unconfigured')
    document=workflow.store.get(owner,request.experiment_id)
    evidence,blocked=observations(workflow.store,owner,document,request.observation_ids)
    after=document.calculation.result
    if document.audit.status!='valid_changeset' or after is None: blocked.append('joint_changeset_not_validated')
    if not after or not after.subject or after.subject.status!='matched': blocked.append('calculation_subject_unavailable')
    if not after or after.equipment_validity!='pass': blocked.append('equipment_validity_not_proven')
    if after and after.validation!='pass' and request.comparison_id is None: blocked.append('scoped_joint_goal_review_required')
    if document.audit.transition_validation=='requires_order_validation':blocked.append('actual_transition_order_not_proven')
    if document.state in {'rejected','superseded'}:blocked.append('plan_is_rejected_or_superseded')
    required=set()
    if any(e.type=='instill_amulet' for e in document.request.edits):required.add('amulet_instilling')
    if document.audit.ascendancy_points_delta>0:required.add('ascendancy_trial')
    if any(e.type=='set_supports' and e.socket_capacity_evidence=='planned_upgrade' for e in document.request.edits):required.add('advanced_gem_sockets')
    for unlock in sorted(required):
        unlock_evidence=evidence.get('progression_unlock:'+unlock)
        if not isinstance(unlock_evidence,UnlockObservation):blocked.append('unlock_unknown:'+unlock)
        elif not unlock_evidence.unlocked:blocked.append('unlock_required:'+unlock)
    if request.comparison_id:
        comparison=workflow.store.get_artifact(owner,'purchase_comparison',request.comparison_id,PurchaseComparison)
        member=next((g for g in comparison.request.candidates if request.experiment_id in g.experiment_ids),None)
        chosen=next((c for c in comparison.candidates if member is not None and c.key==member.key),None)
        if chosen is None or not chosen.qualified_in_all_scenarios:blocked.append('complete_purchase_plan_not_qualified')
        if int(time.time())>=comparison.quote_recheck_after_epoch:blocked.append('purchase_quote_recheck_required')
    elif any(e.type=='equip_item' and e.source.kind=='retained_trade_listing' or e.type in {'socket_rune','instill_amulet'}
            or e.type=='set_supports' and e.socket_capacity_evidence=='planned_upgrade' for e in document.request.edits):
        blocked.append('whole_purchase_bill_required')
    notes=risks(document)
    tree_actions=[]
    transition=document.audit.equipment_transition
    indices=([a.edit_index for a in transition.actions if a.edit_index is not None]
        if transition and transition.status=='verified' else list(range(len(document.request.edits))))
    for index in indices:
        edit=document.request.edits[index]
        remove=getattr(edit,'refund_node_ids',getattr(edit,'node_ids',[]) if edit.type=='refund_passives' else [])
        add=getattr(edit,'allocate_node_ids',getattr(edit,'node_ids',[]) if edit.type=='allocate_passives' else [])
        if remove:tree_actions.append(TreeAction(edit_index=index,action='refund',node_ids=remove))
        if add:tree_actions.append(TreeAction(edit_index=index,action='allocate',node_ids=add,allocation_mode=getattr(edit,'allocation_mode',0)))
    tree_order=None
    if tree_actions and not blocked:
        tree_order=await workflow.engine.static_request('/passive-order',PassiveOrderRequest(build_id=document.request.base_build_id,
            tree_revision=document.request.tree_revision,actions=tree_actions),PassiveOrderResult)
        if tree_order.status!='verified':blocked.append('passive_click_order:'+tree_order.status)
    steps: list[ExecutionStep]=[]
    def append(phase: Phase,text: str,edit_index: int | None = None,refs: list[str] | None = None,temporary: bool = False) -> None:
        steps.append(ExecutionStep(index=len(steps),phase=phase,instruction=text,edit_index=edit_index,
            entity_refs=(refs or [])[:128],temporary=temporary,executable_now=not blocked or phase=='prerequisite'))
    if blocked:
        append('prerequisite','진행을 멈추고 미확인 해금·예산·검증 또는 실전 악화 보고를 먼저 해결하세요. 같은 실패 계획을 반복 적용하지 마세요.')
    else:
        labels=await labels_for(workflow,document)
        def append_edit(index: int) -> None:
            edit=document.request.edits[index]
            tree_steps=[action for action in tree_order.actions if action.edit_index==index] if tree_order else []
            if tree_steps:
                for tree_step in tree_steps:
                    for start in range(0,len(tree_step.node_ids),5):
                        batch=tree_step.node_ids[start:start+5]
                        verb='할당' if tree_step.action=='allocate' else '반환'
                        text=verb+' 순서: '+' → '.join(labels.get('node:'+str(n),'노드 '+str(n)) for n in batch)
                        append('apply',text,index,['node:'+str(n) for n in batch])
            else:
                text,refs=edit_text(edit,labels);append('apply',text,index,refs)
        append('prepare','현재 캐릭터와 이 계획의 원본을 대조하세요. 재료와 임시 장비를 준비하고 기존 장비는 보관하세요.')
        transition=document.audit.equipment_transition
        if transition and transition.status=='verified':
            for action in transition.actions:
                if action.action=='apply_edit':
                    if action.edit_index is None:raise WorkflowError('execution_transition_reference_missing')
                    append_edit(action.edit_index)
                    continue
                if action.slot is None:raise WorkflowError('execution_transition_reference_missing')
                if action.action=='unequip':text=SLOTS[action.slot]+' 슬롯을 비우세요.';refs=[]
                elif action.saved_item_id is not None:
                    key='item:'+str(action.saved_item_id);text=f'{SLOTS[action.slot]}에 {labels.get(key,"저장 장비")}를 장착하세요.';refs=[key]
                elif action.edit_index is not None:text,refs=edit_text(document.request.edits[action.edit_index],labels)
                else:raise WorkflowError('execution_transition_reference_missing')
                append('apply',('임시 단계: ' if action.temporary else '')+text,action.edit_index,refs,action.temporary)
        else:
            for index,edit in enumerate(document.request.edits):
                append_edit(index)
        append('play_check','변경한 스킬로 짧게 시험하세요. 의식에서는 반복 피격 중 ES·마나 하강과 공격 중단을 확인하고, 악화되면 다음 단계를 중단하세요.')
        append('record','완료한 단계와 결과를 기록한 뒤 캐릭터를 다시 조회하세요. 제안이나 적용 보고만으로 게임 상태가 확인되지는 않습니다.')
    now=int(time.time())
    value=ExecutionDocument(execution_id='route_'+secrets.token_hex(16),request=request,experiment_revision=document.revision,
        source_artifact_digest=workflow.artifact_digest(document),artifact_digest='0'*64,created_at_epoch=now,
        expires_at_epoch=min(document.expires_at_epoch,now+(30*86400 if request.persist_plan else 3600)),
        blocking_reasons=list(dict.fromkeys(blocked)),risk_notes=notes,steps=steps)
    value.artifact_digest=digest(value.model_dump(mode='json',exclude={'artifact_digest'}))
    workflow.store.save_artifact(owner,'execution_plan',value.execution_id,value,value.expires_at_epoch,request.persist_plan)
    result=ExecutionSummary(execution_id=value.execution_id,experiment_id=request.experiment_id,artifact_digest=value.artifact_digest,
        status='blocked' if blocked else 'ready_for_user_execution',primary_route_count=0 if blocked else 1,next_steps=steps[:3],
        blocking_reasons=value.blocking_reasons,risk_notes=notes,stop_conditions=['요구치 또는 호환성 실패','예산 초과 또는 미확인 해금','반복 피격에서 자원 고갈·사망'],total_steps=len(steps))
    while tool_json_bytes(result)>8192 and len(result.next_steps)>1:result.next_steps.pop()
    return bounded_dto(result)


def page(request: ExecutionPageRequest,store: DecisionStore,owner: str) -> ExecutionPage:
    value=store.get_artifact(owner,'execution_plan',request.execution_id,ExecutionDocument)
    current=store.get(owner,value.request.experiment_id)
    data=value.model_dump(mode='json')
    text=canonical(data if request.section=='exact_json' else data['steps'])
    end=request.offset+request.limit
    return bounded_dto(ExecutionPage(execution_id=value.execution_id,artifact_digest=value.artifact_digest,
        content=text[request.offset:end],total=len(text),next_offset=end if end<len(text) else None,
        source_revision_changed=current.revision!=value.experiment_revision))
