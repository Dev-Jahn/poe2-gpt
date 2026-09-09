# MCP tool reference

Tools declare typed input schemas and operation-specific annotations. Inspect the live tool list for the authoritative schema. Optional tools are registered only when their backing service is configured. Most equipment and engine tools take one `request` object; build-summary tools take `build_id` directly.

| Tool | Purpose | Enablement |
|---|---|---|
| `list_leagues` | Exact PoE2 league names and slugs | Default |
| `list_currency_categories` | Available categories and reference currencies | Default |
| `get_currency_prices` | Category prices, substring filter, pagination | Default |
| `search_currency_prices` | Names, IDs, and common orb aliases | Default |
| `quote_currency_items` | Value up to 30 exact item IDs and quantities | Default |
| `search_game_terms` | Verified English/Korean names, PoE2DB keys and source links | Default, offline |
| `get_trade_integration_status` | Adapter availability and support scope | Default |
| `prepare_equipment_search` | Conditions for a manual trade-site search | Default |
| `search_trade_stats` | Find canonical numeric trade stat IDs using English or Korean | Trade enabled |
| `search_trade_equipment` | Filter equipment and retain a bounded search | Trade enabled |
| `get_trade_search_results` | Page through retained listings | Trade enabled |
| `get_equipment_dataset` | Imported equipment dataset summary | Equipment directory |
| `search_equipment_candidates` | Filter imported candidates | Equipment directory |
| `optimize_equipment_upgrades` | Optimize explicit item-stat totals | Equipment directory |
| `recommend_trade_upgrades` | Compare retained trade candidates to an equipment dataset | Equipment directory + trade |
| `get_build_summary` | Numbers saved in an externally imported build | Projection directory |
| `get_build_passive_nodes` | Bounded pages of numeric passive-node IDs | Projection directory |
| `get_build_equipment` | Equipped or saved item IDs and complete modifier/property pages | Projection directory; native detail with engine |
| `inspect_build` | Equipment, skills/supports, saved sets, configuration and passive effects | Engine socket |
| `get_build_diagnostics` | Complete immutable calculation/candidate diagnostic pages | Engine socket |
| `get_trade_item_details` | Listing names, known/unknown modifier descriptions | Trade enabled |
| `get_tool_runtime_status` | Process-local latency/error counters and safe error traces | Default |
| `get_pob_engine_status` | Private worker and pinned engine status | Engine socket |
| `recalculate_build` | Recalculate the saved active configuration | Engine socket |
| `validate_build_equipment` | Check supported level, attribute, slot, and gem requirements | Engine socket |
| `compare_build_equipment` | Compare up to three saved-item replacements | Engine socket |
| `recommend_pob_trade_upgrades` | Optimize trade candidates with PoB and equipment validation | Engine socket + trade |
| `list_account_characters` | Public account characters and league slugs | Character socket |
| `get_character` | Account tag + character name → automatic private Ninja import | Character socket |
| `import_pob_attachment` | ChatGPT `.txt` file reference → private import | Character socket + host fileParams support |
| `refresh_character` | Explicit Ninja refresh with cooldown | Character socket + per-user Ninja session |

The minimal configuration exposes 9 tools; all optional services together expose 31. Disabling trade removes its search and recommendation tools. Worker tools do not require the separate projection or manual equipment dataset services.



The two character-entry flows return build IDs for the existing engine tools. The three import/refresh tools declare `readOnlyHint=false`; refresh also declares `idempotentHint=false`. No raw-content or host-path argument is accepted. See [characters](characters.md).

## Currency response semantics

Prices are reference-currency units per one item. `retrieved_at` is the successful fetch time. `source_updated_at=null` means Scout has not supplied the current price's observation time. `latest_history_bucket_at` is a history-bucket label, not a substitute timestamp. `source_quantity` is source metadata, not executable stock or order-book depth.

The SQLite snapshot cache lasts five minutes. Transient failures use bounded retries; 429 responses apply cooldowns. Stale data is returned only when explicitly requested, with an age limit and stale status. Report partial and missing prices rather than estimating unknown values.

Supported category families include `currency`, `fragments`, `runes`, `essences`, `ultimatum`, `expedition`, `ritual`, `vaultkeys`, `breach`, `abyss`, `uncutgems`, `lineagesupportgems`, `delirium`, `incursion`, `idol`, `verisium`, and `vaal`. Discover availability per league instead of assuming every category is priced.

## Identifier flow

Currency rows and reference units retain their English `name` and IDs and add `name_ko` plus a Korean source URL when verified. Korean exact names and substrings can be searched directly. Trade listings add `base_type_ko`; character summaries and selected engine skills add verified Korean labels where available. Use `search_game_terms` for other item, skill or mechanic names. Missing or ambiguous mappings remain untranslated. A localized name is not evidence that its effect is calculated. See [localization](localization.md).

Trade-stat search joins official English and Korean metadata by exact `stat_id`, returning canonical `text` and verified `text_ko` alongside sources, translation status and retrieval time. Korean metadata failures leave English requests usable; if translations are unavailable, a Korean query with no matches does not establish that the stat does not exist. Metadata is cached for six hours. Follow `next_offset`, since long Korean text may reduce the number of entries that fit in one response.

Engine outputs distinguish the selected skill and actor, explicit minion metrics, and whether FullDPS was configured. Do not use player DPS to assess a minion skill or treat absent FullDPS as zero. Inspect engine source/data pins, validation status and issue counts before making equipment recommendations. Truncated diagnostic details preserve the full issue count.

Search for currency before quoting exact item IDs. Discover trade stat IDs before submitting filters. Reuse short server-side trade search IDs instead of the upstream query token. For private calculations, supply only the opaque ID returned by `get_character` or `import_pob_attachment`.

Trade handles expire after ten minutes. Engine trade optimization accepts up to four searches, 32 selected unique listings, three slot changes, and 64 affordable combinations. Narrow an oversized search explicitly; the server does not silently prune candidates and claim a global optimum.

## Complete inspection and recommendation flow

Call `get_character` for the latest published Ninja model at request time. Read
`upstream_checked_at_epoch` and `source_model_version`; identical build-ID reuse
is content deduplication, not a stale fallback. Use `get_build_equipment` with a
slot (for example `ring_left`) or saved ID; omit both to discover IDs. Use
`inspect_build` with `section=sets` to discover alternate sets, `skills` for groups
and supports, `configuration` for saved/default/override/effective values, and
`passives` for allocated effects. `configuration_key` narrows a setting. Follow
`next_offset`; item details include all placements, active variants and flags.

For purchases, confirm the purpose and weights/constraints, search official stat
IDs, use exact name/base/level and AND/count groups as needed, and inspect listing
details. `proxy_optimization_eligible` concerns the item-stat proxy only. PoB
eligibility separately checks equipment, each requested metric, assumptions and
league. For attachments, explicitly declare `declared_character_league`; Ninja
origins are verified using the catalog's explicit league name/slug pair, including
hardcore variants and historical abbreviations. Both the model league identifier
and origin URL slug must agree with that pair. Use `mode=restore_validity` for
minimum-cost repair.

`get_build_diagnostics` sections include `issues`, `mechanics`, `stats`,
`metric_coverage`, `deltas`, `inputs`, `combat_scenario`, and `candidates`.
`candidate_index` retrieves any evaluated candidate's snapshot details. Mechanic
pages map required inputs to public configuration/scenario fields or explicitly
state that no exposed input fully resolves them. Receipts expire after one hour,
capacity eviction or restart; recalculate on expiration. Validation returns a
compact report at the same compute cost as recalculation.

Errors carry safe codes, recovery categories/actions and trace IDs. Trade status
reports cooldown or operator intervention separately from adapter enablement.
Currency responses have explicit DTOs, including null/partial price semantics.
