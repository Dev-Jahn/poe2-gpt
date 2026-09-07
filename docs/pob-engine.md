# Private PoE2 PoB engine

The optional Linux worker uses the upstream headless PoE2 Path of Building engine. The MCP server communicates over a private Unix socket; only the worker mounts raw builds. Calculations use a fresh LuaJIT process and the saved active tree, item set, weapon set, skill group, and configuration. They do not fetch a live character or automatically enable favorable combat assumptions.

## Pinned dependencies

| Component | Pin |
|---|---|
| PathOfBuilding-PoE2 | `3887ae68a6a6b8bb7b41d1b61998f1aa184201e4` |
| LuaJIT | `24c20c94e7db195b640854619577441f9b4bc6be` |
| luautf8 | `0.2.0` |

Installers verify archive SHA-256 digests and retain licenses. Source is downloaded during setup, never auto-updated at runtime. See `scripts/install_pob_engine.py` and `scripts/install_lua_runtime.py` for digests and URLs. A PoB document's `Build.targetVersion=0_1` differs from passive-tree `treeVersion=0_5`; unsupported documents are rejected, and an outdated active tree is excluded from recommendations.

The integration uses [HeadlessWrapper.lua](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/blob/3887ae68a6a6b8bb7b41d1b61998f1aa184201e4/src/HeadlessWrapper.lua), the upstream [slot validator](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/blob/3887ae68a6a6b8bb7b41d1b61998f1aa184201e4/src/Classes/ItemsTab.lua), and [trade item importer](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/blob/3887ae68a6a6b8bb7b41d1b61998f1aa184201e4/src/Classes/ImportTab.lua).

## Validation

The worker checks supported level and attribute requirements, global requirement modifiers, slot/weapon restrictions, class restrictions, gem levels and attributes, support requirements, resource warnings, and unchanged equipment affected by a replacement. One physical item cannot occupy two slots.

For up to three replacements, it removes changed gear first and searches equip orders without crediting a new item's own attribute bonus in advance. This is a conservative sufficient condition. Temporary gear or retaining old gear longer may make other transitions possible; those are not exhaustively searched. Validating a current build checks its final state, not its historical equip sequence.

| Status | Meaning | Recommendation eligibility |
|---|---|---|
| `pass` | Supported checks passed in the selected configuration | Eligible |
| `fail` | A definite requirement or slot violation | Excluded |
| `indeterminate` | Unknown modifiers, custom mods, engine warnings, or unproven transition | Excluded |

Unsupported mechanics are not replaced with zeroes. A failed candidate scenario is excluded with a reason; an uncalculable baseline fails the request. The engine exposes selected numeric metrics and statuses only. Synthetic tests do not establish compatibility with every real build or game mechanic.

## Budget optimization

Use `search_trade_stats`, then `search_trade_equipment`, then pass short search IDs and the imported build ID to `recommend_pob_trade_upgrades`. The server sends candidate item payloads directly to the worker.

`maximize_score` maximizes an explicit weighted gain in final character metrics. `minimize_cost` finds the cheapest eligible retained combination satisfying minimum final metrics. Keeping current gear costs zero and is included. There is no sale-income, crafting-cost, or fee model.

Requests allow up to four searches, 32 selected unique listings, three changes, and 64 affordable combinations. Larger spaces fail before calculation; narrow them with `candidate_refs`. Scout supplies estimated FX when price currencies differ. Listing fetch freshness defaults to 300 seconds, and handles expire at ten minutes. Results are not a post-calculation availability check.

Supported candidate slots cover weapons, armor, and accessories, including uniques the engine can parse. Jewels, flasks, and charms are not exposed as trade replacement slots. Candidates with nested `socketedItems`, unknown bases, hidden modifiers, or unresolved mechanics are excluded. Trade items have `origin=trade_candidate` and `saved_item_id=null`; use `changes[].listing_ref`, never an internal temporary engine ID.

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
