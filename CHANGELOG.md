# Changelog

## 0.12.0

- Preserve required empty inspection records through actual MCP output validation.
- Resolve active equipment slots within one private worker request per page.
- Add zero-cost Unequip plans, explicit changed-slot budgets and removable-slot selection.
- Retain listing provenance, constraint violations, rankings, exclusions and objective/FX inputs.
- Default trade search to Instant Buyout (`securable`), preserving explicit overrides.
- Expose honest official-site handoff metadata; direct in-game travel links remain unverified.
- Require typed definitions and body checking for inspection, receipts and planning.
- Add protocol and real-engine regressions for empty results and two-handed weapon transitions.

See [0.12 review follow-up](docs/review-012.md) for scope and remaining limitations.

## 0.11.0 (unreleased)

- Inspect equipped and saved items, effective modifier variants, requirements,
  rune flags, skills/supports, saved sets and passive effects through the private
  pinned interpreter. Both Ninja and attached builds work.
- Show saved, overridden, default and effective configuration. Immutable receipts
  page full issues, mechanics, metrics, deltas, scenarios and candidate diagnostics.
- Expose request-time Ninja check/model version separately from content reuse;
  retain origin league and reject cross-league purchase comparisons.
- Preserve known trade stats and describe unknown modifiers independently of
  calculation eligibility. Add exact name/base, item level, AND/count and sorting.
- Separate equipment validity and metric coverage. Narrow dependency proofs allow
  resource comparisons with unrelated combat uncertainty; `restore_validity`
  minimizes repair cost without claiming a valid-baseline score delta.
- Integrate per-hit leech caps: analytic single-type uniform/lucky and exact
  independent minimum/maximum enumeration. Mixed continuous damage and upstream
  averaged mitigation remain explicitly approximate.
- Search sequential replacements retaining other old gear. Add uncapped
  resistance, overcap, maximum-hit and recovery metrics.
- Add typed currency outputs, compact validation, actionable safe errors, trace
  IDs, latency/error counters and trade blocking/cooldown state.
- Gate CI on locked dependencies, lint, all-module type checks and 85% Python
  coverage; retain real x64/ARM engine tests with no skipped tests.

## 0.10.0

- Implement Spirit Vessel copied attacks, supports and defences; bounded charge,
  recoup and Mountain's Teachings event scenarios; Ghost Dance, Hollow Focus/Form,
  Tempest Bell, Wind Dancer and Refutation calculations.
- Apply PoE2 hit-leech caps/duration and Impale generation/extraction rules;
  update Vaal Pact, Mana Drain and Soul Tether behavior. Unverified resistance
  values and combat uptime remain explicit assumptions.
- Add captured-beast modifier support and immutable private Ninja metadata,
  matched by unique canonical species/skill/support signatures. Apply verified
  captured-beast ally auras with separate source and recipient state. PoB payloads
  and private upstream text remain outside MCP responses and arguments.
- Implement explicit hit/kill buffs, curse target-level checks, Charged Mark
  ground and Rite of Passage states; retain native support and actor scope.
- Add typed calculation configuration to recalculation, equipment validation,
  comparisons and budget optimization. Apply the same assumptions to every
  candidate without altering saved builds; reject verified recommendations
  when baseline or candidate calculations are incomplete.
- Backport narrowly reviewed curse-condition, rune-parser and Baryanic Leylines
  fixes. Record all six upstream branches and 71 open PRs reviewed during this
  release's inventory, distinguishing triage from detailed source review.
- Preserve numeric status and truncation markers within the 8 KiB public output
  limit; synchronize package, MCP initialization and health version metadata.

## 0.9.0

- Add source-anchored Stonefist requirement, charge-event, Offering Life,
  Companion composition, Wolf Pack and Verglas calculations and diagnostics.
- Calculate Spirit Vessel Life and scoped skill bonuses; preserve weapon-set
  selectors and resolve granted-skill levels against current sources and attributes.
- Detect unmapped game-visible stats on effective skills and compatible supports;
  preserve missing-data and combat-assumption uncertainty in recommendations.
- Return bounded numeric mechanics separately from character DPS, with explicit
  coverage status, required inputs and truncation counts.
- Advertise the project version in MCP initialization and engine status, keep
  package/runtime/manifest versions synchronized, and document separate ChatGPT
  plugin metadata. Correct the local `.mcp.json` wrapper to the plugin schema.

## 0.8.0

- Pin the current PoB2 development source and a checksummed, data-only 0.5.5 overlay for Forbidden Rites, with separate source/data/compatibility health markers.
- Expose canonical selected-skill identity and selected-minion DPS; omit unconfigured FullDPS instead of presenting it as zero damage.
- Calculate the equipment attribute-requirement exemption without removing gem or level requirements; add missing-ES Deflection scaling and expose `DeflectionRating`.
- Diagnose unknown and unparsed passive nodes, modern custom modifier blocks, ignored item limits and character rune-slot effects; preserve validation and issue counts within bounded responses.
- Import compatible socketed runes and Soul Cores from trade items, checking socket type, index, item compatibility and unique limits.
- Add an offline, provenance-backed English/Korean PoE2DB name catalog and `search_game_terms`; localize currency, base types, classes and selected skills without changing provider IDs or guessing missing names.
- Support Korean trade-stat lookup through the official Korean publisher's metadata, joined only by canonical stat ID; localized metadata failures do not block English trade requests.
- Keep engine revision values out of public schema constants so data-only pin updates do not require new ChatGPT tool metadata; reject missing or mismatched worker provenance on every calculation.
- Document Refresh of existing ChatGPT connections after tool metadata changes, including new-conversation character lookup checks.
- Preserve private build ingestion, per-user isolation and existing saved builds. No raw PoB tool input/output or physical-host import workflow is added.

This release improves current-league compatibility; unimplemented upstream mechanics remain explicit and prevent verified upgrade recommendations. See [engine coverage](docs/pob-engine.md) and [localization provenance](docs/localization.md).

## 0.7.0

- Add account-tag character discovery and automatic private poe.ninja PoB ingestion, using current snapshot versions from the upstream event stream.
- Add ChatGPT `.txt` file attachment import with `openai/fileParams`; raw bytes remain outside MCP responses.
- Add explicitly requested Ninja refresh with per-user session binding and persistent cooldowns.
- Isolate the network-enabled importer, raw store and credentials from MCP and the network-disabled PoB worker.
- Remove the physical-host PoB import workflow, CLI and operator Compose service; preserve existing saved builds.
- Move synthetic deployment checks away from production ports.


## 0.6.0

- Share one Mac with two friends using authenticated per-person MCP paths, separate processes, private volumes and worker sockets.
- Keep build IDs, retained trade searches and recommendation state scoped to the individual's instance; only public Scout snapshots are cached together.
- Add operator commands for member registration, targeted build import and revocation, with retired identities reserved to prevent accidental data reassignment.
- Limit the isolated PoB workers to one calculation batch at a time using a shared empty lease file.
- Test foreign build/dataset/search access, forged identity headers, three-container private imports and real calculations on both CPU architectures.

The operator retains administrative access to all files. Self-service upload and character-name lookup remain unimplemented. Real Cloudflare and ChatGPT acceptance tests are required after deployment.

## 0.5.0

- Cloudflare Access Managed OAuth deployment with origin-side JWT signature, issuer, audience, expiry and single-owner checks.
- Mac mini deployment through a dedicated Colima VM and Cloudflare Tunnel, with isolated login services and private token-file configuration.
- Native ARM64 and amd64 real-engine CI, plus container tests for authentication and raw/projection volume isolation.
- Linux-native private build volumes and a bounded operator-only import pipe; no raw PoB tool input/output was added.
- Multi-architecture release images and localized links to the new deployment guide.

Actual Mac login/reboot behavior and the Cloudflare-to-ChatGPT OAuth connection require deployment acceptance testing.

## 0.4.0

Initial public source release, consolidating the earlier private prototype.

- Scout currency prices, league/category discovery, basket quotes, caching, and bounded retry behavior.
- Experimental official trade-site equipment filtering, stat discovery, and paginated retained search results.
- Private external PoB import/export, safe build projections, and optional equipment datasets.
- Pinned PoE2 PoB worker, equipment requirements, candidate comparisons, and budget optimization.
- Standard plugin manifest and marketplace metadata, English technical documentation, five README locales, and CI/release workflows.

This version does not include a hosted MCP service, character-name lookup, a reviewed public ChatGPT listing, or built-in multi-user authentication.
