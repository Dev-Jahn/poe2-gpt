import json
import httpx
from mcp.shared.memory import create_connected_server_and_client_session
from poe2_companion.scout import Scout
from poe2_companion.trade import TradeClient
from poe2_companion.engine import EngineClient
from poe2_companion.server import build_server
from test_scout import Backend


async def test_safe_error_trace_and_blocked_readiness_are_recoverable():
    scout=Scout(user_agent='test',transport=httpx.MockTransport(Backend()),interval=0)
    trade=TradeClient('test');engine=EngineClient('/unused')
    server=build_server(scout,trade=trade,engine=engine)
    try:
        async with create_connected_server_and_client_session(server) as session:
            response=await session.call_tool('recalculate_build',{'request':{'build_id':'bld_'+'1'*32,'configuration':{'refutation_active':True}}})
            failure=json.loads(response.content[0].text)
            assert failure['code']=='incomplete_configuration' and failure['category']=='arguments'
            assert failure['missing_fields']==['configuration.refutation_ward_spent']
            trade.blocked='trade_challenge_required'
            response=await session.call_tool('get_trade_integration_status',{})
            assert response.structuredContent['request_state']=='operator_action_required'
            trade.blocked=None;trade.gate.until=trade.gate.clock()+30
            response=await session.call_tool('get_trade_integration_status',{})
            assert response.structuredContent['request_state']=='cooldown'
            assert 1<=response.structuredContent['retry_after_seconds']<=30
            response=await session.call_tool('get_tool_runtime_status',{})
            row=response.structuredContent
            assert row['recent_errors'][0]['trace_id']==failure['trace_id']
            counter=next(c for c in row['tools'] if c['tool']=='recalculate_build')
            assert counter['calls']==counter['errors']==1 and counter['elapsed_ms']>0
            assert 'bld_' not in json.dumps(row)
    finally:
        await scout.close();await trade.close();await engine.close()
