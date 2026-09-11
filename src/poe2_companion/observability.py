"""Bounded operational counters. No payloads, identities, paths or raw errors."""
from typing import Annotated, Literal
from pydantic import Field
from .builds import DTO, bounded_dto, tool_json_bytes


class ToolCounters(DTO):
    tool: Annotated[str, Field(max_length=80)]
    calls: int = 0
    errors: int = 0
    elapsed_ms: float = 0
    max_elapsed_ms: float = 0


class RuntimeStatus(DTO):
    tools: Annotated[list[ToolCounters], Field(max_length=128)]
    recent_errors: Annotated[list['ErrorTrace'], Field(max_length=16)] = Field(default_factory=list)
    process_local: bool = True
    raw_payloads_logged: bool = False
    total_tools: int = 0
    total_recent_errors: int = 0
    next_offset: int | None = None
    pagination: Literal['same_offset_pages_live_tools_and_recent_errors'] = 'same_offset_pages_live_tools_and_recent_errors'


class ErrorTrace(DTO):
    trace_id: Annotated[str, Field(pattern=r'^[0-9a-f]{24}$')]
    tool: Annotated[str, Field(max_length=80)]
    code: Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]+$', max_length=100)]
    category: Literal['arguments', 'retryable', 'user_input', 'operator_action', 'unavailable']
    occurred_at_epoch: int


def runtime_page(counters: list[ToolCounters], errors: list[ErrorTrace], offset: int, limit: int) -> RuntimeStatus:
    """Page both bounded lists without dropping diagnostics to fit the wire cap."""
    end = offset + limit
    while True:
        page = RuntimeStatus(tools=counters[offset:end], recent_errors=errors[offset:end],
            total_tools=len(counters), total_recent_errors=len(errors),
            next_offset=end if end < max(len(counters), len(errors)) else None)
        if tool_json_bytes(page) <= 8192 or end <= offset + 1:
            return bounded_dto(page)
        end -= 1


def recovery(code):
    if code=='trade_repeated_query_failed':
        return 'arguments','use_retained_results_or_review_query_before_retry'
    if code in {'engine_busy','engine_timeout','engine_unavailable','trade_timeout','trade_rate_limited','trade_cooldown','internal_tool_error','tool_request_failed'}:
        return 'retryable','wait_then_retry_once'
    if 'authentication' in code or 'challenge' in code or code in {'trade_forbidden','trade_unauthorized'}:
        return 'operator_action','check_integration_status_and_operator_configuration'
    if code in {'character_league_unverified','character_league_mismatch'}:
        return 'user_input','check_origin_league_or_declare_attachment_league'
    if code=='calculation_expired_or_unavailable':
        return 'user_input','recalculate_build_to_obtain_new_calculation_id'
    if code.startswith(('invalid_','incomplete_')) or code in {'engine_invalid_request','trade_invalid_query'}:
        return 'arguments','correct_arguments_using_tool_schema'
    if code in {'engine_candidate_space_too_large','candidate_space_too_large_narrow_candidates'}:
        return 'arguments','select_fewer_candidate_refs_or_change_slots'
    return 'unavailable','check_tool_status_and_report_trace_id'
