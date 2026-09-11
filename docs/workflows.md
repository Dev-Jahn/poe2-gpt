# Build workflows in 0.14

This release covers the 25-ticket development handoff. The [79-case map](workflow-014-cases.json) points to executable regressions; the [acceptance ledger](workflow-014-acceptance.md) records which tree was actually tested. Mapping, native simulation, authenticated MCP replay, installed ChatGPT behavior and gameplay observations are separate evidence levels. Historical private fixtures were not identified or replayed.

## Discover, inspect and choose a subject

Start with `get_capabilities`, following inventory pages. Optional services change the configured list. A host inventory is unknown unless the host explicitly reports its names; a count difference does not prove a stale connector. `describe_tool_schema` pages lossless JSON including nested definitions, the schema hash and validated placeholder examples. Replace placeholder IDs with discovered entities and pins. This release includes 100 tools when every optional service is enabled.

`get_build_profile` uses native loaders without combat calculation. Its MCP union result is under `result`: a native profile, or a partial saved projection when the engine is disabled or busy and an import projection exists. The native profile exposes active sets, equipment/empty sockets, stable skill instances, native gem requirements and a source digest. Page all instances. Saved default, requested skill and evaluated subject remain distinct. Fallback fields explicitly identify unavailable native identity and calculations; `get_saved_build_equipment` still reads available import-time equipment.

Select a discovered instance, actor, component and weapon set for every calculation. Ordinary player, Hollow image, selected minion and Spirit Vessel copy metrics cannot be substituted for each other. An unavailable target yields no replacement DPS. `calculate_skill_components` retains separate component receipts and does not invent a combined rotation sum. Totem ownership outside the supported actor contract remains unavailable.

Static cache identity includes source digest, engine/data/compatibility pins, projection revision and selectors; owner instances have separate caches. Hot pages do not recalculate combat. Source check/import/model times and identical-content reuse do not establish current game state.

## Compare complete changes

`create_build_experiment` evaluates at most 32 typed edits on an immutable clone: native gem level/quality/enabled state, support composition, passive/attribute/ascendancy changes, saved or retained trade equipment, rune sockets and verified instilling recipes. Entities come from native catalogs. Invalid edits reject the clone atomically. Related plans share a source digest and exact subject/scenario. A final valid item arrangement still requires a proven transition order.

The transition search replays native prefixes, including mixed gem/equipment changes and user-confirmed owned helpers. New equipment cannot supply its own initial requirement. Search is bounded to 64 native edges and 32 actions; exhaustion is not proof that no game-valid order exists. Equipment/gem maxima and cumulative support requirements remain separate. `analyze_plan_dependencies` reports joint resistance, attribute, Spirit and recovery loss with correction requirements; unknown corrective prices are not zero.

`discover_passive_paths` enumerates adjacent ordinary and weapon branches across the complete graph within an explicit new-node limit. `compare_passive_paths` evaluates up to six full paths with all travel points and common edits, preserving jewels at each native endpoint. Ordinary points and each weapon pool require their own evidence; matching weapon branches share the native ordinary pool. Unsupported special-allocation routes fail closed. Route and execution pages include verified Korean names or English fallback, effects, coordinates and starting landmarks. Five-node batches keep IDs in the machine references.

`compare_support_portfolio` compares complete support alternatives for one subject and scenario in one worker. Socket capacity belongs to the actual gem. A new level-90 gem does not inherit an old gem's upgraded sockets. `enemy_isolated` is an explicit hypothetical native configuration; an isolated-target bonus is not map-wide uptime. Price sockets, gem levels, quality and other materials before approving a purchase.

`compare_item_transformations` links original and effective gloves to their retained calculations. Known transformed inputs can be compared exactly within native coverage. Unreported rolls remain unresolved. User-supplied intervals are conditional character-metric envelopes, not verified game roll pools or a certified midpoint.

## Explain costs and uncertainty

`compare_build_purchase_plans` compares up to six complete supplied plans under matching scenarios, with at most four scenarios per plan. It retains exact plan IDs, bill components, constraint failures, coverage, one FX batch and rank crossings. It does not enumerate the entire market. Missing/stale material costs prevent a complete total; expected sales do not become spendable currency. At most one primary plan is returned, and crossed scenario ranks stay on a conditional frontier.

Official trade search defaults to Instant Buyout (`securable`). Changing that mode is explicit. Retained pages remain available during upstream cooldown; repeated identical failures have a bounded retry policy. Zero matches describe the exact query, with explicit relaxation suggestions. `get_build_diagnostics` preserves listing identities for both evaluated and prefiltered candidates, constraints, normalized costs and input/FX provenance.

`analyze_build_risks` separates subject, equipment, requirements, mechanics and metric coverage. Event findings distinguish producer, recipient, kill credit, Blind source and charge conversion. No favorable event is enabled automatically. A declared guaranteed-critical target exception requires its own native scenario. Follow `next_effect_offset` with identical inputs to recover all event edges.

`analyze_native_recovery_scenario` binds capacities, net regeneration/degen and attack costs to a retained subject. Explicit finite schedules distinguish recharge interruptions, clipping, existing leech/recoup flows and cannot-attack windows. Unknown full-mana leech expiry produces both cases. Post-mitigation hit schedules do not independently derive maximum hit or prove live immortality. Joint Ghost Dance and ES-buffer removal produces separate recovery and capacity warnings.

## State, execution and downloads

Plans begin as proposals. `update_build_plan` uses the plan digest and expected revision; accepted, partly applied, applied, observed, rejected and superseded states are distinct. `record_build_observation` stores typed user reports with pending source confirmation and retains conflicts. It never silently replaces the original build. Reports of depletion or death block repetition of the same plan.

`create_build_execution_plan` produces one route or only prerequisite actions when budgets, unlocks, subject, order or observations are unresolved. `plan_build_rollback` compares reported applied changes against an earlier reported successful state. Its minimum scope is the changed fields; a live rollback's requirements still need a new snapshot and native evaluation. Consumables may need to be purchased again.

`export_build_execution_plan` creates Markdown or JSON from the same execution object. The Markdown contains the exact machine object and shared artifact digest. Stored bytes are read back and SHA-256 checked before a URL is returned. Downloads are under the existing authenticated `/accounts/artifacts/<export_id>` path (or member-prefixed equivalent); the same owner must open the link. They do not need GGG OAuth. GET/HEAD never execute game actions. Missing/expired/deleted or other-owner artifacts are unavailable. `delete_build_plan_export` removes the retained bytes.

Downloads require the server's configured HTTPS public host and Access authentication. Local stdio installations without that origin use the existing lossless plan pages. User reports and plan exports are encrypted at rest when persistence is explicitly requested, with TTLs, quotas, member isolation and deletion. Original PoB, credentials and raw trade importer payloads are excluded. Calculation receipts remain bounded in memory and expire on restart; a saved decision must not be presented as a newly available calculation receipt.

## Progress, guides and game economy

Progression plans use native gem requirements and user-reported point/socket/unlock evidence. Missing quest information stays unknown. Account labels, official login, Ninja refresh, game online status and hideout travel remain distinct. Hideout execution and server browser sessions are deferred.

Guides are fetched only from allowed public HTTPS providers with bounded bodies. Requested variant/stage, author uncertainty, prerequisites, retained source digest and prose/machine conflicts stay separate. Inaccessible variants remain gaps. External text cannot request credentials or tool actions.

Map/reward/crafting tools evaluate typed inputs and observed costs, distinguishing asking prices, unsold loot, realized proceeds and unknown pools/probabilities. Unknown odds produce break-even conditions and maximum loss, not fabricated expected profit. Currency portfolios separate proposals from reported transfers and idempotent spend events. Allocation plans compare exact currency identities, historical buckets, explicit spread/depth hypotheses, downside and equipment opportunity cost. Historical conversion uses the reference price from the same bucket; current quote fetch time is not a historical market observation.

## Operations and evidence

`begin_workflow_trace` and typed workflow steps record calls, bytes, token estimates, phase timings and explicit goal evidence within deadlines and budgets. Successful HTTP responses alone do not complete a task. Tracing is opt-in; host reasoning time, billed tokens and gameplay success are not inferred. Cancellation stops waiting/queued work; it does not promise immediate termination of already admitted native CPU work.

The release compatibility marker is `forbidden-rites-0.5.5-v5`, with the existing pinned upstream engine/data commits. Server and worker must be updated together. Main remains unprotected unless a repository administrator enables required checks; CI success is evidence, not branch-protection enforcement.
