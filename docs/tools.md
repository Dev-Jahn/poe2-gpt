# MCP tool reference

Tools declare typed input schemas and read-only annotations. Inspect the live tool list for the authoritative schema. Optional tools are registered only when their backing service is configured. Most equipment and engine tools take one `request` object; build-summary tools take `build_id` directly.

| Tool | Purpose | Enablement |
|---|---|---|
| `list_leagues` | Exact PoE2 league names and slugs | Default |
| `list_currency_categories` | Available categories and reference currencies | Default |
| `get_currency_prices` | Category prices, substring filter, pagination | Default |
| `search_currency_prices` | Names, IDs, and common orb aliases | Default |
| `quote_currency_items` | Value up to 30 exact item IDs and quantities | Default |
| `get_trade_integration_status` | Adapter availability and support scope | Default |
| `prepare_equipment_search` | Conditions for a manual trade-site search | Default |
| `search_trade_stats` | Find valid numeric trade stat IDs | Trade enabled |
| `search_trade_equipment` | Filter equipment and retain a bounded search | Trade enabled |
| `get_trade_search_results` | Page through retained listings | Trade enabled |
| `get_equipment_dataset` | Imported equipment dataset summary | Equipment directory |
| `search_equipment_candidates` | Filter imported candidates | Equipment directory |
| `optimize_equipment_upgrades` | Optimize explicit item-stat totals | Equipment directory |
| `recommend_trade_upgrades` | Compare retained trade candidates to an equipment dataset | Equipment directory + trade |
| `get_build_summary` | Numbers saved in an externally imported build | Projection directory |
| `get_build_passive_nodes` | Bounded pages of numeric passive-node IDs | Projection directory |
| `get_pob_engine_status` | Private worker and pinned engine status | Engine socket |
| `recalculate_build` | Recalculate the saved active configuration | Engine socket |
| `validate_build_equipment` | Check supported level, attribute, slot, and gem requirements | Engine socket |
| `compare_build_equipment` | Compare up to three saved-item replacements | Engine socket |
| `recommend_pob_trade_upgrades` | Optimize trade candidates with PoB and equipment validation | Engine socket + trade |

The standard configuration exposes 10 tools; all optional services together expose 21. Disabling trade removes its search and recommendation tools. Worker tools do not require the separate projection or manual equipment dataset services.

## Currency response semantics

Prices are reference-currency units per one item. `retrieved_at` is the successful fetch time. `source_updated_at=null` means Scout has not supplied the current price's observation time. `latest_history_bucket_at` is a history-bucket label, not a substitute timestamp. `source_quantity` is source metadata, not executable stock or order-book depth.

The SQLite snapshot cache lasts five minutes. Transient failures use bounded retries; 429 responses apply cooldowns. Stale data is returned only when explicitly requested, with an age limit and stale status. Report partial and missing prices rather than estimating unknown values.

Supported category families include `currency`, `fragments`, `runes`, `essences`, `ultimatum`, `expedition`, `ritual`, `vaultkeys`, `breach`, `abyss`, `uncutgems`, `lineagesupportgems`, `delirium`, `incursion`, `idol`, `verisium`, and `vaal`. Discover availability per league instead of assuming every category is priced.

## Identifier flow

Search for currency before quoting exact item IDs. Discover trade stat IDs before submitting filters. Reuse short server-side trade search IDs instead of the upstream query token. For private calculations, supply only the opaque ID returned by an external operator import.

Trade handles expire after ten minutes. Engine trade optimization accepts up to four searches, 32 selected unique listings, three slot changes, and 64 affordable combinations. Narrow an oversized search explicitly; the server does not silently prune candidates and claim a global optimum.
