# 0.12 review follow-up

This release addresses the follow-up review of main `b2bd844` (0.11.0).

## Inspection contract and worker calls

Required `records` survives JSON serialization even when empty. Unknown saved
item IDs, unknown configuration keys, empty slots and offsets past the end return
successful empty pages. Both offline and real-engine regressions call the actual
MCP session and validate structured output against each tool's output schema.

`get_build_equipment(slot=...)` now resolves the active item and weapon set inside
one private Lua projection. Each detail page uses one worker call, regardless of
the saved item's position. Inspection still loads PoB and calculates a baseline;
there is no inspection cache or calculation-free interpreter path in this release.

## Recommendation actions and receipts

Every unchanged slot means Keep. Equip uses a retained listing; Unequip uses
`saved_item_id=0` privately and costs zero. `max_changes` counts changed slots,
including removal. By default every occupied supported slot may be removed.
`unequip_slots` narrows that set; `[]` disables removals. Empty slots are excluded
from removal choices. Planning first reads the baseline to identify occupied slots.

The existing sequential validator tries action permutations with unchanged items
retained. Both weapon slots are checked after every transition: a main-hand
item's own slot check does not validate a shield still in the other hand.
It must prove shield removal before a two-handed replacement when the
opposite order is invalid. Removing useful attributes still invalidates dependent
equipment. Searches over 64 affordable plans fail explicitly; narrow
`candidate_refs`, `unequip_slots`, or `max_changes` instead of proxy pruning.

`get_build_diagnostics(section="candidates")` retains each candidate's slot,
action, listing reference, original price, normalized cost, status, violated
minimums, eligible rank, gain and selected flag. Snapshot issue pages remain
addressable by `candidate_index`. `section="excluded_listings"` records per-listing
prefilter reasons. All-excluded searches still retain a baseline receipt.
`section="inputs"` preserves objective, weights, constraints, budget/reserve,
candidate selection, removal scope and the FX snapshot, including its uncertainty.
All pages are bounded, copied and subject to receipt expiration. No raw item,
seller, whisper or original PoB is included.

## Instant Buyout and official-site handoff

`search_trade_equipment` defaults to `status="securable"`. The previously retained
official-filter fixture labels this option **Instant Buyout** and `available`
**Instant Buyout and In Person**. This fixture is historical evidence, not a new
capture of today's website. Runtime queries still validate the selected option
against current upstream metadata and fail if absent. Explicit status overrides
are respected. A price tag or an online seller alone is not treated as an
instant-buyout guarantee.

Results expose the actual query URL, selected status, `instant_buyout_only` and
`travel_link_supported=false`. The URL opens the official trade search; it does
not execute an in-game action. Use the official site's Travel to Hideout button
where available. No supported public URL implementing one-click travel from
ChatGPT has been verified. Live UI inspection was blocked by a human-verification
page during this work. We do not synthesize travel URLs, expose session tokens,
automate gold expenditure or substitute a normal search link for teleportation.
The [official asynchronous-trade FAQ](https://www.pathofexile.com/forum/view-thread/3828185)
describes merchant trading and buyer gold costs.

A separate UI investigation supplied this
[official frontend bundle](https://web.poecdn.com/dist/legacy/trade.d17c272e9c6a43635ff3d9779e4f14924da8fcf5.js).
Its reported `requestItem` path passes `listing.hideout_token` to
`whisperAccount`, which POSTs JSON to `apiUrl("whisper")`; direct whisper uses
`whisper_token` instead. This is source-level evidence supplied by another
session, not a successful action test here. The runtime base path, account
authentication, token binding and game-session routing were not verified.
A normal Markdown hyperlink cannot reproduce an authenticated JSON POST on the
official site's origin. An additional authorized integration would be needed;
this server does not collect official account cookies or issue that action.

## Static checks and validation scope

Inspection, receipt and plan-enumeration modules now require typed definitions
and check function bodies with mypy. This is a staged subset; all-module mypy
does not imply full strict typing. Ruff remains the existing fatal-error subset.
The 85% coverage threshold covers Python, while the separate x64/ARM real-engine
jobs check Lua behavior through synthetic regression cases. Repository protection
is an administrative setting independent of these source checks.

See `tests/test_review_011.py`, `tests/test_inspection_real.py`, and
`tests/test_unequip_trade_real.py` for executable acceptance cases. Release and
deployment claims must use the actual CI and operational results.
