# Forbidden Rites calculation coverage

The 0.9 integration targets PoE2 0.5.5 with compatibility revision
`forbidden-rites-0.5.5-v2`. Game data, parsed text, calculation coverage, and
complete character input are separate requirements. An imported character can
have current data while still lacking enough information for a verified upgrade.

## Implemented mechanics

| Mechanic | Calculation and validation | Remaining input or scope |
|---|---|---|
| Way of the Stonefist | Use already transformed Fists of Stone and their supplied rolls; exempt only glove attributes | Ordinary glove candidates need their actual transformed data. No midpoint roll conversion or verification of an original-to-transformed affix relationship |
| Additional charges and Charge Profusion | Per-event extra-charge probabilities from the actual generating skill and its supports | A charge-gain event sequence is needed to establish sustained charge counts |
| Perpetual Charge and The Fabled Stag | Combined charge-retention probability and expected removed fraction | Burst damage does not imply a sustainable attack rate |
| Charge Regulation | Consumption interval including quality, and demand per charge type | Reported demand requires charges to be available; it is not an observed generation rate |
| Ally charge grants | Per-hit grant chance for each charge type | These grants do not automatically increase the player's charges |
| Mending Deflection | Conditional ES recharge and Life recoup per deflected hit | Recovery over time depends on incoming hit timing and damage; no generic recoup is applied to other hits |
| Offering Life | Separate Bone, Pain and Soul Offering spike Life with applicable minion modifiers and supports | No fabricated spike attacks, explosion frequency, or steady-state explosion DPS |
| Companion composition | Distinct type limits, pack-as-one counting, Wild Protector exemption, unique beast limits and generated grant mirrors | An enabled saved group is not evidence that two mirrored entries represent two creatures |
| Wolf Pack | Pack size and the full finite Life pool for damage redirected to Companions | A selected minion's DPS still describes that selected actor |
| Spirit Vessel | Verified Life actor, quality/minion Life modifiers, eligible distinct-skill bonus, and damage-redirection Life pool | Copied attacks and AI rotation remain unsupported; the bonus is not a complete damage calculation |
| Natural Order | Unique identity from the pinned generated data and applicable movement modifier | Random Azmeri spirit behavior requires additional state and remains diagnosed |
| Bonded gold quantity | Non-combat quantity modifier under its actual Bonded condition | It is neither a combat damage modifier nor a currency price |
| Verglas | Supported-skill extra Cold damage in complete 2,000 crystal-Life increments | Recent destruction defaults off; differing crystal sources need an explicit saved Life override |
| Selected skill weapon set | Preserve saved `set1`/`set2` selectors and activate a provable common context through PoB's weapon swap action | Mixed simultaneous weapon contexts remain unsupported; the reported `active_weapon_set` is the evaluated context |
| Item and passive granted skills | Recalculate source-capped item skill levels from current attributes and character level; scale passive grants with character level | Missing or ambiguous grant sources remain indeterminate. Ordinary socketed gems retain their requirements |

Relevant source facts: [Stonefist](https://poe2db.tw/us/Way_of_the_Stonefist),
[Mending Deflection](https://poe2db.tw/us/Mending_Deflection),
[Offering Spike](https://poe2db.tw/us/Offering_Spike),
[Companions](https://poe2db.tw/us/Companion),
[Trusted Kinship](https://poe2db.tw/us/Trusted_Kinship),
[Verglas](https://poe2db.tw/us/Verglas), and reviewed
[PoB2 Verglas PR #2390](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2390).
Spirit Vessel actor data is verified against [its public monster record](https://poe2db.tw/us/DNT_Spirit_Vessel).
Weapon selector preservation and granted-skill levels follow a narrow review of
[PR #2498](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2498);
the broader cross-skill environment changes are not applied.

## Reading results

`stats` retain the saved configuration's PoB results. `mechanics` add bounded,
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

Captured beast exports can omit individual rolled modifiers. A known species
does not recover those rolls. Raw exports, private text and file paths are never
requested as model input to fill missing information. The existing account/name
and attached `.txt` import workflows remain the only character entry points.

## Recommendation eligibility

Equipment optimization requires a passing baseline and passing candidate
calculations with all requested metrics. Missing data, unresolved combat
assumptions, unsupported effects and uncertain equip sequences remain excluded.
These checks do not claim universal coverage of every current upstream mechanic.

The regression suite uses synthetic public game data only. Add a numerical
differential test and a counterexample for each new source patch; preserve the
exact source/data pins and increment the compatibility revision when calculation
semantics change. Real account payloads do not belong in public fixtures.
