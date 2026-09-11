# Private PoE2 PoB engine

The optional Linux worker uses the upstream headless PoE2 Path of Building engine. The MCP server communicates over a private Unix socket; only the worker mounts raw builds. Calculations use a fresh LuaJIT process and the saved active tree, item set, weapon set, skill group, and configuration, with any explicit bounded [calculation assumptions](calculation-assumptions.md). The stored original build remains unchanged. Calculations do not fetch a live character or automatically enable favorable combat assumptions.

## Pinned dependencies

| Component | Pin |
|---|---|
| PathOfBuilding-PoE2 | `fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15` |
| PoE2 0.5.5 data | `b3282b7a9111ed6c4ec6be643edf0806d7beb675` (37 reviewed data files from open PR #2505) |
| Companion compatibility | `forbidden-rites-0.5.5-v5` |
| LuaJIT | `24c20c94e7db195b640854619577441f9b4bc6be` |
| luautf8 | `0.2.0` |

Installers verify the source archive and each overlaid data file with SHA-256 and retain licenses. Health checks verify both source commits and the compatibility revision. The data snapshot updates Soul Cores, skill/base/modifier data, spectres, trade stat mappings, and the 0.5 passive tree. The 17 new 0.5.5 Soul Cores and existing Soul Core balance changes are included. A narrow importer correction preserves `explicitMods[].flags.desecrated` while retaining legacy modifier arrays. Eight exact crafting-only lines (item influence eligibility and guaranteed corruption change) are recognized as having no current combat-stat effect. Unknown combat modifiers remain diagnosed; no broad text pattern suppresses warnings. Source is downloaded during setup, never auto-updated at runtime. See `scripts/install_pob_engine.py` and `scripts/install_lua_runtime.py` for digests and URLs. A PoB document's `Build.targetVersion=0_1` differs from passive-tree `treeVersion=0_5`; unsupported documents are rejected, and an outdated active tree is excluded from recommendations.

The integration uses [HeadlessWrapper.lua](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/blob/fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15/src/HeadlessWrapper.lua), the upstream [slot validator](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/blob/fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15/src/Classes/ItemsTab.lua), and [trade item importer](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/blob/fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15/src/Classes/ImportTab.lua).

Every private calculation response includes all three provenance markers, and the MCP client requires an exact match before returning numbers. Missing markers from an older worker or mismatched deployments produce `engine_version_mismatch`. Public output schemas constrain revision formats without embedding the current pin as a schema constant or default. Updating pins alone therefore leaves tool metadata stable; adding metrics or changing tool contracts still requires the host's metadata refresh.

## Data coverage and upstream review

This is a versioned community calculation engine, not a promise that every current game mechanic is implemented. The latest upstream release on the review date (2026-09-08) was v0.23.1, and the 0.5.5 export remained an open PR. Only reviewed data files from [PR #2505](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2505) are overlaid; its UI changes are excluded. [PR #2504](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2504) independently covers the Soul Core changes already represented by that export. The importer correction follows [PR #2507](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2507), preserving compatibility with older upstream responses.

The [0.10 upstream review](upstream-review-010.md) records branch and PR inventory, exact reviewed heads and individual dispositions. A metadata inventory does not establish that every proposal was validated or implemented. Open mechanics PRs require individual validation before inclusion:

- [Way of the Stonefist #2350](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2350) has ambiguous affix matching and midpoint conversion of transformed rolls; it is not applied.
- [Way of the Mountain #2073](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2073) is not copied wholesale. Independent [current Mountain's Teachings](https://poe2db.tw/us/Mountains_Teachings) calculations use an explicit stack snapshot for attack damage/Stun Threshold and a bounded event schedule for gain, spending and conditional small-hit reduction.
- [Tamed beast modifiers #2147](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2147), head `f2593c10320df3faf74008081548e433d5e849e8`, supplies the reviewed catalogue of 68 canonical modifiers. A mapped subset receives native calculations, with additional independently verified [Tame Beast](https://poe2db.tw/us/Tame_Beast) effects. Private imported metadata and explicit bounded roll lists preserve what is known; unknown rolls, unmapped effects and incomplete aura behavior remain diagnosed. Catalogue inclusion is not full support for every entry or every current beast modifier.
- [Leech #1938](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/1938) and [Impale #1820](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/1820) retain formulas that do not match current PoE2 definitions. Independent replacements apply the 40,000 total-hit leech cap before leech percentages and an explicit strongest-Impale extraction. The available numerical monster leech-resistance table remains provisional; an explicit resistance override resolves that input, not recovery uptime.
- [Runeforged unique variants #2511](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2511) changes editor/database variant selection and remains unmerged; existing actual item imports use their explicit base and modifier data.

Three narrow upstream corrections are included: [#2378](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2378) maps grammatical enemy-condition text to canonical Cursed/Marked/Electrocuted conditions; [#2367](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2367) preserves socket and rune records across import round trips; [#2381](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2381) applies Baryanic Leylines' 40% radius increase to eligible non-unique Time-Lost jewels in the actual calculator, including allocation overrides. Desktop drawing changes are excluded.

A successful calculation or `pass` means the implemented validation checks passed. It does not establish full mechanical coverage of all upstream skills. Unparsed allocated passives and missing saved passive nodes produce explicit diagnostics instead of silently disappearing.

Two verified item mechanics have narrow integration fixes. The Vertex's **Equipment has no Attribute Requirements** applies to both weapons and other equipment, while gem attributes and level requirements remain enforced. [Forgotten Warden](https://poe2db.tw/us/Forgotten_Warden)'s Deflection per 50 missing Energy Shield uses the saved current-ES percentage, defaults to full ES, and floors each complete 50-point step. Explicit zero ES is honored; overflow ES and characters unable to have ES cannot create negative or phantom missing ES. Flat Deflection and converted Armour/Evasion contributions all receive applicable increased/more Deflection modifiers. `DeflectionRating` exposes the resulting player value. These source patches are guarded against the exact pinned source.

The 0.10 compatibility layer extends charge/recovery events, Offering and Companion Life, composition checks and conditional Verglas damage with native Spirit Vessel copied attacks, captured-beast modifiers and explicit Natural Order states. Martial calculations cover scoped Ghost Dance, Hollow Focus/Form, Tempest Bell, Wind Dancer, Refutation and Mountain's Teachings behavior. Current leech/Impale rules, conditional hit buffs, curse eligibility, Charged Mark ground and equipped Rite of Passage possession have separate scopes and diagnostics. Already transformed Fists of Stone imports retain their supplied data; the unsafe midpoint transformation PR is not applied.

See the [coverage matrix](league-coverage.md) for exact source-backed calculations and remaining gaps, the [configuration reference](calculation-assumptions.md) for every accepted snapshot field, and [combat scenarios](combat-scenarios.md) for event semantics. Unmapped game-visible skill stats are diagnosed instead of silently omitted. These modules do not supply an AI rotation, live buff history, unknown captured rolls or proof of resource sustain.

## Validation

The worker detects active custom-modifier blocks and disabled limits. Complete diagnostics stay in immutable per-user calculation receipts; Lua does not truncate them. Public summaries stay within 8 KiB and expose counts, truncation flags and `calculation_id`. Use `get_build_diagnostics` to recover all issues, mechanics, stats, deltas, inputs, combat results and candidate details. Unknown passive diagnostics include numeric node IDs. Level, attribute, slot, weapon, class, gem, support, reservation and unchanged-equipment checks remain enforced.

Calculation JSON can omit optional `null` fields and the default
`origin="saved_build"`. Schema defaults restore their meaning. Integral numbers
may use integer JSON notation without changing their value; fractional values
are not rounded. If optional skill display labels must be removed to fit the
response limit, `selected_skill_labels_truncated` is true; canonical skill IDs
and actor identity remain present. Core and requested numeric metrics, equipment identities, configuration field
names, validation status and diagnostic counts are preserved. Additional metrics
and deltas may move to receipt pages, with explicit truncation flags.

Active Chakra rune slots are also checked for unknown selected rune names, rune level requirements, and unparsed applied modifier lines. This closes a separate upstream import path that does not use ordinary equipped-item modifier validation.

For up to three replacements, it searches sequential replacement orders. Each step removes only that slot's old item before checking the new item, retaining other old items until their turn and never crediting the new item's own attributes in advance. Temporary gear and more general remove/re-equip transitions are not exhaustively searched. Validating a current build checks its final state, not its historical equip sequence.

Hit-based leech integrates the per-hit total cap before applying leech coefficients and resistance. Single-type uniform/lucky distributions use analytic expectations; independent minimum/maximum damage types use exact enumeration. Continuous mixed-type damage uses bounded quadrature. Upstream averaged double/triple/exerted damage and physical mitigation retain an approximation label. The 20,000/60,000 equal-probability case at 10% leech yields 3,000, not 4,000. `leech_recovery_uptime` supplies a separate hypothetical active-rate scaling; it never resolves numerical approximation.

| Status | Meaning | Recommendation eligibility |
|---|---|---|
| `pass` | Supported checks passed in the selected configuration | Eligible |
| `fail` | A definite requirement or slot violation | Excluded |
| `indeterminate` | Unresolved mechanics or transition | Requested metrics need individual dependency proofs and equipment must be valid |

Recommendation eligibility separates equipment validity, requested metric coverage, required assumptions and origin-league match. A narrowly verified unconditional resource graph can permit Life/Mana/ES comparisons despite unrelated combat assumptions; condition tags, unknown effects and unproved conversions block the affected scope. Other metrics retain full-coverage requirements. `restore_validity` minimizes the cost of restoring valid equipment without a baseline score/delta claim. Inspect excluded candidates through receipt pages. Synthetic tests do not establish universal game compatibility.

## Damage scope

`selected_skill` identifies the selected canonical engine skill and whether its damage actor is the player or a minion. Saved skill labels are never returned. `gem_name`, when available, is the pinned gem database name and can be localized separately.

`TotalDPS` and `CombinedDPS` retain their upstream player-output meaning. `MinionTotalDPS`, `MinionCombinedDPS`, and `MinionSpeed` come from the selected minion's output and are explicit optimization objectives. They describe the selected minion calculation, not an inferred sum across every summoned actor. `FullDPS` is omitted when no skills are configured for Full DPS; `full_dps_enabled` distinguishes an absent aggregate from a genuine zero result. Optimization requests for missing metrics fail rather than treating them as zero.

Spirit Vessel copies use their own monster actor and actual compatible attack data; player weapon damage does not transfer implicitly. An explicit copied-skill ID chooses one attack, without inventing a rotation of all copies. Hollow Form's optional scenario uses average copied-image damage and supplied image-generation assumptions; it is not an automatic whole-build DPS replacement. An explicit existing Impale magnitude applies only to the selected eligible player attack, leaving unrelated skill groups and minion attacks unchanged.

## Budget optimization

Use `search_trade_stats`, then `search_trade_equipment`, then pass short search IDs and the imported build ID to `recommend_pob_trade_upgrades`. The server sends candidate item payloads directly to the worker.

Every baseline and candidate uses the same supplied `configuration` and `combat_scenario`. These assumptions are reported as hypothetical inputs, not newly observed character state. Candidate equipment still has to provide any required skill, support or mechanic source; configuration cannot bypass missing-source or unsupported-mechanic diagnostics.

`maximize_score` maximizes an explicit weighted gain in final character metrics. `minimize_cost` finds the cheapest eligible retained combination satisfying minimum final metrics. Keeping current gear costs zero and is included. There is no sale-income, crafting-cost, or fee model.

Requests allow up to four searches, 32 selected unique listings, three changes, and 64 affordable combinations. Larger spaces fail before calculation; narrow them with `candidate_refs`. Scout supplies estimated FX when price currencies differ. Listing fetch freshness defaults to 300 seconds, and handles expire at ten minutes. Results are not a post-calculation availability check.

Supported candidate slots cover weapons, armor, and accessories, including uniques the engine can parse. Jewels, flasks, and charms are not exposed as trade replacement slots. Socketed runes and Soul Cores are supported through a bounded projection containing their exact base names and socket indices, resolved against the pinned worker data. Socketed jewels, unknown rune bases, hidden modifiers, and unresolved mechanics remain excluded. Invalid individual trade candidates are excluded before building the calculation batch. Trade items have `origin=trade_candidate` and `saved_item_id=null`; use `changes[].listing_ref`, never an internal temporary engine ID.

## Runtime and tests

For deployment, use the engine Compose overlay in [deployment](deployment.md). A calculation is limited to 80 CPU seconds, 85 wall-clock seconds, 3 GiB address space, bounded file output, and 64 file descriptors. Cancellation or timeout kills the process group. The worker serializes requests and deletes temporary private files.

For local real-engine tests on Linux with GCC, make, and libc headers installed:

```bash
python -m pip install -e '.[test]'
# This installer writes the pinned runtime to /opt/lua; use a dedicated dev container.
python scripts/install_lua_runtime.py
python scripts/install_pob_engine.py /absolute/new/pob-source
POE2_TEST_ENGINE_DIR=/absolute/new/pob-source POE2_TEST_LUAJIT=/opt/lua/bin/luajit LUA_CPATH='/opt/lua/lib/lua/5.1/?.so;;' python -m pytest -q
```

Without the engine environment variables, real-engine tests skip. Container CI installs the actual pinned runtime and requires those tests to run, including Unix-socket transport. Use only the synthetic fixtures in automated tests. Test your own build privately on the target homelab after deployment.
