# Trade search and item-stat optimization

The adapter queries the official trade website's `trade2` web endpoints. This is experimental and separate from the documented GGG OAuth developer API. It sends no account cookie or OAuth token, and it has no purchasing, whispering, or in-game action capability.

| Request | Purpose |
|---|---|
| `GET /api/trade2/data/leagues` | League metadata |
| `GET /api/trade2/data/filters` | Supported categories and filters |
| `GET /api/trade2/data/stats` | Numeric stat identifiers |
| `POST /api/trade2/search/{league}` | Typed equipment search |
| `GET /api/trade2/fetch/{ids}?query={token}` | Fetch at most 10 listing IDs per request |

These paths are on `https://www.pathofexile.com`. League names are URL-encoded. Query tokens stay in process memory behind short search IDs; result retention and response sizes are bounded. The server returns selected listing properties and links, not seller whisper payloads.

Search filters are validated against current metadata. Requests are serialized with a conservative initial interval, dynamic `X-Rate-Limit-*` windows, and `Retry-After` cooldowns. Limits are process-local and do not coordinate with other overlays sharing the IP. Authentication, challenge HTML, or 401/403 responses disable further trade calls until the operator resolves access and restarts. The adapter does not solve CAPTCHAs, rotate proxies, or extract browser cookies.

Request-shape references: [Exiled Exchange 2 search implementation](https://github.com/Kvan7/Exiled-Exchange-2/blob/cf58adf17a06fe453da47f3672803a33594abcf6/renderer/src/web/price-check/trade/pathofexile-trade.ts), [Sidekick trade service](https://github.com/Sidekick-Poe/Sidekick/blob/cbe063ca3dbb14ef990fe03cfae611581e8e724b/src/Sidekick.Apis.Poe.Trade/Trade/ItemTradeService.cs), and [GGG developer guidance](https://www.pathofexile.com/developer/docs). No overlay source is bundled.

## Imported equipment model

The optional equipment dataset is a typed snapshot of current gear and candidate item metrics. It supports exact enumeration within a bounded candidate space, explicit stat weights, minimum totals, budget, reserve, and maximum changed slots. This simpler path evaluates item-stat totals; it does not recalculate character life, DPS, gems, or equipment requirements.

Run the synthetic example outside ChatGPT:

```bash
python examples/make_equipment_example.py
poe2-equipment-import --input equipment-example.json --projection-dir /absolute/path/equipment-projections
```

Configure `POE2_EQUIPMENT_PROJECTION_DIR` and pass the returned dataset ID to equipment tools. `recommend_trade_upgrades` adds retained search listings to the same item-stat model. It excludes unknown/conditional item mechanics and reports unscored modifiers. Weapons can be searched but are not part of this simpler optimizer's supported slot set.

For final character metrics and supported equipment checks, use the [private PoB optimizer](pob-engine.md). Both optimizers are restricted to supplied or retained candidates; neither guarantees a market-wide cheapest item, executable currency conversion, or listing availability at purchase time.
