"""Explicit bounded workflow execution, outcome evidence and opt-in telemetry."""
from __future__ import annotations
import asyncio
import json
import secrets
import time
from typing import Annotated, Any, Awaitable, Callable, Literal, Self
from mcp.types import CallToolResult, TextContent
from pydantic import Field, model_validator
from .builds import DTO, bounded_dto
from .capabilities import canonical, digest
from .profiles import ProfileRequest, Digest
from .inspection import InspectionRequest
from .engine_models import EngineRequest, EngineTradeRequest
from .experiment_models import ExperimentRequest
from .trade import TradeSearchRequest, TradePageRequest
from .diagnostics import DiagnosticRequest
from .risk_analysis import RiskRequest
from .workflow_store import DecisionStore, WorkflowError
from .workflow_metrics import CURRENT, Measurements

TraceID = Annotated[str, Field(pattern=r'^wf_[0-9a-f]{32}$')]
Outcome = Literal['qualified_recommendation','no_qualified_recommendation','inspection_available',
    'validated_experiment','calculation_available','diagnostic_available','market_response_only','failed']


class BeginTrace(DTO):
    goal: Literal['inspect_build','evaluate_changes','recommend_purchase','explain_rejection']
    maximum_calls: Annotated[int, Field(ge=1,le=32)] = 12
    maximum_output_bytes: Annotated[int, Field(ge=8192,le=262144)] = 65536
    deadline_seconds: Annotated[int, Field(ge=10,le=1800)] = 600
    step_timeout_seconds: Annotated[int, Field(ge=1,le=90)] = 90
    persist_trace: bool = False


class ProfileStep(DTO):
    tool: Literal['get_build_profile']
    request: ProfileRequest


class InspectStep(DTO):
    tool: Literal['inspect_build']
    request: InspectionRequest


class CalculateStep(DTO):
    tool: Literal['recalculate_build']
    request: EngineRequest


class ExperimentStep(DTO):
    tool: Literal['create_build_experiment']
    request: ExperimentRequest


class SearchStep(DTO):
    tool: Literal['search_trade_equipment']
    request: TradeSearchRequest


class PageStep(DTO):
    tool: Literal['get_trade_search_results']
    request: TradePageRequest


class RecommendStep(DTO):
    tool: Literal['recommend_pob_trade_upgrades']
    request: EngineTradeRequest


class DiagnoseStep(DTO):
    tool: Literal['get_build_diagnostics']
    request: DiagnosticRequest


class RiskStep(DTO):
    tool: Literal['analyze_build_risks']
    request: RiskRequest


Step = Annotated[ProfileStep | InspectStep | CalculateStep | ExperimentStep | SearchStep | PageStep |
    RecommendStep | DiagnoseStep | RiskStep, Field(discriminator='tool')]


class TraceStepRequest(DTO):
    trace_id: TraceID
    step_id: Annotated[str, Field(pattern=r'^[a-z0-9_-]{1,40}$')]
    step: Step


class TraceCall(DTO):
    step_id: str
    tool: str
    input_digest: Digest
    request_bytes: int
    output_bytes: int
    token_estimate: int
    elapsed_ms: float
    phases_ms: dict[str,float]
    phase_counts: dict[str,int]
    is_error: bool
    outcome: Outcome
    error_code: str | None
    result_json: Annotated[str, Field(max_length=16384)]


class TraceDocument(DTO):
    trace_id: TraceID
    revision: int
    request: BeginTrace
    created_at_epoch: int
    deadline_epoch: int
    expires_at_epoch: int
    status: Literal['active','finished','cancelled','budget_exhausted'] = 'active'
    calls: Annotated[list[TraceCall], Field(max_length=32)] = Field(default_factory=list)
    user_reported_goal_completed: bool | None = None
    artifact_digest: Digest


class TraceSummary(DTO):
    trace_id: TraceID
    revision: int
    artifact_digest: Digest
    status: str
    goal: str
    tool_calls: int
    successful_calls: int
    failed_calls: int
    output_bytes: int
    token_estimate: int
    token_estimation_method: Literal['ceil_ascii_json_bytes_divided_by_four_not_billed_tokens'] = 'ceil_ascii_json_bytes_divided_by_four_not_billed_tokens'
    tool_elapsed_ms: float
    wall_elapsed_seconds: int
    phase_totals_ms: dict[str,float]
    phase_counts: dict[str,int]
    unmeasured_phases: list[str]
    phase_timings_can_overlap: Literal[True] = True
    latency_histogram_ms: dict[str,int]
    goal_evidence_available: bool
    user_reported_goal_completed: bool | None
    zero_tool_errors_means_goal_completed: Literal[False] = False
    deadline_epoch: int
    remaining_calls: int
    remaining_output_bytes: int
    next_action: Literal['continue_within_budget','stop_exploration_and_review_evidence','workflow_closed']


class TraceStepResult(DTO):
    trace_id: TraceID
    step_id: str
    artifact_digest: Digest
    is_error: bool
    outcome: str
    result_json_fragment: str
    result_total_characters: int
    next_offset: int | None
    duplicate_reused: bool
    fragment_is_embedded_tool_result: Literal[True] = True


class TraceReference(DTO):
    trace_id: TraceID


class TracePageRequest(TraceReference):
    step_id: Annotated[str, Field(pattern=r'^[a-z0-9_-]{1,40}$')] | None = None
    offset: Annotated[int, Field(ge=0,le=1000000)] = 0
    limit: Annotated[int, Field(ge=1,le=1000)] = 800


class TracePage(DTO):
    trace_id: TraceID
    artifact_digest: Digest
    content: str
    total: int
    next_offset: int | None


class FinishTrace(TraceReference):
    user_reported_goal_completed: bool


def seal(value: TraceDocument) -> None:
    value.artifact_digest=digest(value.model_dump(mode='json',exclude={'artifact_digest'}))


def goal_evidence(value: TraceDocument) -> bool:
    wanted={'inspect_build':'inspection_available','evaluate_changes':'validated_experiment',
        'recommend_purchase':'qualified_recommendation','explain_rejection':'diagnostic_available'}[value.request.goal]
    return any(not c.is_error and c.outcome==wanted for c in value.calls)


def summary(value: TraceDocument) -> TraceSummary:
    phases: dict[str,float]={};counts: dict[str,int]={}
    histogram={'le_100':0,'le_1000':0,'le_10000':0,'gt_10000':0}
    for call in value.calls:
        for key,amount in call.phases_ms.items(): phases[key]=phases.get(key,0.0)+amount
        for key,number in call.phase_counts.items(): counts[key]=counts.get(key,0)+number
        bucket='le_100' if call.elapsed_ms<=100 else 'le_1000' if call.elapsed_ms<=1000 else 'le_10000' if call.elapsed_ms<=10000 else 'gt_10000'
        histogram[bucket]+=1
    output=sum(c.output_bytes for c in value.calls)
    stop=goal_evidence(value) or len(value.calls)>=value.request.maximum_calls or output>=value.request.maximum_output_bytes or int(time.time())>=value.deadline_epoch
    return bounded_dto(TraceSummary(trace_id=value.trace_id,revision=value.revision,artifact_digest=value.artifact_digest,
        status=value.status,goal=value.request.goal,tool_calls=len(value.calls),successful_calls=sum(not c.is_error for c in value.calls),
        failed_calls=sum(c.is_error for c in value.calls),output_bytes=output,token_estimate=sum(c.token_estimate for c in value.calls),
        tool_elapsed_ms=sum(c.elapsed_ms for c in value.calls),wall_elapsed_seconds=max(0,int(time.time())-value.created_at_epoch),
        phase_totals_ms=phases,phase_counts=counts,latency_histogram_ms=histogram,
        unmeasured_phases=[p for p in ['queue','worker_round_trip','worker_execution','worker_cpu','parse','network','rate_wait','validation'] if p not in phases],
        goal_evidence_available=goal_evidence(value),user_reported_goal_completed=value.user_reported_goal_completed,
        deadline_epoch=value.deadline_epoch,remaining_calls=max(0,value.request.maximum_calls-len(value.calls)),
        remaining_output_bytes=max(0,value.request.maximum_output_bytes-output),
        next_action='workflow_closed' if value.status!='active' else 'stop_exploration_and_review_evidence' if stop else 'continue_within_budget'))


def outcome(tool: str, data: dict[str,Any], failed: bool) -> Outcome:
    if failed: return 'failed'
    if tool=='recommend_pob_trade_upgrades':
        # Native recommendation success requires an actual retained winner.
        return 'qualified_recommendation' if data.get('feasible') is True else 'no_qualified_recommendation'
    if tool in {'get_build_profile','inspect_build'}: return 'inspection_available'
    if tool=='create_build_experiment': return 'validated_experiment' if data.get('certified') is True else 'calculation_available'
    if tool in {'get_build_diagnostics','analyze_build_risks'}: return 'diagnostic_available'
    if tool=='recalculate_build': return 'calculation_available'
    return 'market_response_only'


def result_payload(result: Any) -> tuple[dict[str,Any],bool]:
    if isinstance(result,CallToolResult):
        if isinstance(result.structuredContent,dict): return result.structuredContent,bool(result.isError)
        text=' '.join(c.text for c in result.content if isinstance(c,TextContent))
        try: value=json.loads(text)
        except ValueError: value={'code':text}
        return value if isinstance(value,dict) else {'code':'tool_request_failed'},bool(result.isError)
    if isinstance(result,tuple) and len(result)==2 and isinstance(result[1],dict): return result[1],False
    raise WorkflowError('workflow_result_contract_unavailable')


class WorkflowTelemetry:
    def __init__(self, store: DecisionStore) -> None:
        self.store=store
        self.running: dict[tuple[str,str],asyncio.Task[Any]]={}

    def get(self, owner: str, identifier: str) -> TraceDocument:
        return self.store.get_artifact(owner,'workflow_trace',identifier,TraceDocument)

    def save(self, owner: str, value: TraceDocument) -> None:
        old=value.revision;value.revision+=1;seal(value)
        self.store.update_mutable_artifact(owner,'workflow_trace',value.trace_id,value,old)

    def begin(self, owner: str, request: BeginTrace) -> TraceSummary:
        now=int(time.time())
        value=TraceDocument(trace_id='wf_'+secrets.token_hex(16),revision=1,request=request,created_at_epoch=now,
            deadline_epoch=now+request.deadline_seconds,expires_at_epoch=now+(30*86400 if request.persist_trace else 3600),artifact_digest='0'*64)
        seal(value)
        self.store.save_artifact(owner,'workflow_trace',value.trace_id,value,value.expires_at_epoch,request.persist_trace)
        return summary(value)

    async def run(self, owner: str, request: TraceStepRequest,
            invoke: Callable[[str,dict[str,Any]],Awaitable[Any]]) -> TraceStepResult:
        value=self.get(owner,request.trace_id)
        key=(owner,request.trace_id)
        input_digest=digest(request.step.model_dump(mode='json'))
        existing=next((c for c in value.calls if c.step_id==request.step_id),None)
        if existing:
            if existing.input_digest!=input_digest: raise WorkflowError('workflow_step_id_conflict')
            return self.step_result(value,existing,True)
        if key in self.running: raise WorkflowError('workflow_busy_retry_after_one_second')
        if value.status!='active': raise WorkflowError('workflow_closed')
        if goal_evidence(value): raise WorkflowError('workflow_goal_evidence_available_stop_exploration')
        if (len(value.calls)>=value.request.maximum_calls or int(time.time())>=value.deadline_epoch
                or sum(c.output_bytes for c in value.calls)+8192>value.request.maximum_output_bytes):
            value.status='budget_exhausted';self.save(owner,value)
            raise WorkflowError('workflow_budget_exhausted_review_retained_evidence')
        if sum(c.input_digest==input_digest and c.is_error for c in value.calls)>=2:
            raise WorkflowError('workflow_identical_failure_retry_limit')
        if any(c.input_digest==input_digest and not c.is_error for c in value.calls):
            raise WorkflowError('workflow_duplicate_success_use_retained_step')
        task=asyncio.current_task()
        if task is None: raise WorkflowError('workflow_task_unavailable')
        self.running[key]=task
        measured=Measurements();token=CURRENT.set(measured)
        start=time.monotonic()
        failed=False
        try:
            timeout=min(value.request.step_timeout_seconds,max(0.01,value.deadline_epoch-time.time()))
            async with asyncio.timeout(timeout):
                result=await invoke(request.step.tool,{'request':request.step.request.model_dump(mode='json',exclude_none=True)})
            data,failed=result_payload(result)
        except asyncio.CancelledError:
            data={'code':'workflow_cancelled','cancellation_scope':'mcp_request_private_worker_has_independent_bounded_timeout'};failed=True
            value.status='cancelled'
        except TimeoutError:
            data={'code':'workflow_step_deadline_exceeded','next_action':'review_retained_evidence_then_retry_once'};failed=True
        except Exception:
            data={'code':'workflow_step_failed','next_action':'review_tool_schema_and_trace'};failed=True
        finally:
            CURRENT.reset(token);self.running.pop(key,None)
        text=canonical(data)
        if len(text.encode())>8192:
            # Inner tools must uphold their own lossless-page contract.
            text=canonical({'code':'workflow_inner_result_too_large'});failed=True
        request_bytes=len(canonical(request.step.model_dump(mode='json')).encode())
        call=TraceCall(step_id=request.step_id,tool=request.step.tool,input_digest=input_digest,request_bytes=request_bytes,
            output_bytes=len(text.encode()),token_estimate=(request_bytes+len(text.encode())+3)//4,elapsed_ms=(time.monotonic()-start)*1000,
            phases_ms=measured.milliseconds,phase_counts=dict(measured.counts),is_error=failed,
            outcome=outcome(request.step.tool,data,failed),error_code=data.get('code') if failed else None,result_json=text)
        value.calls.append(call);self.save(owner,value)
        return self.step_result(value,call,False)

    def step_result(self, value: TraceDocument, call: TraceCall, duplicate: bool) -> TraceStepResult:
        return bounded_dto(TraceStepResult(trace_id=value.trace_id,step_id=call.step_id,artifact_digest=value.artifact_digest,
            is_error=call.is_error,outcome=call.outcome,result_json_fragment=call.result_json[:1000],
            result_total_characters=len(call.result_json),next_offset=1000 if len(call.result_json)>1000 else None,duplicate_reused=duplicate))

    def page(self, owner: str, request: TracePageRequest) -> TracePage:
        value=self.get(owner,request.trace_id)
        if request.step_id is not None:
            call=next((c for c in value.calls if c.step_id==request.step_id),None)
            if call is None: raise WorkflowError('workflow_step_unavailable')
            text=call.result_json
        else: text=canonical(value.model_dump(mode='json'))
        end=request.offset+request.limit
        return bounded_dto(TracePage(trace_id=value.trace_id,artifact_digest=value.artifact_digest,content=text[request.offset:end],
            total=len(text),next_offset=end if end<len(text) else None))

    def finish(self, owner: str, request: FinishTrace) -> TraceSummary:
        value=self.get(owner,request.trace_id)
        if (owner,request.trace_id) in self.running: raise WorkflowError('workflow_busy_retry_after_one_second')
        if value.status=='active': value.status='finished'
        value.user_reported_goal_completed=request.user_reported_goal_completed
        self.save(owner,value)
        return summary(value)

    async def cancel(self, owner: str, identifier: str) -> TraceSummary:
        value=self.get(owner,identifier)
        if task:=self.running.get((owner,identifier)):
            task.cancel()
            # Cancellation joins the current bounded step, never creates a job.
            try: await task
            except asyncio.CancelledError: pass
            value=self.get(owner,identifier)
        elif value.status=='active':
            value.status='cancelled';self.save(owner,value)
        return summary(value)
