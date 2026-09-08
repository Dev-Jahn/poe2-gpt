# Forbidden Rites calculation coverage

The 0.10 integration targets PoE2 0.5.5 with compatibility revision
`forbidden-rites-0.5.5-v3`. Game data, parsed text, calculation coverage, and
complete character input are separate requirements. An imported character can
have current data while still lacking enough information for a verified upgrade.

## Implemented mechanics

| Mechanic | Calculation and validation | Remaining input or scope |
|---|---|---|
| Way of the Stonefist | Use already transformed Fists of Stone and their supplied rolls; exempt only glove attributes | Ordinary glove candidates need their actual transformed data. No midpoint roll conversion or verification of an original-to-transformed affix relationship |
| Charges, Profusion and retention | Per-event generation, caps, expiry, retention and Regulation consumption in an explicit event schedule; compatible skill/support conditions | A hypothetical schedule does not establish live charge generation or sustainable DPS |
| Ally charge grants | Per-hit expected outgoing grants for each charge type | These grants do not automatically increase the player's charges |
| Mending Deflection and recoup | Conditional ES recharge; deflected-hit Life recoup and Romira's redirected-hit recoup over the supplied timeline | Requires hit timing and applicable damage; reports potential recovery without inventing resource deficits |
| Mountain's Teachings | Explicit stack snapshot changes eligible attack damage and Stun Threshold; scheduled gain, spending and small-hit reduction | Hit reduction needs damage after Armour/Resistance and before damage-taken modifiers; no inferred stack uptime |
| Offering Life | Separate Bone, Pain and Soul Offering spike Life with applicable minion modifiers and supports | No fabricated spike attacks, explosion frequency, or steady-state explosion DPS |
| Companion composition | Distinct type limits, pack-as-one counting, Wild Protector exemption, unique beast limits and generated grant mirrors | An enabled saved group is not evidence that two mirrored entries represent two creatures |
| Wolf Pack | Pack size and the full finite Life pool for damage redirected to Companions | A selected minion's DPS still describes that selected actor |
| Spirit Vessel | Native copies of enabled socketed Bear/Wolf/Wyvern attacks with actual gem level, quality, stat set and compatible supports; separate monster actor, eligible distinct-skill bonus and Life pool | Selected copied attack is explicit. Non-attack copies, AI rotation and resource/corpse uptime remain unresolved |
| Captured beast modifiers | Pinned catalogue of 68 canonical modifier IDs; mapped numeric families include Life, damage, speed, resistances, critical strikes, gain-as damage, area, ES, ailment eligibility and recovery | Catalogue membership does not mean every effect is implemented. Missing, ambiguous or unmapped rolls remain partial; species alone cannot recover rolls |
| Captured beast ally auras | Separate intrinsic and emitted Physical/Haste modifiers, explicit living sources and nearby recipients, native strongest-instance stacking and recipient effect | Missing source or recipient state remains partial; no inferred AI positioning or aura uptime |
| Captured All Damage Chills | Eligible hit and critical-hit magnitude candidates, prohibitions, avoidance and noncritical ailment mode | The special 10% minimum versus the ordinary 30% threshold remains unresolved; no automatic small-hit Chill or inferred uptime |
| Natural Order | Explicit no-spirit or selected haunted-monster spirit state, unique Tame Beast scope and mapped static modifiers | Unknown is not a random selection. Periodic spirit summons, rotation and Ox slow potency remain partial; player possession uses different values |
| Companion Armour Break | Wild Protector Maul and mapped captured-beast physical-hit Armour Break use applicable actual hit damage and respect inability to break armour | Leap-distance timing and incomplete captured modifiers remain diagnosed |
| Bonded gold quantity | Non-combat quantity modifier under its actual Bonded condition | It is neither a combat damage modifier nor a currency price |
| Verglas | Supported-skill extra Cold damage in complete 2,000 crystal-Life increments | Recent destruction defaults off; differing crystal sources need an explicit saved Life override |
| Selected skill weapon set | Preserve saved `set1`/`set2` selectors and activate a provable common context through PoB's weapon swap action | Mixed simultaneous weapon contexts remain unsupported; the reported `active_weapon_set` is the evaluated context |
| Item and passive granted skills | Recalculate source-capped item skill levels from current attributes and character level; scale passive grants with character level | Missing or ambiguous grant sources remain indeterminate. Ordinary socketed gems retain their requirements |
| Ghost Dance | Actual Shroud cap and generation timer; conditional Evasion-based ES regeneration with native recovery modifiers | Requires an explicit recently-lost-Shroud state; no inferred hit history |
| Hollow Focus | Native bell spawn timer, compatible bell limit, duration and selected shockwave damage | Requires bell-hit events for damage frequency; spawn frequency is not hit frequency |
| Hollow Form | Native copied-attack penalties and restrictions; explicit channel rate and charged-use fraction project image damage and unrounded costs | Uses one image's average hit, without multiplying attack speed twice. Charge/Mana sustain, overlap and actual contact are not proven |
| Tempest Bell | Actual combo/limit/duration data and shockwave snapshot using valid prior hits, distinct elemental ailment types and knockback distance | Prior hits must be below the actual destruction limit. Combo, hit sequence and uptime require events |
| Wind Dancer | Actual generation interval and explicit current-stage Evasion multiplier | A full-refill bound does not identify the live timer phase |
| Refutation | Explicit buff and Ward expenditure, Light Stun threshold/immunity, block restrictions and duration/cooldown cycle | Heavy Stun can end the buff; active state requires incoming-hit assumptions and does not imply that an enemy was Parried |
| PoE2 damage leech | Total post-mitigation hit capped at 40,000 before type-specific leech; proportional damage types, amount modifiers, one-instance recovery and speed modifiers | Current numerical monster resistance is not verified. Supply resistance explicitly; recovery uptime remains a separate assumption |
| Mana Drain and leech transfers | Flat Mana Drain with its own recovery speed; supported instant recovery, Life-to-ES conversion and Mana recovery copied to ES | Flat Mana Drain is not damage-based leech. Recovery needs resource deficits and applicable conditions |
| Impale | Current physical-hit magnitude and infliction chance; explicit existing strongest Impale added once to the selected eligible player attack before target mitigation | No inferred repeated-stack DPS. Extraction cannot affect spells, minions, unrelated Full DPS groups or skills prohibited from extracting; sustain is unresolved |
| Maim, Blind and conditional hit buffs | Hit chances and explicit target states; compatible Thrill of the Kill, Culling Strike and Onslaught buff snapshots | Chance to trigger does not prove the buff is active. Behead's unknown stolen rare modifiers remain partial |
| Curses and marks | Target-level eligibility, native curse/aura application and mark grouping; explicit compatible Charged Mark ground state | Mark activation is not inferred from skill presence; ground uptime requires a state assumption |
| Rite of Passage | Explicit equipped-charm possession and current mapped static player-spirit modifiers | Periodic spirit attacks, possession uptime and Ox slow potency remain partial |
| Reviewed upstream corrections | Canonical Cursed/Marked/Electrocuted conditions; stable socket/rune import round trips; Baryanic Leylines calculator radius | Narrow reviewed patches only; no wholesale branch merge or desktop UI changes |

Relevant source facts: [Stonefist](https://poe2db.tw/us/Way_of_the_Stonefist),
[Mending Deflection](https://poe2db.tw/us/Mending_Deflection),
[Offering Spike](https://poe2db.tw/us/Offering_Spike),
[Companions](https://poe2db.tw/us/Companion),
[Trusted Kinship](https://poe2db.tw/us/Trusted_Kinship),
[Verglas](https://poe2db.tw/us/Verglas), and reviewed
[PoB2 Verglas PR #2390](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2390).
Spirit Vessel uses [its public monster record](https://poe2db.tw/us/DNT_Spirit_Vessel)
and [skill data](https://poe2db.tw/us/Spirit_Vessel). The captured-modifier catalogue
is the reviewed data subset of [PR #2147](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2147),
with independent calculations checked against [Tame Beast](https://poe2db.tw/us/Tame_Beast).
The 68 catalogue entries are not a claim to cover every current PoE2DB table row.
[Natural Order](https://poe2db.tw/us/Natural_Order) uses the haunted-monster column
of [Azmeri Spirit](https://poe2db.tw/us/Azmeri_Spirit), while
[Rite of Passage](https://poe2db.tw/us/Rite_of_Passage) uses player possession.
[Wild Protector](https://poe2db.tw/us/Wild_Protector) and
[Romira's Requital](https://poe2db.tw/us/Romiras_Requital) retain their separate
hit and redirected-damage scopes.

Martial calculations follow [Ghost Dance](https://poe2db.tw/us/Ghost_Dance),
[Hollow Focus](https://poe2db.tw/us/Hollow_Focus),
[Hollow Form](https://poe2db.tw/us/Hollow_Form),
[Tempest Bell](https://poe2db.tw/us/Tempest_Bell),
[Wind Dancer](https://poe2db.tw/us/Wind_Dancer) and
[Refutation](https://poe2db.tw/us/Refutation). See the
[combat scenario reference](combat-scenarios.md) for Mountain's Teachings,
charges and recovery event semantics.

The leech implementation follows [Life Leech](https://poe2db.tw/us/Life_Leech),
[Mana Leech](https://poe2db.tw/us/Mana_Leech),
[Energy Shield Leech](https://poe2db.tw/us/Energy_Shield_Leech),
[Mana Drain](https://poe2db.tw/us/Mana_Drain) and
[Vaal Pact](https://poe2db.tw/us/Vaal_Pact). The resistance table available in
[PR #1938](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/1938)
has provisional provenance; without an explicit resistance override, the result
requests that input. Its leech formula and the old stack-DPS model in
[PR #1820](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/1820)
are not adopted. Extraction follows the current [Impale](https://poe2db.tw/us/Impale)
definition and needs an explicit target magnitude.

Hit-buff scopes follow [Maim](https://poe2db.tw/us/Maim),
[Blindside](https://poe2db.tw/us/Blindside),
[Thrill of the Kill II](https://poe2db.tw/us/Thrill_of_the_Kill_II),
[Culling Strike II](https://poe2db.tw/us/Culling_Strike_II),
[Behead II](https://poe2db.tw/us/Behead_II) and
[Onslaught](https://poe2db.tw/us/Onslaught). Curse and ground-state boundaries
follow [Temporal Chains](https://poe2db.tw/us/Temporal_Chains),
[Charged Mark](https://poe2db.tw/us/Charged_Mark) and
[Activating Marks](https://poe2db.tw/us/Activating_Marks).

Weapon selector preservation and granted-skill levels follow a narrow review of
[PR #2498](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2498);
the broader cross-skill environment changes are not applied. The three additional
source corrections follow [#2378](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2378),
[#2367](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2367) and
[#2381](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2381).
Exact reviewed heads and deferred work are recorded in the
[0.10 upstream review](upstream-review-010.md).

## Reading results

`stats` describe the saved build with any explicitly supplied, bounded
[`configuration`](calculation-assumptions.md) overrides. Omitted values retain
saved configuration; the request does not change the stored original build.
`mechanics` add bounded,
named numeric details with a status and `required_inputs`. A `calculated`
mechanic means that particular calculation ran; it is not a whole-build
certificate. `partial`, `unsupported`, and `requires_configuration` must be
reported alongside their numbers. `inactive` means the effect is not active in
the evaluated configuration.

Unknown game-visible stats on effective skill instances and compatible
supports produce `unsupported_skill_stat` with canonical skill/stat IDs.
Disabled groups, incompatible supports and display-only category metadata are
not treated as active combat effects. This closes silent omissions for missing
stat mappings, but a mapped stat may still have incomplete upstream behavior.
`granted_skill_source_unresolved` means an imported item/passive skill cannot be
matched to one current active source; its saved level cannot verify an upgrade.

Details are limited to 16 issues and 16 mechanics and may be shortened further
to preserve the 8 KiB public response limit. `issue_count`, `mechanic_count`,
`issues_truncated`, and `mechanics_truncated` preserve that distinction. Validation
and numeric character results are not upgraded when details are shortened.

Captured beast exports can omit individual rolled modifiers. Canonical imported
metadata or a bounded `captured_beast_mods` assumption can supply a known roll
list; `complete=false` preserves incomplete status. A known species does not
recover those rolls. Raw exports, private text and file paths are never
requested as model input to fill missing information. The existing account/name
and attached `.txt` import workflows remain the only character entry points.

## Recommendation eligibility

Equipment optimization requires a passing baseline and passing candidate
calculations with all requested metrics. The same supplied configuration is used
for the baseline and every candidate. Missing data, unresolved combat
assumptions, unsupported effects and uncertain equip sequences remain excluded.
These checks do not claim universal coverage of every current upstream mechanic.

The regression suite uses synthetic public game data only. Add a numerical
differential test and a counterexample for each new source patch; preserve the
exact source/data pins and increment the compatibility revision when calculation
semantics change. Real account payloads do not belong in public fixtures.
