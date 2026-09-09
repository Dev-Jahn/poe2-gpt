# 0.11 review resolution

Review baseline: `9b215f78b5e736c00ba1ec59480f47eed1c3918f` (0.10.0).
This document describes implementation scope, not production deployment state.

| Review issue | Implementation and verification |
|---|---|
| Cannot describe saved equipment | `get_build_equipment` and `inspect_build` read all saved IDs through the private interpreter, including attachments, inactive items, variants, requirements, rune/modifier flags and paginated properties. Parsing is explicitly not full calculation verification. Native tests preserve raw originals and omit notes. |
| Cannot discover skills/settings | `inspect_build` sections `skills`, `sets`, `configuration` and `passives`; set IDs, groups/supports, selected skill, saved/override/default/effective values. `configuration_key` narrows a field; compound overrides are flattened into pages. |
| Stale Ninja snapshot concern | Every `get_character` resolves and fetches the published Ninja model. Check time/model version/content reuse are separate. A→B→A and failed-upstream tests prevent false freshness claims. `refresh_character` separately requests a game-account refresh. |
| Global indeterminate gate | `equipment_validity` and per-stat `metric_coverage`; narrow inspected resource dependency proofs, including conditional tags, level growth, attributes and conversion guards. Unknown effects stay blocked. Real leech/resource and conditional-Life regressions. |
| Invalid baseline cannot be repaired | `restore_validity` minimizes candidate cost; requires valid resulting equipment, with no baseline score/delta claim. Real requirement-repair regression. |
| Trade options disappear | Known numeric values survive unknown lines. `get_trade_item_details` pages names, base and all modifier text independently of private PoB-import eligibility. `proxy_optimization_eligible` is explicitly scoped; legacy alias remains. |
| Misleading errors | Safe error codes, paired missing fields, recovery category/action and trace IDs. No raw exception or input retention. Operational-status regression covers Refutation and blocking/cooldown state. |
| Truncated details cannot be retrieved | Immutable `calculation_id`, complete private receipts and `get_build_diagnostics`: issues, mechanics, stats, deltas, coverage, inputs, combat result and candidate evaluations/details. Lua no longer pre-truncates. TTL/capacity/instance isolation are explicit. |
| Nonlinear leech cap | Per-hit integration, separate crit/noncrit paths, independent type draws and proportional cap. Analytic single-type uniform/lucky; exact minimum/maximum enumeration; bounded quadrature is labeled. Pure independent oracle and real capped-range regressions. |
| Missed sequential equipment change | Remove only the current slot's old item at each step. Other old gear can support the next change; new items never satisfy their own initial requirements. Real helmet/boots counterexample. |
| Search/league/metric limits | Exact item name/base, item level, AND/count groups, sort options. Ninja origin league checked; attachments require separately declared league. Uncapped resistance, overcap, maximum-hit and recovery values; requested metrics retained in summaries. |
| Weak operations/engineering gates | Trade cooldown/block state, process-local latency/error counts and bounded safe error traces. Locked CI/container dependencies, fatal lint checks, all-module mypy and 85% coverage gate. Real x64/ARM engine CI remains in workflow. |
| Duplicated validation UX / loose outputs | Validation returns a compact deficit report and receipt ID; currency tools have explicit nested DTOs. MCP tests validate actual structured results and schemas. |

## Boundaries

Resource comparisons require an inspected dependency proof; this is not a blanket
whitelist for Life or ES. Other metrics require full coverage until a comparable
proof exists. Candidate enumeration is exact within the explicitly retained,
affordable set, not the whole market. Borrowed temporary gear is not searched.

Receipts last at most one hour, 64 calculations and a 32 MiB process-local budget
(plus one bounded latest result); restart or eviction produces an explicit error.
Large summaries direct callers to pages. Overrides and hypothetical schedules
are not observed combat telemetry.

Leech integration follows [Life Leech](https://poe2db.tw/us/Life_Leech) and
[Only Minimum or Maximum Damage](https://poe2db.tw/us/Only_Minimum_or_Maximum_Damage).
Upstream averaged double/triple damage, exertion and physical mitigation can
still make the supplied hit model approximate. Continuous mixed-type quadrature
is also approximate; supplying resistance or uptime does not remove that label.

All external text remains data, never instructions. Raw PoB/XML, seller whispers,
notes, arbitrary paths and private credentials remain outside public responses.
Unknown modifiers can be described without certifying their calculation effects.

Branch protection is a GitHub administration setting. The workflow provides CI
checks but does not claim that a repository ruleset has been enabled. Production
and actual ChatGPT-host acceptance require a deployed release; protocol tests
are not a claim of a live-host evaluation.

## Host acceptance scenarios

1. Fetch by tag/name twice; show fresh Ninja checks and identical-content reuse.
   Fetch again after Ninja changes equipment.
2. Describe the Sapphire Ring, discover an unequipped saved item and compare its
   ID. Repeat with a ChatGPT-attached `.txt` build.
3. Inspect skills/supports and saved/effective settings; recover an incomplete
   Refutation override using its reported missing field.
4. Compare Life with unrelated leech uncertainty, reject an unknown conditional
   resource effect, and repair invalid equipment at minimum cost.
5. Search by name/base/count filters, explain known and unknown lines, reject
   league mismatch and state the evaluated candidate scope.
6. Follow all diagnostic pages, including an excluded candidate; recalculate
   when the receipt expires.
