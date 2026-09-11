"""Minimal changed-field restoration to an explicitly reported successful plan."""
from __future__ import annotations
import secrets
import time
from typing import Annotated,Literal,Any
from pydantic import Field
from .builds import DTO,bounded_dto
from .capabilities import canonical,digest
from .experiment_models import ExperimentID
from .observations import ResourceObservation
from .workflow_store import DecisionStore,DecisionDocument,WorkflowError
from .execution_plans import risks

RollbackID=Annotated[str,Field(pattern=r'^rollback_[0-9a-f]{32}$')]


class RollbackRequest(DTO):
    failed_experiment_id: ExperimentID
    last_successful_experiment_id: ExperimentID
    persist_plan: bool = False


class RestoreField(DTO):
    entity_ref: str
    current_reported_value_json: str
    desired_value_json: str | None
    restore_from_original_snapshot: bool
    may_require_new_consumables: bool


class RollbackDocument(DTO):
    rollback_id: RollbackID
    request: RollbackRequest
    source_snapshot_digest: str
    failed_revision: int
    successful_revision: int
    failure_observation_ids: list[str]
    successful_observation_ids: list[str]
    changes: Annotated[list[RestoreField],Field(max_length=4096)]
    risk_notes: list[str]
    risk_notes_scope: Literal['planned_joint_endpoint_not_live_partial_state'] = 'planned_joint_endpoint_not_live_partial_state'
    artifact_digest: str
    created_at_epoch: int
    expires_at_epoch: int
    current_game_state_verified: Literal[False] = False
    rollback_transition_verified: Literal[False] = False
    causal_effect_proven_by_user_reports: Literal[False] = False


class RollbackSummary(DTO):
    rollback_id: RollbackID
    failed_experiment_id: ExperimentID
    last_successful_experiment_id: ExperimentID
    artifact_digest: str
    changed_target_fields: int
    original_state_inspection_required_count: int
    consumable_replacement_may_be_required: bool
    minimum_scope: Literal['different_target_fields_between_reported_applied_plans'] = 'different_target_fields_between_reported_applied_plans'
    globally_cheapest_equip_sequence_proven: Literal[False] = False
    rollback_transition_verified: Literal[False] = False
    risk_notes: list[str]
    risk_notes_scope: Literal['planned_joint_endpoint_not_live_partial_state'] = 'planned_joint_endpoint_not_live_partial_state'
    next_steps: list[str]
    repeat_failed_plan: Literal[False] = False


class RollbackPageRequest(DTO):
    rollback_id: RollbackID
    section: Literal['changes','exact_json'] = 'changes'
    offset: Annotated[int,Field(ge=0,le=1000000)] = 0
    limit: Annotated[int,Field(ge=1,le=1000)] = 800


class RollbackPage(DTO):
    rollback_id: RollbackID
    artifact_digest: str
    content: str
    total: int
    next_offset: int | None
    source_revision_changed: bool


class RollbackReference(DTO):
    rollback_id: RollbackID


def fields(document: DecisionDocument) -> dict[str,Any]:
    if document.state not in {'applied','partially_applied','observed'}:
        raise WorkflowError('rollback_requires_reported_applied_plan')
    result: dict[str,Any]={}
    for index in document.applied_edit_indices:
        edit=document.request.edits[index]
        if edit.type=='set_gem':result['gem:'+edit.skill_instance_id]={'native_level':edit.native_level,'quality':edit.quality}
        elif edit.type=='set_supports':result['supports:'+edit.skill_instance_id.rsplit(':n',1)[0]]=sorted(edit.support_gem_ids)
        elif edit.type=='equip_item':result['equipment:'+edit.slot]=edit.source.model_dump(mode='json')
        elif edit.type=='unequip_item':result['equipment:'+edit.slot]=None
        elif edit.type=='socket_rune':result[f'rune:{edit.slot}:{edit.socket_index}']=edit.rune_catalog_id
        elif edit.type=='instill_amulet':result['instill:amulet']={'notable_node_id':edit.notable_node_id,'recipe_catalog_id':edit.recipe_catalog_id}
        else:
            remove=getattr(edit,'refund_node_ids',getattr(edit,'node_ids',[]) if edit.type=='refund_passives' else [])
            add=getattr(edit,'allocate_node_ids',getattr(edit,'node_ids',[]) if edit.type=='allocate_passives' else [])
            choices={c.node_id:c.attribute for c in getattr(edit,'attribute_choices',[])}
            prefix='ascendancy:' if edit.type=='set_ascendancy' else 'passive:'
            for identifier in remove:result[prefix+str(identifier)]={'allocated':False}
            for identifier in add:result[prefix+str(identifier)]={'allocated':True,'allocation_mode':getattr(edit,'allocation_mode',0),'attribute_choice':choices.get(identifier)}
    return result


def resource_reports(store: DecisionStore,owner: str,document: DecisionDocument,successful: bool) -> list[tuple[str,ResourceObservation,int]]:
    records=[]
    for identifier in document.observation_ids:
        row=store.get_observation(owner,identifier)
        if row.request.related_experiment_id!=document.experiment_id:continue
        for value in row.request.values:
            if isinstance(value,ResourceObservation) and (value.outcome=='stable' and value.minimum_during_encounter>0 if successful else value.outcome in {'depleted','died'}):
                records.append((identifier,value,row.request.observed_at_epoch))
    return records


def create(request: RollbackRequest,store: DecisionStore,owner: str) -> RollbackSummary:
    if request.persist_plan and store.db is None:raise WorkflowError('workflow_persistence_unconfigured')
    failed=store.get(owner,request.failed_experiment_id);previous=store.get(owner,request.last_successful_experiment_id)
    if failed.experiment_id==previous.experiment_id:raise WorkflowError('rollback_requires_distinct_plans')
    if (failed.request.base_build_id,failed.request.base_snapshot_digest)!=(previous.request.base_build_id,previous.request.base_snapshot_digest):
        raise WorkflowError('rollback_origin_revision_mismatch')
    if failed.request.target!=previous.request.target:raise WorkflowError('rollback_subject_mismatch')
    a,b=fields(failed),fields(previous)
    failures=resource_reports(store,owner,failed,False);successes=resource_reports(store,owner,previous,True)
    paired=[(f,s) for f in failures for s in successes if f[1].resource==s[1].resource and f[1].encounter==s[1].encounter and s[2]<=f[2]]
    if not paired:raise WorkflowError('rollback_requires_matching_success_and_failure_observations')
    # An unchanged field is never included merely because it is in a plan.
    # Missing desired fields refer back to the shared immutable original.
    changes=[]
    for key in sorted(a.keys() | b.keys()):
        if key in a and key in b and a[key]==b[key]:continue
        changes.append(RestoreField(entity_ref=key,current_reported_value_json=canonical(a[key]) if key in a else canonical({'source':'original_snapshot'}),
            desired_value_json=canonical(b[key]) if key in b else None,restore_from_original_snapshot=key not in b,
            may_require_new_consumables=key.startswith(('rune:','instill:'))))
    if not changes:raise WorkflowError('rollback_no_changed_fields_check_encounter_assumptions')
    now=int(time.time())
    value=RollbackDocument(rollback_id='rollback_'+secrets.token_hex(16),request=request,source_snapshot_digest=failed.request.base_snapshot_digest,
        failed_revision=failed.revision,successful_revision=previous.revision,failure_observation_ids=sorted({f[0] for f,s in paired}),
        successful_observation_ids=sorted({s[0] for f,s in paired}),changes=changes,risk_notes=risks(failed),artifact_digest='0'*64,
        created_at_epoch=now,expires_at_epoch=min(failed.expires_at_epoch,previous.expires_at_epoch,now+(30*86400 if request.persist_plan else 3600)))
    value.artifact_digest=digest(value.model_dump(mode='json',exclude={'artifact_digest'}))
    store.save_artifact(owner,'rollback_plan',value.rollback_id,value,value.expires_at_epoch,request.persist_plan)
    return bounded_dto(RollbackSummary(rollback_id=value.rollback_id,failed_experiment_id=failed.experiment_id,
        last_successful_experiment_id=previous.experiment_id,artifact_digest=value.artifact_digest,changed_target_fields=len(changes),
        original_state_inspection_required_count=sum(c.restore_from_original_snapshot for c in changes),
        consumable_replacement_may_be_required=any(c.may_require_new_consumables for c in changes),risk_notes=value.risk_notes,
        next_steps=['실패한 구성을 반복 적용하지 말고 현재 캐릭터를 다시 조회하세요.',
            '차이가 있는 항목만 이전 성공 상태로 되돌리는 변경안을 현재 스냅샷에서 함께 계산하세요. 기존 성공 기록은 현재 장착 순서의 증명이 아닙니다.',
            '요구치·장착 순서·소모 재료를 확인한 뒤 짧은 동일 조건 실험으로 회복 여부를 기록하세요.']))


def page(request: RollbackPageRequest,store: DecisionStore,owner: str) -> RollbackPage:
    value=store.get_artifact(owner,'rollback_plan',request.rollback_id,RollbackDocument)
    failed=store.get(owner,value.request.failed_experiment_id);previous=store.get(owner,value.request.last_successful_experiment_id)
    data=value.model_dump(mode='json');text=canonical(data if request.section=='exact_json' else data['changes'])
    end=request.offset+request.limit
    return bounded_dto(RollbackPage(rollback_id=value.rollback_id,artifact_digest=value.artifact_digest,content=text[request.offset:end],
        total=len(text),next_offset=end if end<len(text) else None,
        source_revision_changed=failed.revision!=value.failed_revision or previous.revision!=value.successful_revision))
