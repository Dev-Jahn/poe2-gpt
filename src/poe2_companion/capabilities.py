"""Runtime inventory and lossless nested schema discovery, not host guesswork."""
from __future__ import annotations
import hashlib
import json
from typing import Annotated, Literal
from pydantic import Field
from . import __version__
from .builds import DTO
from .engine_models import ENGINE_COMMIT, ENGINE_DATA_COMMIT, ENGINE_COMPATIBILITY

ToolName = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]{0,79}$')]


class CapabilitiesRequest(DTO):
    host_tool_names: Annotated[list[ToolName], Field(max_length=128)] | None = None


class Feature(DTO):
    name: ToolName
    implemented: bool
    configured: bool
    disable_reason: Literal['not_configured', 'future_feature'] | None = None
    next_action: Literal['configure_service', 'use_official_trade_site'] | None = None


class Capabilities(DTO):
    server_version: str
    protocol_profile: Literal['poe2-workflow-v1'] = 'poe2-workflow-v1'
    engine_commit: str
    engine_data_commit: str
    engine_compatibility: str
    tool_schema_hash: str
    configured_tool_count: int
    configured_tools: list[ToolName]
    host_inventory_status: Literal['unknown', 'matches_reported_inventory', 'differs_from_reported_inventory']
    missing_from_reported_host: list[ToolName]
    features: list[Feature]
    max_tool_result_bytes: Literal[8192] = 8192
    max_equipment_candidates: Literal[64] = 64
    max_equipment_changes: Literal[3] = 3
    schema_discovery_tool: Literal['describe_tool_schema'] = 'describe_tool_schema'
    default_trade_mode: Literal['instant_buyout'] = 'instant_buyout'
    authentication_is_permanent: Literal[False] = False
    website_link_is_game_action: Literal[False] = False


class SchemaRequest(DTO):
    tool_name: ToolName
    direction: Literal['input', 'output'] = 'input'
    offset: Annotated[int, Field(ge=0, le=1000000)] = 0
    limit: Annotated[int, Field(ge=128, le=1800)] = 1500


class SchemaPage(DTO):
    tool_name: ToolName
    direction: Literal['input', 'output']
    schema_hash: str
    schema_json_fragment: Annotated[str, Field(max_length=1800)]
    offset: int
    total_characters: int
    next_offset: int | None
    assembly: Literal['concatenate_fragments_then_parse_json_including_defs'] = 'concatenate_fragments_then_parse_json_including_defs'
    example_arguments_json: Annotated[str, Field(max_length=3000)] | None = None


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


async def inventory(server, request: CapabilitiesRequest, configured: dict[str, bool]) -> Capabilities:
    tools = sorted(await server.list_tools(), key=lambda tool: tool.name)
    names = [tool.name for tool in tools]
    missing = sorted(set(names) - set(request.host_tool_names or [])) if request.host_tool_names is not None else []
    status: Literal['unknown', 'matches_reported_inventory', 'differs_from_reported_inventory'] = 'unknown' if request.host_tool_names is None else (
        'matches_reported_inventory' if set(names) == set(request.host_tool_names) else 'differs_from_reported_inventory')
    return Capabilities(server_version=__version__, engine_commit=ENGINE_COMMIT,
        engine_data_commit=ENGINE_DATA_COMMIT, engine_compatibility=ENGINE_COMPATIBILITY,
        tool_schema_hash=digest([{'name':t.name,'input':t.inputSchema,'output':t.outputSchema} for t in tools]),
        configured_tool_count=len(names), configured_tools=names, host_inventory_status=status,
        missing_from_reported_host=missing, features=[Feature(name=name, implemented=True,
            configured=enabled, disable_reason=None if enabled else 'not_configured',
            next_action=None if enabled else 'configure_service') for name, enabled in configured.items()] + [
                Feature(name='hideout_execution', implemented=False, configured=False,
                    disable_reason='future_feature', next_action='use_official_trade_site')])


async def schema_page(server, request: SchemaRequest) -> SchemaPage:
    tools = {tool.name:tool for tool in await server.list_tools()}
    if request.tool_name not in tools:
        raise ValueError('schema_tool_unavailable')
    tool = tools[request.tool_name]
    schema = tool.inputSchema if request.direction == 'input' else tool.outputSchema
    text = canonical(schema)
    end = request.offset + request.limit
    examples = {
        'get_build_profile': {'request': {'build_id': 'bld_'+'1'*32}},
        'inspect_build': {'request': {'build_id': 'bld_'+'1'*32, 'section':'skills', 'offset':0, 'limit':10}},
        'get_capabilities': {'request': {}},
    }
    return SchemaPage(tool_name=tool.name, direction=request.direction, schema_hash=digest(schema),
        schema_json_fragment=text[request.offset:end], offset=request.offset, total_characters=len(text),
        next_offset=end if end < len(text) else None,
        example_arguments_json=canonical(examples[tool.name]) if request.offset == 0 and tool.name in examples else None)
