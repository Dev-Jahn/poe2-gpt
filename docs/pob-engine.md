# Private PoE2 PoB engine

The optional Linux worker uses the upstream headless PoE2 Path of Building engine. The MCP server communicates over a private Unix socket; only the worker mounts raw builds. Calculations use a fresh LuaJIT process and the saved active tree, item set, weapon set, skill group, and configuration. They do not fetch a live character or automatically enable favorable combat assumptions.

## Pinned dependencies

| Component | Pin |
|---|---|
| PathOfBuilding-PoE2 | `fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15` |
| PoE2 0.5.5 data | `b3282b7a9111ed6c4ec6be643edf0806d7beb675` (37 reviewed data files from open PR #2505) |
| Companion compatibility | `forbidden-rites-0.5.5-v1` |
| LuaJIT | `24c20c94e7db195b640854619577441f9b4bc6be` |
| luautf8 | `0.2.0` |

Installers verify the source archive and each overlaid data file with SHA-256 and retain licenses. Health checks verify both source commits and the compatibility revision. The data snapshot updates Soul Cores, skill/base/modifier data, spectres, trade stat mappings, and the 0.5 passive tree. The 17 new 0.5.5 Soul Cores and existing Soul Core balance changes are included. A narrow importer correction preserves `explicitMods[].flags.desecrated` while retaining legacy modifier arrays. Eight exact crafting-only lines (item influence eligibility and guaranteed corruption change) are recognized as having no current combat-stat effect. Unknown combat modifiers remain diagnosed; no broad text pattern suppresses warnings. Source is downloaded during setup, never auto-updated at runtime. See `scripts/install_pob_engine.py` and `scripts/install_lua_runtime.py` for digests and URLs. A PoB document's `Build.targetVersion=0_1` differs from passive-tree `treeVersion=0_5`; unsupported documents are rejected, and an outdated active tree is excluded from recommendations.

The integration uses [HeadlessWrapper.lua](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/blob/fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15/src/HeadlessWrapper.lua), the upstream [slot validator](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/blob/fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15/src/Classes/ItemsTab.lua), and [trade item importer](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/blob/fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15/src/Classes/ImportTab.lua).

Every private calculation response includes all three provenance markers, and the MCP client requires an exact match before returning numbers. Missing markers from an older worker or mismatched deployments produce `engine_version_mismatch`. Public output schemas constrain revision formats without embedding the current pin as a schema constant or default. Updating pins alone therefore leaves tool metadata stable; adding metrics or changing tool contracts still requires the host's metadata refresh.

## Data coverage and upstream review

This is a versioned community calculation engine, not a promise that every current game mechanic is implemented. The latest upstream release on the review date (2026-09-08) was v0.23.1, and the 0.5.5 export remained an open PR. Only reviewed data files from [PR #2505](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2505) are overlaid; its UI changes are excluded. [PR #2504](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2504) independently covers the Soul Core changes already represented by that export. The importer correction follows [PR #2507](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2507), preserving compatibility with older upstream responses.

Open mechanics PRs require individual validation before inclusion:

- [Way of the Stonefist #2350](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2350) has ambiguous affix matching and midpoint conversion of transformed rolls; it is not applied.
- [Way of the Mountain #2073](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2073) matches older wording and omits conditional small-hit reduction; it is not applied. [Current Mountain's Teachings mechanics](https://poe2db.tw/us/Mountains_Teachings) require explicit buff state and hit-threshold calculations.
- [Tamed beast modifiers #2147](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2147) has numerous entries without calculations and incomplete aura behavior; it is not applied.
- [Runeforged unique variants #2511](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2511) changes editor/database variant selection and remains unmerged; existing actual item imports use their explicit base and modifier data.

A successful calculation or `pass` means the implemented validation checks passed. It does not establish full mechanical coverage of all upstream skills. Unparsed allocated passives and missing saved passive nodes produce explicit diagnostics instead of silently disappearing.

Two verified item mechanics have narrow integration fixes. The Vertex's **Equipment has no Attribute Requirements** applies to both weapons and other equipment, while gem attributes and level requirements remain enforced. [Forgotten Warden](https://poe2db.tw/us/Forgotten_Warden)'s Deflection per 50 missing Energy Shield uses the saved current-ES percentage, defaults to full ES, and floors each complete 50-point step. Explicit zero ES is honored; overflow ES and characters unable to have ES cannot create negative or phantom missing ES. Flat Deflection and converted Armour/Evasion contributions all receive applicable increased/more Deflection modifiers. `DeflectionRating` exposes the resulting player value. These source patches are guarded against the exact pinned source.

Remaining diagnosed gaps include transformed-affix validation for Stonefist, Offering spike maximum Life (the upstream engine has no separate spike actor/base-Life calculation), and some charge-generation/consumption effects. [Trusted Kinship](https://poe2db.tw/us/Trusted_Kinship)'s companion/non-companion reservation modifiers already calculate, but distinct-companion composition limits remain unsupported. The Natural Order's random Azmeri Spirit behavior and unimplemented tamed-beast modifiers are not inferred. Already transformed Fists of Stone imports retain their supplied item data; this integration does not run the unsafe transformation PR again.

## Validation

The worker detects active modern custom-modifier blocks, legacy custom modifiers, and disabled item-limit enforcement. Diagnostic details are deduplicated and limited to 16 entries, with fewer details when needed to keep a comparison or recommendation under 8 KiB. `issue_count` retains the original count and `issues_truncated` reports omitted details; statistics, equipped items, and validation status are preserved. Unknown passive diagnostics include numeric node IDs. The worker checks supported level and attribute requirements, global requirement modifiers, slot/weapon restrictions, class restrictions, gem levels and attributes, support requirements, resource warnings, and unchanged equipment affected by a replacement. One physical item cannot occupy two slots.

Active Chakra rune slots are also checked for unknown selected rune names, rune level requirements, and unparsed applied modifier lines. This closes a separate upstream import path that does not use ordinary equipped-item modifier validation.

For up to three replacements, it removes changed gear first and searches equip orders without crediting a new item's own attribute bonus in advance. This is a conservative sufficient condition. Temporary gear or retaining old gear longer may make other transitions possible; those are not exhaustively searched. Validating a current build checks its final state, not its historical equip sequence.

| Status | Meaning | Recommendation eligibility |
|---|---|---|
| `pass` | Supported checks passed in the selected configuration | Eligible |
| `fail` | A definite requirement or slot violation | Excluded |
| `indeterminate` | Unknown modifiers, custom mods, engine warnings, or unproven transition | Excluded |

Unsupported mechanics are not replaced with zeroes. A failed candidate scenario is excluded with a reason; an uncalculable baseline fails the request. The engine exposes selected numeric metrics and statuses only. Synthetic tests do not establish compatibility with every real build or game mechanic.

## Damage scope

`selected_skill` identifies the selected canonical engine skill and whether its damage actor is the player or a minion. Saved skill labels are never returned. `gem_name`, when available, is the pinned gem database name and can be localized separately.

`TotalDPS` and `CombinedDPS` retain their upstream player-output meaning. `MinionTotalDPS`, `MinionCombinedDPS`, and `MinionSpeed` come from the selected minion's output and are explicit optimization objectives. They describe the selected minion calculation, not an inferred sum across every summoned actor. `FullDPS` is omitted when no skills are configured for Full DPS; `full_dps_enabled` distinguishes an absent aggregate from a genuine zero result. Optimization requests for missing metrics fail rather than treating them as zero.

## Budget optimization

Use `search_trade_stats`, then `search_trade_equipment`, then pass short search IDs and the imported build ID to `recommend_pob_trade_upgrades`. The server sends candidate item payloads directly to the worker.

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
