# 0.14.1 workflow follow-up

This patch addresses the seven post-merge review findings on PR #19. It does not change the pinned engine/data commits or claim new game mechanics coverage.

| Finding | Corrected behavior | Regression |
|---|---|---|
| Wrong subject combat output | Unavailable explicit targets expose no combat scenario, selected skill, stats or mechanics, including replacement calculations. | `test_workflow_subjects_real.py` |
| Cross-encounter observation collisions | Resource keys include encounter; conflicting reports within the same encounter still block. | `test_workflow_observations.py` |
| Inexact sale identity | A supplied item level or rune count must match, including rejecting unavailable listing metadata from the matched price band. | `test_workflow_economics.py` |
| Non-idempotent completion | An unchanged closed trace returns the retained revision/digest across restarts; corrected user completion reports still produce a revision. | `test_workflow_telemetry.py` |
| Lost history | Full-window buckets are stored in the allocation document. The bounded result shows the first eight, total count, truncation flag and `get_currency_allocation` recovery tool. Coverage checks use all retained buckets. | `test_workflow_allocation.py` |
| Conflated validation axes | Requirement failures/unknowns and mechanic failures/unknowns are assessed independently. Truncated evidence cannot certify success. | `test_workflow_risks.py` |
| Lost map assumptions | Every interaction preserves input evidence; hypotheses have a distinct matched status and confirmation action. | `test_workflow_economics.py` |

The history regression covers 169 hourly points across a full inclusive seven-day window, missing intervals, duplicates and lossless artifact pagination. Pre-0.14.1 allocations have unknown preview completeness and no recoverable full-history field; replan to obtain the new evidence.

## Tool catalog and model context

MCP discovery/host catalog storage and model context loading are separate operations. The 2026-09-12 authenticated ChatGPT comparison exposed 27 tools in the old connection and all 96 configured tools in a new connection. Both reached the same reported server/engine version. This supports a connection metadata refresh problem; it does not identify an internal cache mechanism.

In the inspected Work session, tool declarations could be retrieved selectively before invoking tools. This is session evidence, not a guarantee for every ChatGPT mode. [OpenAI Tool search](https://developers.openai.com/api/docs/guides/tools-tool-search) documents host-controlled deferred loading. In the Responses API, the host enables `tool_search` and `defer_loading`; the MCP server cannot enforce that behavior by changing its tool descriptions. A loaded schema may remain in conversation context. Prompt caching is not removal of schema tokens from context.

`get_capabilities` now reports compact sorted ASCII JSON catalog bytes, separate input/output schema byte sums and UTF-8 description bytes. `tool_catalog_bytes` counts `{"tools":[...]}` with null fields excluded; it excludes HTTP framing and server instructions and is not a token estimate. `model_context_loading` explicitly reports that host loading is not observable by the server. `python scripts/check_tool_catalog.py` measures the fully configured catalog offline and checks a 900,000-byte project growth budget, not a supposed platform limit.

All existing tool names, input constraints, output schemas and permission annotations remain available. `describe_tool_schema` recovers complete nested schemas on demand but does not itself remove them from MCP `tools/list`. A universal untyped dispatcher would sacrifice tool-specific validation and permission semantics; this patch does not introduce one.

## Validation scope

Local Python verification and native CI results are recorded in the follow-up PR. Native tests use synthetic inputs and no external network. Production verification must check the exact deployed SHA/version and authenticated MCP behavior separately.

The historical seven private failure cases still require a verified case-to-input mapping. Existing opaque private builds do not establish that mapping. A real signed-in production artifact download and repository branch protection remain separate checks; synthetic authenticated HTTP tests do not establish either.
