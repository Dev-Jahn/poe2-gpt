# Hypothetical combat schedules

`recalculate_build` accepts an optional `combat_scenario`. Equipment comparisons
apply the same supplied schedule to each candidate. This projection is separate
from the saved PoB charge configuration and never rewrites the imported build or
multiplies charge uptime estimates into PoB DPS.

Provide a horizon of at most 120 seconds, at most 64 ordered events, and the
initial count and remaining lifetime of each charge type. Existing Charge
Regulation requires an explicit first-tick time. Flicker uses require an explicit
occupation window: a static attack-speed snapshot cannot establish its actual
combat duration. Results identify their scope as
`hypothetical_supplied_event_schedule`.

| Event | Source-derived calculation |
| --- | --- |
| `external_charge_gain` | Apply the character's known extra-charge chance to a supplied qualifying base gain. |
| `killing_palm_kill` | Resolve the active skill group; use 1/2/3 base Power Charges for normal or magic/rare/unique kills, plus compatible support chances. |
| `armour_fully_broken` | Resolve the active supported skill; Armour Break II/III generate an Endurance Charge with 15%/20% probability. |
| `flicker_use` | Consume available Power Charges with retention, count virtual charges and Heightened benefits, and block Power gains throughout the supplied window. |
| `ally_hit` | Expected outgoing grants per eligible ally in Presence. The ally's charge cap, expiry, modifiers, and actual receipt are not inferred. |
| `incoming_hit` | Integrate Mending Deflection recovery from supplied post-mitigation damage and an explicit deflection outcome. |
| `companion_redirected_hit` | Integrate Romira's Requital recovery from damage actually redirected to the selected eligible companion. |
| `enemy_immobilised` | Gain Mountain's Teachings using the supplied effective monster Power and the passive's Surpassing chance. |
| `mountain_attack_use` | Spend one Mountain's Teaching on an eligible attack use or sustain. Flicker already performs this step in `flicker_use`. |
| `mountain_hit` | Test the 30% maximum-Life threshold after Armour/Resistances but before damage-taken modifiers, apply the conditional 40% reduction, and spend a Teaching. |

Describe each underlying event once. A Killing Palm kill records its charge
grant; use a separate `mountain_attack_use` for an activation that spends a
Teaching, since multiple culled enemies need not imply multiple skill uses.
`incoming_hit` and `mountain_hit` are alternative representations of an incoming
hit. The latter can also project deflected-hit recoup from its calculated damage.

The charge state machine retains a distribution over count and expiry for each
charge type. It applies charge caps, refresh on gain (including at cap), minimum
charges, Regulation ticks, consumption retention, and expiry. Reported totals
obey conservation of generated, blocked, wasted, removed, expired, and remaining
charges. It reports per-type marginal expectations, not joint all-charge uptime
or rotation DPS. Processing stops with a fixed issue code if two million state
operations are exceeded; partial result prefixes are discarded.

`gain_roll_model` is required. The two supported scenario assumptions are
`independent_nonrecursive_per_event` and
`independent_nonrecursive_per_base_charge`. They distinguish whether a multi-charge
base grant rolls its additional-charge effects once or once per base charge.
Same-type chance modifiers add; the additional random-charge roll is independent
and chooses uniformly among the three types. These are declared stochastic
models: the public game descriptions do not establish every detail of the
server's random-number implementation. A modelled event schedule is not evidence
that a charge state was sustained in live gameplay.

Recovery results are uncapped potential recovery. They account for elapsed time,
Recoup speed, and the saved Life recovery multiplier once. They do not model
overhealing, death, changing resource caps, or unprovided changes to recovery
modifiers. Recoup speed shortens the duration rather than increasing the total
percentage recovered. Damage already supplied after mitigation is not mitigated
a second time.

`configuration.mountain_teachings` selects an explicit snapshot count from 0 to
30. The native engine applies the active 15% more damage to eligible attacks and
50% more Stun Threshold. Hollow Form copies retain the attack benefit. The
conditional incoming-hit reduction is evaluated only for supplied `mountain_hit`
events; it is never installed as an unconditional damage-taken modifier.

Sources: [Charges](https://poe2db.tw/us/Charges),
[Killing Palm](https://poe2db.tw/us/Killing_Palm),
[Charge Profusion II](https://poe2db.tw/us/Charge_Profusion_II),
[Flicker Strike](https://poe2db.tw/us/Flicker_Strike),
[Charge Regulation](https://poe2db.tw/us/Charge_Regulation),
[Armour Break III](https://poe2db.tw/us/Armour_Break_III),
[Mending Deflection](https://poe2db.tw/us/Mending_Deflection),
[Recoup](https://poe2db.tw/us/Recoup),
[Mountain's Teachings](https://poe2db.tw/us/Mountains_Teachings),
[Monster Power](https://poe2db.tw/us/Monster_Power),
and reviewed upstream [PR #1860](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/1860),
[PR #1947](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/1947),
[PR #1541](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/1541),
and [PR #2073](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2073).
