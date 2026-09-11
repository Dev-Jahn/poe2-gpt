"""Configured-tool examples and partial projections over actual MCP sessions."""
import json
from types import SimpleNamespace
import httpx
from jsonschema import Draft202012Validator
from mcp.shared.memory import create_connected_server_and_client_session
from poe2_companion.server import build_server
from poe2_companion.capabilities import tool_examples
from poe2_companion.builds import BuildReader
from poe2_companion.engine_models import EngineError
from poe2_companion.scout import Scout
from test_scout import Backend
from test_build_boundary import imported,MARKER


async def test_every_configured_tool_has_a_valid_nested_example_and_bounded_inventory():
    stub=SimpleNamespace()
    server=build_server(stub,build_reader=stub,equipment=stub,trade=stub,engine=stub,characters=stub,accounts=stub)
    examples=tool_examples()
    async with create_connected_server_and_client_session(server) as session:
        tools={t.name:t for t in (await session.list_tools()).tools}
        assert set(tools)==set(examples)
        for name,t in tools.items():
            Draft202012Validator.check_schema(t.inputSchema)
            Draft202012Validator.check_schema(t.outputSchema)
            page=await session.call_tool('describe_tool_schema',{'request':{'tool_name':name}})
            assert not page.isError,name
            Draft202012Validator(tools['describe_tool_schema'].outputSchema).validate(page.structuredContent)
            assert len(json.dumps(page.structuredContent,allow_nan=False).encode())<=8192
            value=json.loads(page.structuredContent['example_arguments_json'])
            Draft202012Validator(t.inputSchema).validate(value)
            server._tool_manager._tools[name].fn_metadata.arg_model.model_validate(value)
        offset=0;found=[];missing=[]
        while True:
            page=await session.call_tool('get_capabilities',{'request':{'host_tool_names':[],'offset':offset,'limit':40}})
            assert not page.isError
            assert len(json.dumps(page.structuredContent,allow_nan=False).encode())<=8192
            found+=page.structuredContent['configured_tools'];missing+=page.structuredContent['missing_from_reported_host']
            offset=page.structuredContent['next_offset']
            if offset is None:break
        assert found==missing==sorted(tools)
        assert len(found)==len(set(found))


async def test_disabled_and_busy_engine_retain_saved_projection_without_derived_claims(tmp_path):
    bid,_,projections,_=imported(tmp_path)
    scout=Scout(user_agent='test',transport=httpx.MockTransport(Backend()),interval=0)
    async def busy(request):raise EngineError('engine_busy')
    try:
        for engine,reason in [(None,'not_configured'),(SimpleNamespace(profile=busy),'engine_busy')]:
            server=build_server(scout,build_reader=BuildReader(projections),engine=engine)
            async with create_connected_server_and_client_session(server) as session:
                schemas={t.name:t for t in (await session.list_tools()).tools}
                page=await session.call_tool('get_build_profile',{'request':{'build_id':bid}})
                assert not page.isError
                Draft202012Validator(schemas['get_build_profile'].outputSchema).validate(page.structuredContent)
                data=page.structuredContent['result']
                assert data['native_unavailable_reason']==reason and data['level']==91
                assert data['counts']['saved_gems']==1
                assert not data['calculated_metrics_available'] and 'stats' not in data
                assert data['equipment'] is None and 'equipment_projection' in data['unavailable']
                assert MARKER not in json.dumps(data) and not data['raw_payload_exposed']
    finally:await scout.close()
