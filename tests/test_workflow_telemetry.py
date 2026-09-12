"""Task budgets and completion evidence are distinct from tool success."""
import asyncio
import json
import time
from types import SimpleNamespace
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult,TextContent
from jsonschema import Draft202012Validator
from poe2_companion.workflow_telemetry import (WorkflowTelemetry,BeginTrace,TraceStepRequest,FinishTrace,
    TracePageRequest,summary,outcome)
from poe2_companion.workflow_store import DecisionStore,WorkflowError
from poe2_companion.workflow_metrics import span,count
from poe2_companion.server import build_server
from poe2_companion.inspection import InspectionPage
from test_scout import client


def search_step(trace,identifier='s1'):
    return TraceStepRequest(trace_id=trace,step_id=identifier,step={'tool':'search_trade_equipment',
        'request':{'league':'Forbidden Rites','category':'accessory.ring'}})


async def test_zero_errors_does_not_complete_goal_and_duplicate_success_does_not_execute(tmp_path,monkeypatch):
    clock=[time.time()]
    monkeypatch.setattr('poe2_companion.workflow_telemetry.time.time',lambda:clock[0])
    store=DecisionStore('m',tmp_path/'state',tmp_path/'keys'/'key')
    telemetry=WorkflowTelemetry(store)
    started=telemetry.begin('alice',BeginTrace(goal='recommend_purchase',persist_trace=True))
    calls=[]
    async def invoke(tool,args):
        calls.append((tool,args))
        with span('network'): count('upstream_request')
        return [],{'items':[],'all_unknown':True}
    request=search_step(started.trace_id)
    first=await telemetry.run('alice',request,invoke)
    second=await telemetry.run('alice',request,invoke)
    assert len(calls)==1 and second.duplicate_reused and first.outcome=='market_response_only'
    status=summary(telemetry.get('alice',started.trace_id))
    assert status.successful_calls==1 and status.failed_calls==0 and not status.goal_evidence_available
    assert status.phase_counts['upstream_request']==1 and 'worker_cpu' in status.unmeasured_phases
    assert not status.zero_tool_errors_means_goal_completed
    assert outcome('recommend_pob_trade_upgrades',{'feasible':False},False)=='no_qualified_recommendation'
    assert outcome('recommend_pob_trade_upgrades',{'feasible':True},False)=='qualified_recommendation'
    finished=telemetry.finish('alice',FinishTrace(trace_id=started.trace_id,user_reported_goal_completed=True))
    assert finished.user_reported_goal_completed and not finished.goal_evidence_available
    receipt=telemetry.get('alice',started.trace_id)
    clock[0]+=10
    store.close();store=DecisionStore('m',tmp_path/'state',tmp_path/'keys'/'key');telemetry=WorkflowTelemetry(store)
    assert telemetry.finish('alice',FinishTrace(trace_id=started.trace_id,user_reported_goal_completed=True))==finished
    assert telemetry.get('alice',started.trace_id)==receipt
    assert finished.wall_elapsed_seconds==0
    corrected=telemetry.finish('alice',FinishTrace(trace_id=started.trace_id,user_reported_goal_completed=False))
    assert not corrected.user_reported_goal_completed and corrected.artifact_digest!=finished.artifact_digest
    assert telemetry.finish('alice',FinishTrace(trace_id=started.trace_id,user_reported_goal_completed=False))==corrected
    piece=telemetry.page('alice',TracePageRequest(trace_id=started.trace_id,step_id='s1'))
    assert json.loads(piece.content)=={'items':[],'all_unknown':True}
    with pytest.raises(WorkflowError): telemetry.get('bob',started.trace_id)
    store.close()


async def test_all_closed_trace_durations_stop_and_legacy_closed_time_stays_unknown(monkeypatch):
    from poe2_companion.capabilities import canonical,digest
    clock=[time.time()]
    monkeypatch.setattr('poe2_companion.workflow_telemetry.time.time',lambda:clock[0])
    store=DecisionStore('m');telemetry=WorkflowTelemetry(store)
    active=telemetry.begin('alice',BeginTrace(goal='inspect_build',maximum_calls=1))
    clock[0]+=5
    assert summary(telemetry.get('alice',active.trace_id)).wall_elapsed_seconds==5
    cancelled=await telemetry.cancel('alice',active.trace_id)
    budget=telemetry.begin('alice',BeginTrace(goal='recommend_purchase',maximum_calls=1))
    async def invoke(tool,args):return [],{'items':[]}
    await telemetry.run('alice',search_step(budget.trace_id),invoke)
    with pytest.raises(WorkflowError,match='budget_exhausted'):
        await telemetry.run('alice',search_step(budget.trace_id,'s2'),invoke)
    exhausted=summary(telemetry.get('alice',budget.trace_id))
    clock[0]+=10
    assert summary(telemetry.get('alice',active.trace_id))==cancelled
    assert summary(telemetry.get('alice',budget.trace_id))==exhausted
    key=(store.owner_key('alice'),'workflow_trace',active.trace_id)
    expires,payload=store.artifacts[key]
    legacy=json.loads(payload);legacy.pop('closed_at_epoch')
    legacy['user_reported_goal_completed']=False
    legacy['artifact_digest']=digest({k:v for k,v in legacy.items() if k!='artifact_digest'})
    store.artifacts[key]=(expires,canonical(legacy).encode())
    finish=FinishTrace(trace_id=active.trace_id,user_reported_goal_completed=False)
    first=telemetry.finish('alice',finish)
    assert first.wall_elapsed_seconds is None
    clock[0]+=10
    assert telemetry.finish('alice',finish)==first
    fragments=[];query=TracePageRequest(trace_id=active.trace_id)
    while True:
        part=telemetry.page('alice',query);fragments.append(part.content)
        if part.next_offset is None:break
        query.offset=part.next_offset
    assert ''.join(fragments)==canonical(legacy)


async def test_bounded_identical_retry_admission_cancellation_and_deadline():
    telemetry=WorkflowTelemetry(DecisionStore('m'))
    started=telemetry.begin('alice',BeginTrace(goal='recommend_purchase'))
    calls=0
    async def failed(tool,args):
        nonlocal calls
        calls+=1
        return CallToolResult(isError=True,content=[TextContent(type='text',text=json.dumps({'code':'engine_busy','retry_after_seconds':1}))])
    for i in range(2):
        assert (await telemetry.run('alice',search_step(started.trace_id,f's{i}'),failed)).is_error
    with pytest.raises(WorkflowError,match='identical_failure_retry_limit'):
        await telemetry.run('alice',search_step(started.trace_id,'s3'),failed)
    assert calls==2
    waiting=asyncio.Event();release=asyncio.Event()
    async def blocked(tool,args):
        waiting.set();await release.wait()
        return [],{'items':[]}
    other=telemetry.begin('alice',BeginTrace(goal='recommend_purchase'))
    task=asyncio.create_task(telemetry.run('alice',search_step(other.trace_id),blocked))
    await waiting.wait()
    with pytest.raises(WorkflowError,match='workflow_busy'):
        await telemetry.run('alice',search_step(other.trace_id,'s2'),blocked)
    cancelled=await telemetry.cancel('alice',other.trace_id)
    assert cancelled.status=='cancelled' and cancelled.failed_calls==1 and task.done()
    closed=telemetry.finish('alice',FinishTrace(trace_id=other.trace_id,user_reported_goal_completed=False))
    assert closed.status=='cancelled' and not closed.user_reported_goal_completed
    assert telemetry.finish('alice',FinishTrace(trace_id=other.trace_id,user_reported_goal_completed=False))==closed
    deadline=telemetry.begin('alice',BeginTrace(goal='recommend_purchase',step_timeout_seconds=1))
    timed=await telemetry.run('alice',search_step(deadline.trace_id),blocked)
    assert timed.is_error and 'workflow_step_deadline_exceeded' in timed.result_json_fragment
    budget=telemetry.begin('alice',BeginTrace(goal='recommend_purchase',maximum_calls=1))
    await telemetry.run('alice',search_step(budget.trace_id),failed)
    with pytest.raises(WorkflowError,match='budget_exhausted'):
        await telemetry.run('alice',search_step(budget.trace_id,'s2'),failed)


async def test_actual_mcp_trace_wraps_empty_inspection_without_schema_loss(client):
    scout,_,_=client
    async def inspect(request):
        return InspectionPage(build_id=request.build_id,section=request.section,records=[],total=0)
    server=build_server(scout,engine=SimpleNamespace(inspect=inspect))
    async with create_connected_server_and_client_session(server) as session:
        tools={t.name:t for t in (await session.list_tools()).tools}
        first=await session.call_tool('begin_workflow_trace',{'request':{'goal':'inspect_build'}})
        assert not first.isError
        trace=first.structuredContent['trace_id']
        step=await session.call_tool('run_workflow_step',{'request':{'trace_id':trace,'step_id':'inspect',
            'step':{'tool':'inspect_build','request':{'build_id':'bld_'+'1'*32,'section':'equipment'}}}})
        assert not step.isError and not step.structuredContent['is_error']
        Draft202012Validator(tools['run_workflow_step'].outputSchema).validate(step.structuredContent)
        inner=json.loads(step.structuredContent['result_json_fragment'])
        assert inner['records']==[]
        Draft202012Validator(tools['inspect_build'].outputSchema).validate(inner)
        status=await session.call_tool('get_workflow_trace',{'request':{'trace_id':trace}})
        assert status.structuredContent['goal_evidence_available']
        assert status.structuredContent['next_action']=='stop_exploration_and_review_evidence'


async def test_runtime_pages_all_tool_counters_and_errors_within_mcp_wire_limit(client):
    from poe2_companion.observability import ToolCounters,ErrorTrace
    scout,_,_=client
    server=build_server(scout)
    for i in range(100):
        name=f'tool_{i:03d}_'+'x'*71
        server.counters[name]=ToolCounters(tool=name,calls=10**12,elapsed_ms=1e12,max_elapsed_ms=1e9)
    for i in range(16):
        server.error_traces.append(ErrorTrace(trace_id=f'{i:024x}',tool='x'*80,code='e'*100,
            category='operator_action',occurred_at_epoch=1800000000+i))
    async with create_connected_server_and_client_session(server) as session:
        schema=next(t.outputSchema for t in (await session.list_tools()).tools if t.name=='get_tool_runtime_status')
        names=[];errors=[];offset=0
        while True:
            response=await session.call_tool('get_tool_runtime_status',{'offset':offset,'limit':32})
            assert not response.isError
            page=response.structuredContent
            Draft202012Validator(schema).validate(page)
            assert len(json.dumps(page,allow_nan=False).encode())<=8192
            names.extend(row['tool'] for row in page['tools']);errors.extend(row['trace_id'] for row in page['recent_errors'])
            if page['next_offset'] is None:break
            assert page['next_offset']>offset;offset=page['next_offset']
        assert len(names)==101 and len(set(names))==101
        assert errors==[f'{i:024x}' for i in range(16)]
        empty=await session.call_tool('get_tool_runtime_status',{'offset':128})
        assert not empty.isError and empty.structuredContent['tools']==[] and empty.structuredContent['recent_errors']==[]
