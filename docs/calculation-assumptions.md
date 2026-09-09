# Calculation assumptions

Calculation, equipment-comparison and recommendation requests accept an optional
`configuration` object. It provides bounded assumptions for the saved build in a
fresh calculation process. The same configuration applies to the baseline and
every candidate; the stored original build remains unchanged. These values are
not a live observation, a saved-character refresh or proof of sustained uptime.

Every top-level field defaults to `null`/omitted, which retains saved
configuration. Explicit `false` and numeric `0` are meaningful and are not
replaced with defaults. An absent saved state can still require configuration;
omission does not enable a favorable buff. Unknown fields, non-finite numbers,
duplicate list entries and out-of-range values are rejected.

The table lists every field in
[`CalculationConfiguration`](../src/poe2_companion/calculation_config.py).

| Group | Field | Accepted value and meaning |
|---|---|---|
| Companion | `natural_order_spirit` | `unknown`, `none`, or one of the nine spirits below; a unique Tame Beast's haunted-monster state |
| Companion | `captured_beast_mods` | Up to 8 distinct skill-group records, described below |
| Companion | `companion_aura_sources` | Up to 8 distinct captured-beast source records with explicit survival and recipient proximity, described below |
| Companion | `spirit_vessel_skill_id` | Canonical ID of the selected eligible copied attack |
| Hollow Form | `hollow_form_attack_skill_id` | Canonical ID of the supported copied attack; supply all three Hollow Form fields together |
| Hollow Form | `hollow_form_channel_uses_per_second` | Number from 0 to 30; hypothetical channel uses per second |
| Hollow Form | `hollow_form_power_charge_use_fraction` | Number from 0 to 1; fraction of those uses that use a Power Charge |
| Damage | `impale_magnitude` | Number from 0 to 1,000,000,000; strongest existing target Impale for extraction by the selected eligible player attack |
| Recovery | `leech_recovery_uptime` | Number from 0 to 1; hypothetical fraction of time an instance actively recovers. Returns uptime-scaled active rates, not measured recovery or revised snapshot DPS |
| Recovery | `leech_resistance_percent` | Number from 0 to 100; assumed target resistance for damage-based leech |
| Hit buff | `onslaught_active` | Boolean; explicit Onslaught state, separate from chance to gain it |
| Hit buff | `thrill_of_the_kill_active` | Boolean; explicit compatible Thrill of the Kill buff state |
| Hit buff | `culling_strike_recent_cull` | Boolean; explicit recent-cull buff state; does not grant Culling Strike itself |
| Defence | `ghost_shroud_lost_recently` | Boolean; whether a Ghost Shroud was lost within the relevant recent window |
| Defence | `wind_dancer_stages` | Integer from 0 to 3; current Wind Dancer stages |
| Mountain | `mountain_teachings` | Integer from 0 to 30; current Mountain's Teachings stacks |
| Refutation | `refutation_active` | Boolean; supply together with `refutation_ward_spent` |
| Refutation | `refutation_ward_spent` | Number from 0 to 1,000,000; Ward spent for the buff, rather than maximum Ward |
| Tempest Bell | `tempest_bell_prior_hits` | Integer from 0 to 100; prior hits on the current bell, also required to be below its actual destruction limit |
| Tempest Bell | `tempest_bell_ailment_types` | Up to 3 distinct values: `fire`, `cold`, `lightning`; which elemental ailment types affect the bell. `[]` means none |
| Tempest Bell | `tempest_bell_knockback_metres` | Number from 0 to 100; knockback distance for the shockwave-area calculation |
| Target | `enemy_maimed` | Boolean; target Maim state, separate from hit chance |
| Target | `enemy_blinded` | Boolean; target Blind state, separate from hit chance |
| Mark | `charged_mark_ground_active` | Boolean; active ground from a compatible Charged Mark source |
| Charm | `rite_of_passage_spirit` | `none` or one of the nine spirits below; explicit possession from an available equipped Rite of Passage charm |

The nine spirit values are `bear`, `boar`, `cat`, `owl`, `ox`, `primate`,
`serpent`, `stag` and `wolf`. Natural Order's haunted-monster effects differ from
Rite of Passage's player possession. `natural_order_spirit="unknown"` does not
choose a spirit or claim a complete result; `none` explicitly selects no spirit.

Canonical skill IDs contain only ASCII letters, digits and underscores and are
1–120 characters long. A valid identifier still needs an eligible source in the
build. Supplying a state does not create a missing skill, support, charm or
compatible attack. Hollow Form's three fields must be supplied together or all
omitted; Refutation's two fields have the same rule.

Each captured-beast record contains:

| Field | Accepted value |
|---|---|
| `skill_group` | Integer from 1 to 10,000, unique within the request |
| `mod_ids` | Up to 4 distinct canonical `PlayerMonster…` IDs, at most 160 characters each; no guessed labels or arbitrary modifier text |
| `complete` | Required boolean stating whether the supplied list is complete; `false` keeps incomplete-roll diagnostics |

This catalogue contains 68 pinned IDs with a mapped subset of effects. A
syntactically valid but unknown ID cannot establish support; declaring a list
complete does not make unmapped effects calculable. Metadata from imports stays
private, and a known beast species cannot reconstruct missing rolled modifiers.

Each `companion_aura_sources` record contains a `skill_group`, required booleans
`source_alive` and `player_within_radius`, and `minion_recipients` (up to 32
records with a `skill_group` and required `within_radius` boolean). Source and
recipient group numbers must be unique within their respective lists. An active
captured beast must actually have a supported aura modifier. Supply a recipient
record for every other active minion group; an omitted recipient does not receive
the aura and keeps the projection partial. A dead source emits no aura.

The supported captured effects are Extra Physical Damage Aura (+40% increased
Physical Damage) and Haste Aura (+20% increased Attack and Cast Speed, +10%
increased Movement Speed), both with a 5-metre ally radius. The source's intrinsic
modifiers are separate: +40% physical damage, or +25% attack/cast and movement
speed. Its emitted ally aura is not applied to itself. Identical emitted auras
use the strongest instance for each recipient, following the game's
[buff stacking rule](https://poe2db.tw/us/Buffs). Recipient aura/buff effect
modifiers apply through the native calculator. This snapshot does not estimate
movement, AI behaviour or sustained coverage.

All Damage Chills now projects bounded hit and critical-hit magnitude candidates
from eligible damage types, including the captured modifier's 10% minimum.
PoE2DB's [Tame Beast](https://poe2db.tw/us/Tame_Beast) modifier specifies 10%, while
the [ordinary Chill rule](https://poe2db.tw/us/Chill) rejects magnitudes below 30%.
Their interaction is not established by these data, so this effect remains
partial: small-hit candidates do not become automatic enemy Chill or assumed
uptime. `CannotChill` and zero eligible damage produce no candidate.

Use [`combat_scenario`](combat-scenarios.md) for bounded charge, hit and recovery
event schedules. A snapshot and a schedule answer different questions: selecting
Mountain stacks can calculate their current damage effect, while a supplied hit
sequence is needed for threshold-dependent mitigation. Neither establishes live
game state. Impale sustain, bell contact, stolen rare modifiers, missing captured
rolls and unverified leech resistance remain explicit limitations when unresolved.

See the [coverage matrix](league-coverage.md) for source-backed scopes and
diagnostics, and the [upstream review](upstream-review-010.md) for accepted and
deferred changes. No raw PoB text, export code or server-side path belongs in a
configuration request; character import uses account/character lookup or an
attached `.txt` file.
