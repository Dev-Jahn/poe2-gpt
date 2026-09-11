"""Build decisions, calculations and user-applied state remain separate."""
from __future__ import annotations
import json
import secrets
import time
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .builds import DTO, bounded_dto
from .capabilities import digest, canonical
from .engine import EngineClient, deltas, calculation_context
from .engine_protocol import WorkerRequest, ExperimentVariantJob, private_trade_item
from .engine_models import EngineCalculation, EngineRequest, EngineSnapshot
from .experiment_models import ExperimentID, ExperimentRequest, ExperimentResult, ExperimentAudit, EquipItem
from .profiles import Digest
from .workflow_store import DecisionDocument, DecisionStore, PlanState, WorkflowError


class PlanPageRequest(DTO):
    experiment_id: ExperimentID
    section: Literal['plan_json','steps','calculation_json','validation'] = 'steps'
    offset: Annotated[int, Field(ge=0, le=1000000)] = 0
    limit: Annotated[int, Field(ge=1, le=1500)] = 1000


class PlanPage(DTO):
    experiment_id: ExperimentID
    revision: int
    state: PlanState
    plan_digest: Digest
    artifact_digest: Digest
    section: Literal['plan_json','steps','calculation_json','validation']
    content: Annotated[str, Field(max_length=5000)]
    next_offset: int | None
    total: int
    saved_base_is_current_character: Literal[False] = False
    source_confirmation: Literal['pending_source_confirmation','confirmed_by_source']
    calculation_replayability: Literal['receipt_available','stored_decision_only']
    persisted: bool


class PlanTransition(DTO):
    experiment_id: ExperimentID
    expected_revision: Annotated[int, Field(ge=1, le=1000000)]
    expected_plan_digest: Digest
    state: Literal['accepted','partially_applied','applied','rejected','superseded']
    applied_edit_indices: Annotated[list[Annotated[int, Field(ge=0, le=31)]], Field(max_length=32)] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_indices(self):
        if len(set(self.applied_edit_indices))!=len(self.applied_edit_indices):
            raise ValueError('duplicate_applied_edit')
        return self


class DeleteDecisionRequest(DTO):
    experiment_id: ExperimentID


class DeletedDecision(DTO):
    status: Literal['deleted_or_unavailable'] = 'deleted_or_unavailable'


class WorkflowService:
    def __init__(self, engine: EngineClient, store: DecisionStore, trade=None):
        self.engine,self.store,self.trade=engine,store,trade

    async def resolve_items(self, request: ExperimentRequest) -> dict[str,dict]:
        if request.persist_decision and self.store.db is None:
            raise WorkflowError('workflow_persistence_unconfigured')
        items={}
        for index,edit in enumerate(request.edits):
            if isinstance(edit,EquipItem) and edit.source.kind=='retained_trade_listing':
                if self.trade is None: raise WorkflowError('trade_not_configured')
                entry=self.trade.retained(edit.source.search_id)
                if edit.source.listing_ref not in entry['ids']: raise WorkflowError('listing_unavailable')
                await self.trade.fetch(entry,[edit.source.listing_ref])
                raw=entry.get('engine_items',{}).get(edit.source.listing_ref)
                if raw is None: raise WorkflowError('listing_unavailable')
                items[str(index+1)]=private_trade_item(raw)
        return items

    async def create(self, owner: str, request: ExperimentRequest) -> ExperimentResult:
        items = await self.resolve_items(request)
        worker=await self.engine.batch(WorkerRequest(build_id=request.base_build_id,
            target=request.target,configuration=request.configuration,combat_scenario=request.combat_scenario,
            experiment=request,experiment_items=items or None))
        if worker.experiment_audit is None: raise WorkflowError('experiment_protocol_mismatch')
        after=worker.results[0] if worker.results else None
        return self.retain_result(owner,request,worker.baseline,after,worker.experiment_audit)

    async def create_variants(self, owner: str, requests: list[ExperimentRequest]) -> list[ExperimentResult]:
        if not 1 <= len(requests) <= 6: raise WorkflowError('variant_limit_exceeded')
        first = requests[0]
        jobs = [ExperimentVariantJob(request=request,items=await self.resolve_items(request)) for request in requests]
        worker = await self.engine.batch(WorkerRequest(build_id=first.base_build_id,target=first.target,
            configuration=first.configuration,combat_scenario=first.combat_scenario,variant_jobs=jobs))
        return [self.retain_result(owner,request,worker.baseline,result.snapshot,result.audit)
            for request,result in zip(requests,worker.experiment_variants,strict=True)]

    def retain_result(self, owner: str, request: ExperimentRequest, baseline: EngineSnapshot,
            after: EngineSnapshot | None, audit: ExperimentAudit) -> ExperimentResult:
        context=EngineRequest(build_id=request.base_build_id,target=request.target,
            configuration=request.configuration,combat_scenario=request.combat_scenario)
        calculation=EngineCalculation(build_id=request.base_build_id,calculated_at_epoch=int(time.time()),
            baseline=baseline,result=after,deltas=deltas(baseline,after) if after else [],
            **calculation_context(context))
        self.engine.receipts.retain(calculation,context)
        assert calculation.calculation_id is not None and calculation.diagnostics_expires_at_epoch is not None
        identifier='exp_'+secrets.token_hex(16)
        plan_hash=digest(request.model_dump(mode='json'))
        now=int(time.time())
        document=DecisionDocument(experiment_id=identifier,request=request,plan_digest=plan_hash,
            audit=audit,calculation=calculation,created_at_epoch=now,
            expires_at_epoch=now+(30*86400 if request.persist_decision else 3600))
        self.store.save(owner,document)
        primary={'Life','Mana','EnergyShield','TotalDPS','CombinedDPS','Str','Dex','Int'}
        select=lambda values:[v for v in values if v.name in primary][:8]
        return bounded_dto(ExperimentResult(experiment_id=identifier,base_build_id=request.base_build_id,
            base_snapshot_digest=request.base_snapshot_digest,plan_digest=plan_hash,edit_count=len(request.edits),
            audit=audit,calculation_id=calculation.calculation_id,
            calculation_expires_at_epoch=calculation.diagnostics_expires_at_epoch,
            baseline_metrics=select(baseline.stats),candidate_metrics=select(after.stats) if after else [],
            deltas=select(calculation.deltas),subject=after.subject if after else baseline.subject,
            candidate_validation=after.validation if after else 'not_evaluated',
            certified=bool(after and after.validation=='pass' and after.subject and after.subject.status=='matched'
                and audit.transition_validation in {'no_equipment_transition','verified'}),
            artifact_digest=self.artifact_digest(document),decision_persisted=request.persist_decision))

    @staticmethod
    def artifact_digest(document: DecisionDocument) -> str:
        # Every representation binds the identical machine-readable plan.
        return digest({'plan':document.request.model_dump(mode='json'),
            'audit':document.audit.model_dump(mode='json'),'calculation':document.calculation.model_dump(mode='json')})

    def page(self, owner: str, request: PlanPageRequest) -> PlanPage:
        document=self.store.get(owner,request.experiment_id)
        if request.section=='plan_json':
            text=canonical(document.request.model_dump(mode='json'))
        elif request.section=='calculation_json':
            text=canonical(document.calculation.model_dump(mode='json'))
        elif request.section=='validation':
            text=canonical(document.audit.model_dump(mode='json'))
        else:
            actions=[]
            labels={'set_gem':'젬 레벨·퀄리티 변경','set_supports':'보조 젬 구성 변경',
                'allocate_passives':'패시브 할당','refund_passives':'패시브 반환','set_ascendancy':'전직 노드 변경',
                'equip_item':'장비 장착','unequip_item':'장비 해제','socket_rune':'룬 장착','instill_amulet':'목걸이 주입'}
            for index,edit in enumerate(document.request.edits):
                fields=edit.model_dump(mode='json');fields.pop('type')
                actions.append(f'{index+1}. {labels[edit.type]} — '+canonical(fields))
            text='\n'.join(['적용 전: 같은 원본과 요구 조건을 확인하세요.',*actions,
                '중단 조건: 요구 능력치·자원·호환성 검증에 실패하면 다음 단계를 진행하지 마세요.',
                '적용 후: 완료한 단계 번호를 기록하고 캐릭터를 다시 조회하세요. 제안만으로 현재 상태를 바꾸지 않습니다.'])
        # UTF-8 byte bounds are enforced separately from character pagination.
        end=request.offset+min(request.limit,1500)
        fragment=text[request.offset:end]
        while len(fragment.encode())>4500:
            end-=1;fragment=text[request.offset:end]
        replay: Literal['receipt_available','stored_decision_only'] = 'receipt_available' if (document.calculation.calculation_id in self.engine.receipts.rows
            and (document.calculation.diagnostics_expires_at_epoch or 0)>int(time.time())) else 'stored_decision_only'
        return bounded_dto(PlanPage(experiment_id=document.experiment_id,revision=document.revision,
            state=document.state,plan_digest=document.plan_digest,artifact_digest=self.artifact_digest(document),
            section=request.section,content=fragment,next_offset=end if end<len(text) else None,total=len(text),
            source_confirmation=document.source_confirmation,calculation_replayability=replay,
            persisted=document.request.persist_decision))

    def transition(self, owner: str, request: PlanTransition) -> PlanPage:
        document=self.store.get(owner,request.experiment_id)
        if document.plan_digest!=request.expected_plan_digest or document.revision!=request.expected_revision:
            raise WorkflowError('plan_revision_conflict')
        allowed={'proposed':{'accepted','rejected','superseded'},
            'accepted':{'partially_applied','applied','rejected','superseded'},
            'partially_applied':{'partially_applied','applied','rejected','superseded'},
            'applied':{'superseded'},'observed':{'superseded'},'rejected':set(),'superseded':set()}
        if request.state not in allowed[document.state]: raise WorkflowError('invalid_plan_transition')
        if request.state=='accepted' and (document.audit.status!='valid_changeset'
                or document.calculation.result is None or document.calculation.result.validation!='pass'):
            raise WorkflowError('plan_validation_required')
        indices=set(request.applied_edit_indices)
        if not indices<=set(range(len(document.request.edits))): raise WorkflowError('invalid_applied_edits')
        if request.state=='applied' and indices!=set(range(len(document.request.edits))):
            raise WorkflowError('applied_requires_all_edits')
        if request.state=='partially_applied' and (not indices or len(indices)==len(document.request.edits)):
            raise WorkflowError('partial_requires_subset')
        if request.state in {'partially_applied','applied'}:
            document.applied_edit_indices=sorted(indices)
        elif indices: raise WorkflowError('state_cannot_apply_edits')
        document.state=request.state;document.revision+=1
        self.store.save(owner,document,expected_revision=request.expected_revision)
        return self.page(owner,PlanPageRequest(experiment_id=document.experiment_id))
