"""Handoff 001/025: actual MCP discovery and lossless nested contracts."""
import json
import pytest
from jsonschema import Draft202012Validator
from mcp.shared.memory import create_connected_server_and_client_session
from poe2_companion.server import build_server
from poe2_companion.scout import Scout
from test_scout import Backend
import httpx


async def test_mcp_inventory_distinguishes_configuration_from_host_and_schema():
    scout=Scout(user_agent='test',transport=httpx.MockTransport(Backend()),interval=0)
    server=build_server(scout)
    try:
        async with create_connected_server_and_client_session(server) as session:
            listed=(await session.list_tools()).tools
            schemas={tool.name:tool for tool in listed}
            result=await session.call_tool('get_capabilities',{'request':{}})
            assert not result.isError
            data=result.structuredContent
            Draft202012Validator(schemas['get_capabilities'].outputSchema).validate(data)
            assert data['host_inventory_status']=='unknown'
            assert data['configured_tool_count']==len(listed)
            assert any(f['name']=='private_engine' and f['disable_reason']=='not_configured' for f in data['features'])
            mismatch=await session.call_tool('get_capabilities',{'request':{'host_tool_names':['get_capabilities']}})
            assert mismatch.structuredContent['host_inventory_status']=='differs_from_reported_inventory'
            fragments=[]; offset=0
            while True:
                page=await session.call_tool('describe_tool_schema',{'request':{
                    'tool_name':'get_capabilities','direction':'output','offset':offset,'limit':1800}})
                assert not page.isError
                Draft202012Validator(schemas['describe_tool_schema'].outputSchema).validate(page.structuredContent)
                fragments.append(page.structuredContent['schema_json_fragment'])
                offset=page.structuredContent['next_offset']
                if offset is None: break
            reconstructed=json.loads(''.join(fragments))
            assert reconstructed==schemas['get_capabilities'].outputSchema
            assert '$defs' in reconstructed
            bad=await session.call_tool('describe_tool_schema',{'request':{'tool_name':'not_configured'}})
            assert bad.isError
    finally:
        await scout.close()
