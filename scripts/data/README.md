# Captured companion modifier data

`TamedBeastMods.lua` is the unchanged generated catalogue from
[PathOfBuilding-PoE2 PR #2147](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2147),
commit `f2593c10320df3faf74008081548e433d5e849e8`. It contains 68 canonical
`PlayerMonster...` records. The installer verifies its SHA-256 before copying
it into the private engine. The upstream MIT license applies to the source;
the upstream file identifies the monster data as copyright Grinding Gear Games.
The upstream source license is included in `LICENSE.PathOfBuilding`.

`patch_companion_states.py` adds narrow headless import/persistence and native
actor calculations. Unsupported generated-stat comments, empty modifier lists,
and unmapped behavior remain diagnosed. Canonical IDs and unambiguous English
labels can identify a captured modifier; ambiguous labels do not select an
arbitrary tier. Unknown labels never enter public calculation results.

Additional numeric effects were checked against the
[Tame Beast Archnemesis table](https://poe2db.tw/us/Tame_Beast): increased stun
buildup, extra Energy Shield from Life, multiplicative area of effect, and
all-damage ailment eligibility. `patch_beast_auras.py` implements captured
Physical/Haste ally auras with explicit source survival and recipient proximity,
separate intrinsic modifiers and native strongest-instance merging. The special
10% minimum Chill versus ordinary 30% threshold, other aura families and periodic
effects remain partial. No modifier is inferred from the beast's species.

Natural Order's optional nine-spirit snapshot uses the monster **Haunted**
column in [Azmeri Spirit](https://poe2db.tw/us/Azmeri_Spirit). These modifiers
apply only to the actual unique Tamed Beast while the passive is allocated.
Unknown is the default. The static snapshot does not include periodic summoned
spirit animals, their attack rotation, or an assumed distribution of random
spirits. Ox slow potency is not modeled by the pinned engine.

[Wild Protector](https://poe2db.tw/us/Wild_Protector) supplies Maul's 5% of hit
damage as armour break. This computes armour removed by the evaluated hit,
including armour-break scaling, without marking the target already fully
broken. [Romira's Requital](https://poe2db.tw/us/Romiras_Requital) supplies the
support-scoped 200% recoup of damage actually redirected to that Companion;
it does not become generic player recoup.
