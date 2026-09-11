"""Runtime inventory and lossless nested schema discovery, not host guesswork."""
from __future__ import annotations
import hashlib
import json
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal
from pydantic import Field
from . import __version__
from .builds import DTO, bounded_dto
from .engine_models import ENGINE_COMMIT, ENGINE_DATA_COMMIT, ENGINE_COMPATIBILITY

ToolName = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]{0,79}$')]


class CapabilitiesRequest(DTO):
    host_tool_names: Annotated[list[ToolName], Field(max_length=128)] | None = None
    offset: Annotated[int,Field(ge=0,le=1000)] = 0
    limit: Annotated[int,Field(ge=1,le=40)] = 30


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
    missing_from_reported_host_count: int
    next_offset: int | None
    inventory_pagination: Literal['same_offset_pages_configured_and_missing_tool_lists'] = 'same_offset_pages_configured_and_missing_tool_lists'
    features: list[Feature]
    max_tool_result_bytes: Literal[8192] = 8192
    result_limit_scope: Literal['bounded_build_workflow_and_runtime_dtos; legacy_market_tools_have_separate_row_limits'] = 'bounded_build_workflow_and_runtime_dtos; legacy_market_tools_have_separate_row_limits'
    max_equipment_candidates: Literal[64] = 64
    max_equipment_changes: Literal[3] = 3
    schema_discovery_tool: Literal['describe_tool_schema'] = 'describe_tool_schema'
    default_trade_mode: Literal['instant_buyout'] = 'instant_buyout'
    authentication_is_permanent: Literal[False] = False
    website_link_is_game_action: Literal[False] = False
    max_changeset_edits: Literal[32] = 32
    max_joint_variants: Literal[6] = 6
    maximum_native_transition_edges: Literal[64] = 64
    supported_target_actors: list[str] = Field(default_factory=lambda:['player','minion','hollow_image','spirit_vessel'])
    supported_edit_types: list[str] = Field(default_factory=lambda:['set_gem','set_supports','allocate_passives','refund_passives','set_ascendancy','equip_item','unequip_item','socket_rune','instill_amulet'])
    recovery_scenario_types: list[str] = Field(default_factory=lambda:['no_hit','continuous_hits','ritual','boss_no_adds','custom'])


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
    example_scope: Literal['schema_valid_placeholders_require_discovered_entities'] = 'schema_valid_placeholders_require_discovered_entities'


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
    end=request.offset+request.limit
    return bounded_dto(Capabilities(server_version=__version__, engine_commit=ENGINE_COMMIT,
        engine_data_commit=ENGINE_DATA_COMMIT, engine_compatibility=ENGINE_COMPATIBILITY,
        tool_schema_hash=digest([{'name':t.name,'input':t.inputSchema,'output':t.outputSchema} for t in tools]),
        configured_tool_count=len(names), configured_tools=names[request.offset:end], host_inventory_status=status,
        missing_from_reported_host=missing[request.offset:end],missing_from_reported_host_count=len(missing),
        next_offset=end if end<len(names) else None,features=[Feature(name=name, implemented=True,
            configured=enabled, disable_reason=None if enabled else 'not_configured',
            next_action=None if enabled else 'configure_service') for name, enabled in configured.items()] + [
                Feature(name='hideout_execution', implemented=False, configured=False,
                    disable_reason='future_feature', next_action='use_official_trade_site')]))


@lru_cache(maxsize=1)
def tool_examples() -> dict[str, dict]:
    return json.loads(files('poe2_companion').joinpath('data/tool_examples.json').read_text())


async def schema_page(server, request: SchemaRequest) -> SchemaPage:
    tools = {tool.name:tool for tool in await server.list_tools()}
    if request.tool_name not in tools:
        raise ValueError('schema_tool_unavailable')
    tool = tools[request.tool_name]
    schema = tool.inputSchema if request.direction == 'input' else tool.outputSchema
    text = canonical(schema)
    end = request.offset + request.limit
    examples = tool_examples()
    return SchemaPage(tool_name=tool.name, direction=request.direction, schema_hash=digest(schema),
        schema_json_fragment=text[request.offset:end], offset=request.offset, total_characters=len(text),
        next_offset=end if end < len(text) else None,
        example_arguments_json=canonical(examples[tool.name]) if request.direction == 'input' and request.offset == 0 and tool.name in examples else None)
