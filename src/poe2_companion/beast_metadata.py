"""Private, immutable Ninja captured-beast metadata.

Model/export association requires one unique canonical gem/support signature
on each side. Positions are recorded only after that proof. Public species-name
template expansion must agree with the export's selected canonical minion ID.
Only known modifier IDs enter computation. Raw exports/properties never enter
public DTOs or logs, and this module never changes the original export bytes.

Canonical gem/species names: PathOfBuildingCommunity/PathOfBuilding-PoE2
Gems.lua and Spectres.lua at
b3282b7a9111ed6c4ec6be643edf0806d7beb675 (generated game data, GGG).
Modifier names: upstream PR2147 f2593c10320df3faf74008081548e433d5e849e8,
MIT-licensed Path of Building data; see scripts/data/LICENSE.PathOfBuilding.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from defusedxml import ElementTree

from .pob_io import decode_pob, project_pob

MAX_BEAST_METADATA_BYTES = 65536
_PROVENANCE = "unique_skill_support_signature"


def _normalise(value):
    return " ".join(value.casefold().split())


def _index(rows):
    result = {}
    for key, value in rows:
        key = _normalise(key)
        if key not in result:
            result[key] = value
        elif result[key] != value:
            result[key] = None  # Ambiguous public aliases are never guessed.
    return result
# Source-derived aliases: canonical support name and granted-effect ID.
_GEM_ROWS = [['Fire Attunement', 'SupportAddedFireDamagePlayer'],
 ['Rapid Attacks I', 'SupportRapidAttacksPlayer'],
 ['Rapid Attacks II', 'SupportRapidAttacksPlayerTwo'],
 ['Rapid Attacks III', 'SupportRapidAttacksPlayerThree'],
 ['Multishot I', 'SupportMultishotPlayer'],
 ['Multishot II', 'SupportMultishotPlayerTwo'],
 ['Nova Projectiles I', 'SupportNovaProjectilesPlayer'],
 ['Projectile Acceleration I', 'SupportProjectileAccelerationPlayer'],
 ['Projectile Acceleration II', 'SupportProjectileAccelerationPlayerTwo'],
 ['Projectile Acceleration III', 'SupportProjectileAccelerationPlayerThree'],
 ['Cold Attunement', 'SupportAddedColdDamagePlayer'],
 ['Heightened Accuracy I', 'SupportHeightenedAccuracyPlayer'],
 ['Heightened Accuracy II', 'SupportHeightenedAccuracyPlayerTwo'],
 ['Magnified Area I', 'SupportMagnifiedAreaPlayer'],
 ['Magnified Area II', 'SupportMagnifiedAreaPlayerTwo'],
 ['Lightning Attunement', 'SupportAddedLightningDamagePlayer'],
 ['Efficiency I', 'SupportEfficiencyPlayer'],
 ['Efficiency II', 'SupportEfficiencyPlayerTwo'],
 ['Supercritical', 'SupportIncreasedCriticalDamagePlayer'],
 ['Knockback', 'SupportKnockbackPlayer'],
 ['Life Leech I', 'SupportLifeLeechPlayer'],
 ['Life Leech II', 'SupportLifeLeechPlayerTwo'],
 ['Life Leech III', 'SupportLifeLeechPlayerThree'],
 ['Mana Leech', 'SupportManaLeechPlayer'],
 ["Oisin's Oath", 'SupportOisinsOathPlayer'],
 ['Chaos Attunement', 'SupportAddedChaosDamagePlayer'],
 ['Pierce I', 'SupportPiercePlayer'],
 ['Pierce II', 'SupportPiercePlayerTwo'],
 ['Pierce III', 'SupportPiercePlayerThree'],
 ['Heavy Swing', 'SupportMeleePhysicalDamagePlayer'],
 ['Rapid Casting I', 'SupportRapidCastingPlayer'],
 ['Rapid Casting II', 'SupportRapidCastingPlayerTwo'],
 ['Rapid Casting III', 'SupportRapidCastingPlayerThree'],
 ['Concentrated Area', 'SupportConcentratedAreaPlayer'],
 ['Bloodlust', 'SupportBloodlustPlayer'],
 ['Blind I', 'SupportBlindPlayer'],
 ['Blind II', 'SupportBlindPlayerTwo'],
 ['Fire Penetration I', 'SupportFirePenetrationPlayer'],
 ['Fire Penetration II', 'SupportFirePenetrationPlayerTwo'],
 ['Cold Penetration', 'SupportColdPenetrationPlayer'],
 ['Lightning Penetration', 'SupportLightningPenetrationPlayer'],
 ['Chain I', 'SupportChainPlayer'],
 ['Chain II', 'SupportChainPlayerTwo'],
 ['Chain III', 'SupportChainPlayerThree'],
 ['Fork', 'SupportForkPlayer'],
 ['Spell Echo', 'SupportSpellEchoPlayer'],
 ['Elemental Army', 'SupportElementalArmyPlayer'],
 ['Projectile Deceleration I', 'SupportProjectileDecelerationPlayer'],
 ['Projectile Deceleration II', 'SupportProjectileDecelerationPlayerTwo'],
 ["Vilenta's Propulsion", 'SupportVilentasPropulsionPlayer'],
 ['Ice Bite I', 'SupportIceBitePlayer'],
 ['Ice Bite II', 'SupportIceBitePlayerTwo'],
 ["Bhatair's Vengeance", 'SupportBhatairsVengeancePlayer'],
 ['Freeze', 'SupportFreezePlayer'],
 ['Shock', 'SupportShockPlayer'],
 ['Controlled Destruction', 'SupportControlledDestructionPlayer'],
 ['Elemental Focus', 'SupportElementalFocusPlayer'],
 ['Wildfire', 'SupportWildfirePlayer'],
 ['Bleed I', 'SupportBleedPlayer'],
 ['Bleed II', 'SupportBleedPlayerTwo'],
 ['Bleed III', 'SupportBleedPlayerThree'],
 ['Bleed IV', 'SupportBleedPlayerFour'],
 ['Poison I', 'SupportPoisonPlayer'],
 ['Poison II', 'SupportPoisonPlayerTwo'],
 ['Poison III', 'SupportPoisonPlayerThree'],
 ['Maim', 'SupportMaimPlayer'],
 ['Immolate', 'SupportImmolatePlayer'],
 ['Lasting Shock', 'SupportLastingShockPlayer'],
 ['Brutality I', 'SupportBrutalityPlayer'],
 ['Brutality II', 'SupportBrutalityPlayerTwo'],
 ['Brutality III', 'SupportBrutalityPlayerThree'],
 ['Momentum', 'SupportMomentumPlayer'],
 ['Arcane Surge', 'SupportArcaneSurgePlayer'],
 ['Withering Touch', 'SupportWitheringTouchPlayer'],
 ['Expand', 'SupportExpandPlayer'],
 ['Unleash', 'SupportUnleashPlayer'],
 ["Zarokh's Revolt", 'SupportZarokhsRevoltPlayer'],
 ['Close Combat I', 'SupportCloseCombatPlayer'],
 ['Close Combat II', 'SupportCloseCombatPlayerTwo'],
 ['Rage I', 'SupportRagePlayer'],
 ['Rage II', 'SupportRagePlayerTwo'],
 ['Rage III', 'SupportRagePlayerThree'],
 ['Feeding Frenzy I', 'SupportFeedingFrenzyPlayer'],
 ['Feeding Frenzy II', 'SupportFeedingFrenzyPlayerTwo'],
 ['Meat Shield I', 'SupportMeatShieldPlayer'],
 ['Meat Shield II', 'SupportMeatShieldPlayerTwo'],
 ["Brutus' Brain", 'SupportBrutusBrainPlayer'],
 ['Infernal Legion I', 'SupportInfernalLegionPlayer'],
 ['Infernal Legion II', 'SupportInfernalLegionPlayerTwo'],
 ['Infernal Legion III', 'SupportInfernalLegionPlayerThree'],
 ['Second Wind I', 'SupportSecondWindPlayer'],
 ['Second Wind II', 'SupportSecondWindPlayerTwo'],
 ['Second Wind III', 'SupportSecondWindPlayerThree'],
 ['Impending Doom', 'ViciousHexSupportPlayer'],
 ['Lifetap', 'SupportBloodMagicPlayer'],
 ["Atalui's Bloodletting", 'SupportAtaluiBloodlettingPlayer'],
 ['Behead I', 'SupportBeheadPlayer'],
 ['Behead II', 'SupportBeheadPlayerTwo'],
 ["Einhar's Beastrite", 'SupportEinharsBeastritePlayer'],
 ['Execute I', 'SupportExecutePlayer'],
 ['Execute II', 'SupportExecutePlayerTwo'],
 ['Execute III', 'SupportExecutePlayerThree'],
 ['Overcharge', 'SupportOverchargePlayer'],
 ['Jagged Ground I', 'SupportJaggedGroundPlayer'],
 ['Jagged Ground II', 'SupportJaggedGroundPlayerTwo'],
 ['Inexorable Critical I', 'SupportInevitableCriticalsPlayer'],
 ['Inexorable Critical II', 'SupportInevitableCriticalsPlayerTwo'],
 ['Ruthless', 'RuthlessSupportPlayer'],
 ['Compressed Duration I', 'CompressedDurationSupportPlayer'],
 ['Compressed Duration II', 'CompressedDurationSupportPlayerTwo'],
 ['Fist of War I', 'FistOfWarSupportPlayer'],
 ['Fist of War II', 'FistOfWarSupportPlayerTwo'],
 ['Fist of War III', 'FistOfWarSupportPlayerThree'],
 ['Prolonged Duration I', 'ProlongedDurationSupportPlayer'],
 ['Prolonged Duration II', 'ProlongedDurationSupportPlayerTwo'],
 ['Impact Shockwave', 'ImpactShockwaveSupportPlayer'],
 ['Hex Bloom', 'SupportHexBloomPlayer'],
 ['Frost Nexus', 'SupportChillingIcePlayer'],
 ['Shock Siphon', 'SupportEnergyShieldOnShockKillPlayer'],
 ['Shock Conduction', 'SupportShockConductionPlayer'],
 ['Shock Conduction II', 'SupportShockConductionPlayerTwo'],
 ['Deep Freeze', 'SupportLastingFrostPlayer'],
 ['Ignite I', 'SupportIgnitePlayer'],
 ['Ignite II', 'SupportIgnitePlayerTwo'],
 ['Ignite III', 'SupportIgnitePlayerThree'],
 ['Searing Flame I', 'SupportDeadlyIgnitesPlayer'],
 ['Searing Flame II', 'SupportDeadlyIgnitesPlayerTwo'],
 ['Eternal Flame I', 'SupportIgniteDurationPlayer'],
 ['Eternal Flame II', 'SupportIgniteDurationPlayerTwo'],
 ['Eternal Flame III', 'SupportIgniteDurationPlayerThree'],
 ['Essence Harvest', 'SupportEssenceHarvestPlayer'],
 ['Exploit Weakness', 'SupportExploitWeaknessPlayer'],
 ['Enraged Warcry I', 'SupportEnragedWarcryPlayer'],
 ['Enraged Warcry II', 'SupportEnragedWarcryPlayerTwo'],
 ['Neural Overload', 'SupportNeuralOverloadPlayer'],
 ['Pinpoint Critical', 'SupportPinpointCriticalPlayer'],
 ['Perpetual Charge', 'SupportPerpetualChargePlayer'],
 ['Corrosion', 'SupportCorrosionPlayer'],
 ['Bursting Plague', 'SupportBurstingPlaguePlayer'],
 ['Fortress I', 'SupportWallFortressPlayer'],
 ['Fortress II', 'SupportWallFortressPlayerTwo'],
 ["Ahn's Citadel", 'SupportAhnsCitadelPlayer'],
 ['Frostfire', 'SupportFrostfirePlayer'],
 ['Stormfire', 'SupportStormfirePlayer'],
 ['Overabundance I', 'SupportIncreaseLimitPlayer'],
 ['Overabundance II', 'SupportIncreaseLimitPlayerTwo'],
 ['Electrocute', 'SupportElectrocutePlayer'],
 ["Eonyr's Thunder", 'SupportEonyrsThunderPlayer'],
 ['Wind Wave', 'SupportKnockbackWavePlayer'],
 ['Biting Frost I', 'SupportBitingFrostPlayer'],
 ['Biting Frost II', 'SupportBitingFrostPlayerTwo'],
 ['Elemental Discharge', 'SupportElementalDischargePlayer'],
 ['Hourglass', 'SupportHourglassPlayer'],
 ['Fiery Death', 'SupportFieryDeathPlayer'],
 ['Deadly Herald', 'SupportDeadlyHeraldsPlayer'],
 ['Mana Flare', 'SupportManaFlarePlayer'],
 ['Lockdown', 'SupportLockdownPlayer'],
 ['Stun I', 'SupportStunPlayer'],
 ['Stun II', 'SupportStunPlayerTwo'],
 ['Stun III', 'SupportStunPlayerThree'],
 ['Mobility', 'SupportMobilityPlayer'],
 ['Pin I', 'SupportPinPlayer'],
 ['Pin II', 'SupportPinPlayerTwo'],
 ['Pin III', 'SupportPinPlayerThree'],
 ['Ambush', 'SupportAmbushPlayer'],
 ['Bounty I', 'SupportBountyPlayer'],
 ['Bounty II', 'SupportBountyPlayerTwo'],
 ['Mana Bounty', 'SupportManaFlaskPlayer'],
 ['Life Bounty', 'SupportLifeFlaskPlayer'],
 ['Minion Instability', 'SupportMinionInstabilityPlayer'],
 ['Heightened Curse', 'SupportCurseEffectPlayer'],
 ['Corpse Conservation', 'SupportCorpseConservationPlayer'],
 ['Decaying Hex', 'SupportDecayingHexPlayer'],
 ['Focused Curse', 'SupportFocusedCursePlayer'],
 ['Ritualistic Curse', 'SupportRitualisticCursePlayer'],
 ['Minion Pact I', 'SupportMinionPactPlayer'],
 ['Minion Pact II', 'SupportMinionPactPlayerTwo'],
 ['Last Gasp', 'SupportLastGaspPlayer'],
 ["Tecrod's Revenge", 'SupportTecrodsRevengePlayer'],
 ['Life Drain', 'SupportLifeOnCullPlayer'],
 ['Soul Drain', 'SupportManaOnCullPlayer'],
 ['Innervate', 'SupportInnervatePlayer'],
 ['Escalating Poison', 'SupportEscalatingPoisonPlayer'],
 ['Charge Profusion I', 'SupportChargeProfusionPlayer'],
 ['Charge Profusion II', 'SupportChargeProfusionPlayerTwo'],
 ['Murderous Intent', 'SupportEmpoweredCullPlayer'],
 ['Raging Cry', 'SupportRagingCryPlayer'],
 ['Armour Demolisher I', 'SupportArmourDemolisherPlayer'],
 ['Armour Demolisher II', 'SupportArmourDemolisherPlayerTwo'],
 ["Uruk's Smelting", 'SupportUruksSmeltingPlayer'],
 ['Rageforged I', 'SupportRageforgedPlayer'],
 ['Rageforged II', 'SupportRageforgedPlayerTwo'],
 ['Armour Explosion', 'SupportArmourExplosionPlayer'],
 ['Stomping Ground', 'SupportStompingGroundPlayer'],
 ['Crescendo I', 'SupportCrescendoPlayer'],
 ['Crescendo II', 'SupportCrescendoPlayerTwo'],
 ['Crescendo III', 'SupportCrescendoPlayerThree'],
 ['Fire Exposure', 'SupportFireExposurePlayer'],
 ['Lightning Exposure', 'SupportLightningExposurePlayer'],
 ['Cold Exposure', 'SupportColdExposurePlayer'],
 ['Deadly Poison I', 'SupportDeadlyPoisonPlayer'],
 ['Deadly Poison II', 'SupportDeadlyPoisonPlayerTwo'],
 ['Deep Cuts I', 'SupportDeepCutsPlayer'],
 ['Deep Cuts II', 'SupportDeepCutsPlayerTwo'],
 ['Corrupting Cry I', 'SupportCorruptingCryPlayer'],
 ['Corrupting Cry II', 'SupportCorruptingCryPlayerTwo'],
 ["Paquate's Pact", 'SupportCorruptingCryPlayerThree'],
 ['Window of Opportunity I', 'SupportWindowOfOpportunityPlayer'],
 ['Window of Opportunity II', 'SupportWindowOfOpportunityPlayerTwo'],
 ['Fire Mastery', 'SupportFireMasteryPlayer'],
 ['Cold Mastery', 'SupportColdMasteryPlayer'],
 ['Lightning Mastery', 'SupportLightningMasteryPlayer'],
 ['Chaos Mastery', 'SupportChaosMasteryPlayer'],
 ['Physical Mastery', 'SupportPhysicalMasteryPlayer'],
 ['Minion Mastery', 'SupportMinionMasteryPlayer'],
 ['Swift Affliction I', 'SupportSwiftAfflictionPlayer'],
 ['Swift Affliction II', 'SupportSwiftAfflictionPlayerTwo'],
 ['Swift Affliction III', 'SupportSwiftAfflictionPlayerThree'],
 ['Intense Agony', 'SupportIntenseAgonyPlayer'],
 ['Drain Ailments', 'SupportDrainedAilmentPlayer'],
 ['Chaotic Freeze', 'SupportChaoticFreezePlayer'],
 ['Combo Finisher I', 'SupportComboFinisherPlayer'],
 ['Combo Finisher II', 'SupportComboFinisherPlayerTwo'],
 ["Ailith's Chimes", 'SupportAilithLineagePlayer'],
 ['Slow Potency', 'SupportSlowPotencyPlayer'],
 ['Precision I', 'SupportPrecisionPlayer'],
 ['Precision II', 'SupportPrecisionPlayerTwo'],
 ['Clarity I', 'SupportClarityPlayer'],
 ['Clarity II', 'SupportClarityPlayerTwo'],
 ['Vitality I', 'SupportVitalityPlayer'],
 ['Vitality II', 'SupportVitalityPlayerTwo'],
 ['Herbalism I', 'SupportHerbalismPlayer'],
 ['Herbalism II', 'SupportHerbalismPlayerTwo'],
 ['Cannibalism I', 'SupportCannibalismPlayer'],
 ['Cannibalism II', 'SupportCannibalismPlayerTwo'],
 ['Rupture', 'SupportRupturePlayer'],
 ['Culling Strike I', 'SupportCullingStrikePlayer'],
 ['Culling Strike II', 'SupportCullingStrikePlayerTwo'],
 ['Spell Cascade', 'SupportSpellCascadePlayer'],
 ['Armour Break I', 'SupportArmourBreakPlayer'],
 ['Armour Break II', 'SupportArmourBreakPlayerTwo'],
 ['Armour Break III', 'SupportArmourBreakPlayerThree'],
 ['Longshot I', 'SupportFarCombatPlayer'],
 ['Longshot II', 'SupportFarCombatPlayerTwo'],
 ['Daze', 'SupportDazePlayer'],
 ['Cursed Ground', 'SupportCursedGroundPlayer'],
 ["Doedre's Undoing", 'SupportDoedresUndoingPlayer'],
 ["Hayoxi's Fulmination", 'SupportHayoxisBindingPlayer'],
 ["Zerphi's Infamy", 'SupportZerphisLegacyPlayer'],
 ["Helbrym's Hide", 'SupportHelbrymsHidePlayer'],
 ['Elemental Armament I', 'SupportElementalArmamentPlayer'],
 ['Elemental Armament II', 'SupportElementalArmamentPlayerTwo'],
 ['Elemental Armament III', 'SupportElementalArmamentPlayerThree'],
 ['Cooldown Recovery I', 'SupportCooldownRecoveryPlayer'],
 ['Cooldown Recovery II', 'SupportCooldownRecoveryPlayerTwo'],
 ['Font of Blood', 'SupportBloodFountainPlayer'],
 ['Font of Mana', 'SupportManaFountainPlayer'],
 ['Aftershock I', 'SupportAftershockChancePlayer'],
 ['Aftershock II', 'SupportAftershockChancePlayerTwo'],
 ['Tectonic Slams', 'SupportSlamAftershocksPlayer'],
 ['Holy Descent', 'SupportHolyDescentPlayer'],
 ['Burning Inscription', 'SupportBurningRunesPlayer'],
 ['Double Barrel I', 'SupportDoubleBarrelPlayer'],
 ['Double Barrel II', 'SupportDoubleBarrelPlayerTwo'],
 ['Double Barrel III', 'SupportDoubleBarrelPlayerThree'],
 ["Ratha's Assault", 'SupportCombatReloadPlayer'],
 ['Auto Reload', 'SupportAutoReloadPlayer'],
 ['Ammo Conservation I', 'SupportAmmoConservationPlayer'],
 ['Ammo Conservation II', 'SupportAmmoConservationPlayerTwo'],
 ['Ammo Conservation III', 'SupportAmmoConservationPlayerThree'],
 ["Arjun's Medal", 'SupportAmmoConservationPlayerFour'],
 ['Nimble Reload', 'SupportNimbleReloadPlayer'],
 ['Fresh Clip I', 'SupportFreshClipPlayer'],
 ['Fresh Clip II', 'SupportFreshClipPlayerTwo'],
 ['Sacrificial Lamb I', 'SupportSacrificialLambPlayer'],
 ['Sacrificial Lamb II', 'SupportSacrificialLambPlayerTwo'],
 ['Branching Fissures I', 'SupportBranchingFissuresPlayer'],
 ['Branching Fissures II', 'SupportBranchingFissuresPlayerTwo'],
 ['Upheaval I', 'SupportUpheavalPlayer'],
 ['Upheaval II', 'SupportUpheavalPlayerTwo'],
 ["Kaom's Madness", 'SupportKaomsMadnessPlayer'],
 ['Lasting Ground', 'SupportLastingGroundPlayer'],
 ['Ricochet I', 'SupportRicochetPlayer'],
 ['Ricochet II', 'SupportRicochetPlayerTwo'],
 ['Urgent Totems I', 'SupportUrgentTotemsPlayer'],
 ['Urgent Totems II', 'SupportUrgentTotemsPlayerTwo'],
 ['Urgent Totems III', 'SupportUrgentTotemsPlayerThree'],
 ['Long Fuse I', 'SupportLongFusePlayer'],
 ['Long Fuse II', 'SupportLongFusePlayerTwo'],
 ['Payload', 'SupportPayloadPlayer'],
 ['Potent Exposure', 'SupportPotentExposurePlayer'],
 ['Reinforced Totems I', 'SupportReinforcedTotemsPlayer'],
 ['Reinforced Totems II', 'SupportReinforcedTotemsPlayerTwo'],
 ['Considered Casting', 'SupportConsideredCastingPlayer'],
 ['Wildshards I', 'SupportWildshardsPlayer'],
 ['Wildshards II', 'SupportWildshardsPlayerTwo'],
 ["Sione's Temper", 'SupportWildshardsPlayerThree'],
 ['Icicle', 'SupportIciclePlayer'],
 ['Glacier', 'SupportGlacierPlayer'],
 ['Heft', 'SupportHeftPlayer'],
 ['Rising Tempest', 'SupportTempestuousTempoPlayer'],
 ['Extraction', 'SupportExtractionPlayer'],
 ['Astral Projection', 'SupportAstralProjectionPlayer'],
 ['Practiced Combo', 'SupportPracticedComboPlayer'],
 ['Culmination I', 'SupportCulminationPlayer'],
 ['Culmination II', 'SupportCulminationPlayerTwo'],
 ['Expanse', 'SupportExpansePlayer'],
 ['Excise', 'SupportExcisePlayer'],
 ['Execrate', 'SupportExecratePlayer'],
 ['Energy Retention', 'SupportEnergyRetentionPlayer'],
 ['Ferocity', 'SupportFerocityPlayer'],
 ['Sacrificial Offering', 'SupportSacrificalOfferingPlayer'],
 ["Guatelitzi's Ablation", 'SupportGuatelitzisAblationPlayer'],
 ['Danse Macabre', 'SupportDanseMacabrePlayer'],
 ['Energy Capacitor', 'SupportEnergyCapacitorPlayer'],
 ['Boundless Energy I', 'SupportBoundlessEnergyPlayer'],
 ['Boundless Energy II', 'SupportBoundlessEnergyPlayerTwo'],
 ['Harmonic Remnants I', 'SupportFleetingRemnantsPlayer'],
 ['Harmonic Remnants II', 'SupportFleetingRemnantsPlayerTwo'],
 ['Fluke', 'SupportFlukePlayer'],
 ["Ixchel's Torment", 'SupportFlukePlayerTwo'],
 ['Zenith I', 'SupportZenithPlayer'],
 ['Zenith II', 'SupportZenithPlayerTwo'],
 ['Bidding I', 'SupportBiddingPlayer'],
 ['Bidding II', 'SupportBiddingPlayerTwo'],
 ['Bidding III', 'SupportBiddingPlayerThree'],
 ['Commandment', 'SupportCommandment'],
 ['Adhesive Grenades I', 'SupportAdhesiveGrenadesPlayer'],
 ['Adhesive Grenades II', 'SupportAdhesiveGrenadesPlayerTwo'],
 ['Retaliate I', 'SupportRetaliatePlayer'],
 ['Retaliate II', 'SupportRetaliatePlayerTwo'],
 ['Salvo', 'SupportSalvoPlayer'],
 ['Cadence', 'SupportCadencePlayer'],
 ['Volt', 'SupportVoltPlayer'],
 ['Bone Shrapnel', 'SupportBoneShrapnelPlayer'],
 ['Alignment I', 'SupportAlignmentPlayer'],
 ['Alignment II', 'SupportAlignmentPlayerTwo'],
 ['Alignment III', 'SupportAlignmentPlayerThree'],
 ['Derange', 'SupportDerangePlayer'],
 ['Charged Shots I', 'SupportChargedShotsPlayer'],
 ['Charged Shots II', 'SupportChargedShotsPlayerTwo'],
 ['Profanity I', 'SupportProfanityPlayer'],
 ['Profanity II', 'SupportProfanityPlayerTwo'],
 ['Burgeon I', 'SupportBurgeonPlayer'],
 ['Burgeon II', 'SupportBurgeonPlayerTwo'],
 ['Steadfast I', 'SupportSteadfastPlayer'],
 ['Steadfast II', 'SupportSteadfastPlayerTwo'],
 ['Flamepierce', 'SupportFlamepiercePlayer'],
 ['Freezefork', 'SupportFreezeforkPlayer'],
 ['Stormchain', 'SupportStormchainPlayer'],
 ['Verglas', 'SupportVerglasPlayer'],
 ['Embitter', 'SupportEmbitterPlayer'],
 ['Battershout', 'SupportBattershoutPlayer'],
 ['Abiding Hex', 'SupportAbidingHexPlayer'],
 ['Rusted Spikes', 'SupportRustedSpikesPlayer'],
 ['Crazed Minions', 'SupportCrazedMinionsPlayer'],
 ['Spectral Volley', 'SupportSpectralVolleyPlayer'],
 ['Deathmarch', 'SupportDeathmarchPlayer'],
 ['Acrimony', 'SupportAcrimonyPlayer'],
 ['Concoct I', 'SupportConcoctPlayer'],
 ['Concoct II', 'SupportConcoctPlayerTwo'],
 ['Ambrosia', 'SupportAmbrosiaPlayer'],
 ['Ambrosia II', 'SupportAmbrosiaPlayerTwo'],
 ['Persistent Ground I', 'SupportPersistentGroundPlayer'],
 ['Persistent Ground II', 'SupportPersistentGroundPlayerTwo'],
 ['Persistent Ground III', 'SupportPersistentGroundPlayerThree'],
 ['Selfless Remnants', 'SupportSelflessRemnantsPlayer'],
 ['Remnant Potency I', 'SupportInterludePlayer'],
 ['Remnant Potency II', 'SupportInterludePlayerTwo'],
 ['Remnant Potency III', 'SupportInterludePlayerThree'],
 ['Reverberate', 'SupportReveberatePlayer'],
 ['Clash', 'SupportClashPlayer'],
 ['Malady', 'SupportMaladyPlayer'],
 ['Syzygy', 'SupportSyzygyPlayer'],
 ['Overextend', 'SupportOverextendPlayer'],
 ['Retreat I', 'SupportRetreatPlayer'],
 ['Retreat II', 'SupportRetreatPlayerTwo'],
 ['Retreat III', 'SupportRetreatPlayerThree'],
 ['Pursuit I', 'SupportPursuitPlayer'],
 ['Pursuit II', 'SupportPursuitPlayerTwo'],
 ['Pursuit III', 'SupportPursuitPlayerThree'],
 ['Overreach', 'SupportOverreachPlayer'],
 ['Commiserate', 'SupportCommiseratePlayer'],
 ['Blindside', 'SupportBlindsidePlayer'],
 ['Hit and Run', 'SupportHitAndRunPlayer'],
 ['Crackling Barrier', 'SupportCracklingBarrierPlayer'],
 ['Defy I', 'SupportDefyPlayer'],
 ['Defy II', 'SupportDefyPlayerTwo'],
 ['Volatility', 'SupportVolatilityPlayer'],
 ['Muster', 'SupportMusterPlayer'],
 ['Hulking Minions', 'SupportHulkingMinionsPlayer'],
 ['Caltrops', 'SupportCaltropsPlayer'],
 ['Haemocrystals', 'SupportHaemocrystalsPlayer'],
 ['Spar', 'SupportSparPlayer'],
 ['Dauntless', 'SupportDauntlessPlayer'],
 ['Magnetic Remnants', 'SupportMagneticRemnantsPlayer'],
 ['Ancestral Call I', 'SupportAncestralCallPlayer'],
 ['Ancestral Call II', 'SupportAncestralCallPlayerTwo'],
 ['Quill Burst', 'SupportQuillburstPlayer'],
 ['Ancestral Aid', 'SupportAncestralAidPlayer'],
 ['Shocking Leap', 'SupportShockingLeapPlayer'],
 ['Barbs I', 'SupportBarbsPlayer'],
 ['Barbs II', 'SupportBarbsPlayerTwo'],
 ['Barbs III', 'SupportBarbsPlayerThree'],
 ['Arms Length', 'SupportArmsLengthPlayer'],
 ['Charm Bounty', 'SupportCharmBountyPlayer'],
 ['Thornskin I', 'SupportThornskinPlayer'],
 ['Thornskin II', 'SupportThornskinPlayerTwo'],
 ['Mysticism I', 'SupportMysticismPlayer'],
 ['Mysticism II', 'SupportMysticismPlayerTwo'],
 ['Direstrike I', 'SupportDirestrikePlayer'],
 ['Direstrike II', 'SupportDirestrikePlayerTwo'],
 ['Upwelling I', 'SupportUpwellingPlayer'],
 ['Upwelling II', 'SupportUpwellingPlayerTwo'],
 ['Warm Blooded', 'SupportWarmbloodedPlayer'],
 ['Cool Headed', 'SupportCoolheadedPlayer'],
 ['Strong Hearted', 'SupportStrongHeartedPlayer'],
 ['Untouchable', 'SupportUntouchablePlayer'],
 ['Refraction I', 'SupportRefractionPlayer'],
 ['Refraction II', 'SupportRefractionPlayerTwo'],
 ['Refraction III', 'SupportRefractionPlayerThree'],
 ["Cirel's Cultivation", 'SupportCirelsCultivationPlayer'],
 ['Splinter Totem I', 'SupportSplinteringTotemPlayer'],
 ['Splinter Totem II', 'SupportSplinteringTotemPlayerTwo'],
 ['Punch Through', 'SupportPunchThroughPlayer'],
 ['Rip', 'SupportRipPlayer'],
 ['Tear', 'SupportTearPlayer'],
 ['Brink I', 'SupportBrinkPlayer'],
 ['Brink II', 'SupportBrinkPlayerTwo'],
 ['Tireless', 'SupportTirelessPlayer'],
 ['Volcanic Eruption', 'SupportVolcanicEruptionPlayer'],
 ['Frenzied Riposte', 'SupportFrenziedRipostePlayer'],
 ['Heightened Charges', 'SupportHeightenedChargesPlayer'],
 ['Incision', 'SupportIncisionPlayer'],
 ['Catharsis', 'SupportCatharsisPlayer'],
 ['Delayed Gratification', 'SupportDelayedGratificationPlayer'],
 ['Loyalty', 'SupportLoyaltyPlayer'],
 ["Romira's Requital", 'SupportRomirasRequitalPlayer'],
 ['Rearm I', 'SupportRearmPlayer'],
 ['Rearm II', 'SupportRearmPlayerTwo'],
 ['Delayed Reaction', 'SupportDelayedReactionPlayer'],
 ['Gambleshot', 'SupportGambleshotPlayer'],
 ['Unerring Power', 'SupportUnerringPowerPlayer'],
 ['Impale', 'SupportImpalePlayer'],
 ['Perfection', 'SupportPerfectionPlayer'],
 ['Deliberation', 'SupportDeliberationPlayer'],
 ['Short Fuse I', 'SupportShortFusePlayer'],
 ['Short Fuse II', 'SupportShortFusePlayerTwo'],
 ['Undermine', 'SupportUnderminePlayer'],
 ['Mark for Death', 'SupportMarkForDeathPlayer'],
 ['Mark for Death II', 'SupportMarkForDeathPlayerTwo'],
 ['Admixture', 'SupportAdmixturePlayer'],
 ['Stoicism I', 'SupportStoicismPlayer'],
 ['Stoicism II', 'SupportStoicismPlayerTwo'],
 ['Relentless Rage', 'SupportRelentlessRagePlayer'],
 ['Brambleslam', 'SupportBrambleslamPlayer'],
 ['Inhibitor', 'SupportChargeInhibitionPlayer'],
 ['Static Shocks', 'SupportStaticShocksPlayer'],
 ['Hardy Totems I', 'SupportHardyTotemsPlayer'],
 ['Hardy Totems II', 'SupportHardyTotemsPlayerTwo'],
 ["Tawhoa's Tending", 'SupportHardyTotemsPlayerThree'],
 ['Encroaching Ground', 'SupportEncroachingGroundPlayer'],
 ['Living Lightning', 'SupportLivingLightningPlayer'],
 ['Living Lightning II', 'SupportLivingLightningPlayerTwo'],
 ['Frozen Spite', 'SupportFrozenSpitePlayer'],
 ['Electromagnetism', 'SupportShockingRiftPlayer'],
 ["Dominus' Grasp", 'SupportPietysMercyPlayer'],
 ['Flame Pillar', 'SupportFlamePillarPlayer'],
 ['Streamlined Rounds', 'SupportStreamlinedRoundsPlayer'],
 ['Perfected Endurance', 'SupportPerfectEndurancePlayer'],
 ['Enduring Impact I', 'SupportHeavyStunEndurancePlayerOne'],
 ['Enduring Impact II', 'SupportHeavyStunEndurancePlayerTwo'],
 ['Crater', 'SupportCraterPlayer'],
 ['Vanguard I', 'SupportVanguardPlayer'],
 ['Vanguard II', 'SupportVanguardPlayerTwo'],
 ['Crystalline Shards', 'SupportCrystallineShardsPlayer'],
 ['Skittering Stone I', 'SupportSkitteringStonePlayer'],
 ['Skittering Stone II', 'SupportSkitteringStonePlayerTwo'],
 ["Dialla's Desire", 'SupportDiallasDesirePlayer'],
 ["Kalisa's Crescendo", 'SupportKalisasCrescendoPlayer'],
 ['Durability', 'SupportDurabilityPlayer'],
 ["Xoph's Pyre", 'SupportXophsPyrePlayer'],
 ["Esh's Radiance", 'SupportEshsRadiancePlayer'],
 ["Tul's Stillness", 'SupportTulsStillnessPlayer'],
 ["Uul-Netol's Embrace", 'SupportUulNetolsEmbracePlayer'],
 ["Rakiata's Flow", 'SupportRakiatasFlowPlayer'],
 ["Rigwald's Ferocity", 'SupportRigwaldsFerocityPlayer'],
 ["Uhtred's Exodus", 'SupportUhtredExodusPlayer'],
 ["Uhtred's Omen", 'SupportUhtredOmenPlayer'],
 ["Uhtred's Augury", 'SupportUhtredAuguryPlayer'],
 ["Daresso's Passion", 'SupportDaressosPassionPlayer'],
 ["Atziri's Allure", 'SupportAtzirisAllurePlayer'],
 ["Atziri's Communion", 'SupportAtzirisCommunionPlayer'],
 ["Atziri's Impatience", 'SupportAtzirisImpatiencePlayer'],
 ["Tacati's Ire", 'SupportTacatisIrePlayer'],
 ["Zarokh's Refrain", 'SupportZarokhsRefrainPlayer'],
 ["Garukhan's Resolve", 'SupportGarukhansResolvePlayer'],
 ["Kurgal's Leash", 'SupportKurgalsLeashPlayer'],
 ["Kulemak's Dominion", 'SupportKulemaksDominionPlayer'],
 ["Amanamu's Tithe", 'SupportAmanamusTithePlayer'],
 ["Varashta's Blessing", 'SupportVarashtasBlessingPlayer'],
 ["Arbiter's Ignition", 'SupportArbitersIgnitionPlayer'],
 ["Arakaali's Lust", 'SupportArakaalisLustPlayer'],
 ["Tasalio's Rhythm", 'SupportTasaliosRhythmPlayer'],
 ["Xibaqua's Rending", 'SupportXibaquasRendingPlayer'],
 ["Khatal's Rejuvenation", 'SupportKhatalsRejuvenationPlayer'],
 ["Morgana's Tempest", 'SupportMorganasTempestPlayer'],
 ['Creeping Chill', 'SupportCreepingChillPlayer'],
 ['Mark of Siphoning', 'SupportMarkOfSiphoningPlayer'],
 ['Mark of Siphoning II', 'SupportMarkOfSiphoningPlayerTwo'],
 ['Thrill of the Kill', 'SupportThrillOfTheKillPlayer'],
 ['Thrill of the Kill II', 'SupportThrillOfTheKillPlayerTwo'],
 ['Exposing Cry', 'SupportExposingCryPlayer'],
 ['Opening Move', 'SupportOpeningMovePlayer'],
 ['Accelerated Growth', 'SupportExplosiveGrowthPlayer'],
 ['Accelerated Growth II', 'SupportExplosiveGrowthPlayerTwo'],
 ['Fan The Flames', 'SupportFanTheFlamesPlayer'],
 ['Fan The Flames II', 'SupportFanTheFlamesPlayerTwo'],
 ['Coursing Current', 'SupportDeadlyCurrentPlayer'],
 ['Poison Spores', 'SupportPoisonSpores'],
 ['Deadly Resolve', 'SupportDeadlyResolvePlayer'],
 ['Advancing Storm', 'SupportAdvancingStormPlayer'],
 ['Echoing Cry', 'SupportEchoingCryPlayer'],
 ['Gorge', 'SupportGorgePlayer'],
 ['Empowered Sparks I', 'SupportEmpoweredSparksPlayer'],
 ['Controlled Hazard', 'SupportControlledHazardPlayer'],
 ['Brittle Armour', 'SupportBrittleArmourPlayer'],
 ['Rending Apex', 'SupportRendingApexPlayer'],
 ['Practical Magic I', 'SupportPracticalMagicPlayer'],
 ['Practical Magic II', 'SupportPracticalMagicPlayerTwo'],
 ['Blazing Critical', 'SupportBlazingCriticalPlayer'],
 ['Concussive Spells', 'SupportConcussiveSpellsPlayer'],
 ['Eternal Mark', 'SupportEternalMarkPlayer'],
 ['Catalysing Elements', 'SupportCatalysingElementsPlayer'],
 ['Nova Projectiles II', 'SupportNovaProjectilesTwoPlayer'],
 ['Charged Mark', 'SupportChargedMarkPlayer'],
 ['Minion Splash I', 'SupportMinionMeleeSplashPlayer'],
 ['Minion Splash II', 'SupportMinionMeleeSplashPlayerTwo'],
 ['Her Declaration', 'SupportHerDeclarationPlayer'],
 ['Prototype Seventeen', 'SupportPrototypeSeventeenPlayer'],
 ["Seraph's Heart", 'SupportSeraphsHeartPlayer'],
 ["Uhtred's Rite", 'SupportUhtredsRitePlayer'],
 ["Trickster's Shard", 'SupportTrickstersShardPlayer'],
 ["Arbiter's Reach", 'ArbitersReachWardPlayer'],
 ["Tangmazu's Thurible", 'SupportTangMazusThuriblePlayer'],
 ["Esh's Prowess", 'SupportEshsProwess'],
 ["Breachlord's Rift", 'SupportBreachlordsRift'],
 ["Breachlord's Amalgam", 'SupportBreachlordsAmalgam'],
 ["Vruun's Aftermath", 'SupportVruunsAftermath'],
 ["Vruun's Inevitability", 'SupportVruunsInevitability'],
 ["Uhtred's Constellation", 'SupportUhtredsConstellation'],
 ["Medved's Felling", 'SupportMedvedsFelling'],
 ["Vorana's Siege", 'SupportVoranasSiege'],
 ["Styrn's Mountain", 'SupportStyrnsMountain'],
 ["Styrn's Ferocity", 'SupportStyrnsFerocity'],
 ["Catha's Brilliance", 'SupportCathasBrilliance'],
 ["Morrigan's Insight", 'SupportMorrigansInsight'],
 ["Tul's Avalanche", 'SupportTulsAvalanche'],
 ['Concussive Runes', 'SupportConcussiveRunesPlayer'],
 ['Runic Infusion', 'SupportRunicInfusionPlayer'],
 ['Runeforged Blades', 'SupportRuneforgedBladesPlayer'],
 ['Runic Extraction', 'SupportRunicExtractionPlayer'],
 ['Scouring Flame', 'SupportScouringFlamePlayer'],
 ['Fist Of Kalguur', 'SupportFistOfKalguurPlayer'],
 ['Healing Runes', 'SupportHealingRunesPlayer'],
 ["Olroth's Conviction", 'SupportOlrothsConvictionPlayer'],
 ["Olroth's Hubris", 'SupportOlrothsHubrisPlayer']]

# Exact public modifier labels; no fuzzy or translated-label inference.
_MOD_ROWS = [['PlayerMonsterDamageGainedAsFire1', 'Extra Fire Damage'],
 ['PlayerMonsterDamageGainedAsCold1', 'Extra Cold Damage'],
 ['PlayerMonsterDamageGainedAsLightning1', 'Extra Lightning Damage'],
 ['PlayerMonsterIncreasedSpeed1', 'Hasted'],
 ['PlayerMonsterCriticalStrikeChance1', 'Extra Crits'],
 ['PlayerMonsterStunDamageIncrease1', 'Stuns'],
 ['PlayerMonsterExtraArmour1', 'Armoured'],
 ['PlayerMonsterExtraEvasion1', 'Evasive'],
 ['PlayerMonsterExtraEnergyShield1', 'Extra Energy Shield'],
 ['PlayerMonsterAlwaysPoison1', 'Always Poisons'],
 ['PlayerMonsterAlwaysBleed1', 'Always Bleeds'],
 ['PlayerMonsterBurningGroundOnDeath1', 'Periodically unleashes Fire'],
 ['PlayerMonsterChilledGroundOnDeath1', 'Periodically unleashes Ice'],
 ['PlayerMonsterShockedGroundOnDeath1', 'Periodically unleashes Lightning'],
 ['PlayerMonsterStunResilience1', 'Stun Resistant'],
 ['PlayerMonsterFireResistance1', 'Fire Resistant'],
 ['PlayerMonsterColdResistance1', 'Cold Resistant'],
 ['PlayerMonsterLightningResistance1', 'Lightning Resistant'],
 ['PlayerMonsterArmourPenetration1', 'Breaks Armour'],
 ['PlayerMonsterIncreasedAccuracy1', 'Accurate'],
 ['PlayerMonsterDamageGainedAsChaos1', 'Extra Chaos Damage'],
 ['PlayerMonsterLifeRegenerationRatePercentage1', 'Regenerates Life'],
 ['PlayerMonsterAdditionalProjectiles1', 'Additional Projectiles'],
 ['PlayerMonsterAreaOfEffect1', 'Increased Area of Effect'],
 ['PlayerMonsterIgniteChanceIncrease1', 'All Damage Ignites'],
 ['PlayerMonsterFreezeDamageIncrease1', 'All Damage Chills'],
 ['PlayerMonsterShockChanceIncrease1', 'All Damage Shocks'],
 ['PlayerMonsterBurningGroundTrail1', 'Trail of Fire'],
 ['PlayerMonsterChilledGroundTrail1', 'Trail of Ice'],
 ['PlayerMonsterShockedGroundTrail1', 'Trail of Lightning'],
 ['PlayerMonsterImmuneToSlow1', 'Slow Resistant'],
 ['PlayerMonsterModReducedCritMulti1', 'Crit Resistant'],
 ['PlayerMonsterChaosResistance1', 'Chaos Resistant'],
 ['PlayerMonsterFlameBeacons1', 'Periodic Fire Explosions'],
 ['PlayerMonsterFrostBeacons1', 'Periodic Cold Explosions'],
 ['PlayerMonsterLightningBeacons1', 'Periodic Lightning Explosions'],
 ['PlayerMonsterStrongerMinions1', 'Powerful Minions'],
 ['PlayerMonsterPhysicalDamageAura1', 'Extra Physical Damage Aura'],
 ['PlayerMonsterIncreasedSpeedAura1', 'Haste Aura'],
 ['PlayerMonsterEnergyShieldAura1', 'Energy Shield Aura'],
 ['PlayerMonsterResistanceAura1', 'Elemental Resistance Aura'],
 ['PlayerMonsterTemporalAura1', 'Temporal Bubble'],
 ['PlayerMonsterHinderAura1', 'Hinder Aura'],
 ['PlayerMonsterPreventRecoveryAura1', 'Prevents Recovery Above 50%'],
 ['PlayerMonsterImmuneAura1', 'Periodic Invulnerability Aura'],
 ['PlayerMonsterImmuneAura2', 'Empowered Periodic Invulnerability Aura'],
 ['PlayerMonsterManaSiphonAura1', 'Siphons Mana and Deals Lightning Damage'],
 ['PlayerMonsterManaSiphonAura2', 'Siphons Mana and Deals Lightning Damage'],
 ['PlayerMonsterHealingNova1', 'Heals Allies and Suppresses Foe Recovery'],
 ['PlayerMonsterFlaskRemovalAura1', 'Siphons Flask Charges'],
 ['PlayerMonsterRevivesMinions1', 'Reviving Minions'],
 ['PlayerMonsterRevivesMinions2', 'Empowered Reviving Minions'],
 ['PlayerMonsterMinionsTakeLifeInstead1', 'Damage Taken From Minions First'],
 ['PlayerMonsterShroudWalker1', 'Shroud Walker'],
 ['PlayerMonsterShroudWalker2', 'Shroud Walker'],
 ['PlayerMonsterPeriodicEnrage1', 'Periodically Enrages'],
 ['PlayerMonsterPeriodicEnrage2', 'Enraged'],
 ['PlayerMonsterCorpseExploder1', 'Explodes Nearby Corpses'],
 ['PlayerMonsterLightningMirage1', 'Lightning Mirage When Hit'],
 ['PlayerMonsterLightningMirage2', 'Lightning Mirages When Hit'],
 ['PlayerMonsterMagmaBarrier1', 'Magma Barrier'],
 ['PlayerMonsterFlamewaller1', 'Conjures Flamewalls'],
 ['PlayerMonsterLightningStorms1', 'Conjures Lightning Storms'],
 ['PlayerMonsterVolatilePlants1', 'Volatile Plants'],
 ['PlayerMonsterVolatilePlants2', 'Empowering Volatile Plants'],
 ['PlayerMonsterVolatileRocks1', 'Volatile Crag'],
 ['PlayerMonsterVolatileRocks2', 'Empowering Volatile Crag'],
 ['PlayerMonsterProximalTangibility1', 'Proximal Tangibility']]

# Public species names from the same pinned Spectres.lua data overlay.
_SPECIES_ROWS = [('Metadata/Monsters/EtchedBeetles/SmallEtchedBeetleArmoured', 'Adorned Beetle'),
 ('Metadata/Monsters/EtchedBeetles/SmallEtchedBeetleArmouredDull', 'Tarnished Beetle'),
 ('Metadata/Monsters/EtchedBeetles/MediumEtchedBeetleArmouredDull', 'Tarnished Scarab'),
 ('Metadata/Monsters/EtchedBeetles/MediumEtchedBeetleArmouredTuskWide', 'Adorned Scarab'),
 ('Metadata/Monsters/GoreCharger/GoreCharger', 'Diretusk Boar'),
 ('Metadata/Monsters/QuillCrab/QuillCrab', 'Porcupine Crab'),
 ('Metadata/Monsters/QuillCrab/QuillCrabTropical', 'Quill Crab'),
 ('Metadata/Monsters/QuillCrab/QuillCrabBigTropical', 'Quill Crab'),
 ('Metadata/Monsters/CrabMonsters/CrabCoconut', 'Coconut Crab'),
 ('Metadata/Monsters/QuillCrab/QuillCrabBig', 'Porcupine Crab'),
 ('Metadata/Monsters/QuillCrab/QuillCrabPoison', 'Venomous Crab'),
 ('Metadata/Monsters/QuillCrab/QuillCrabBigPoison_', 'Venomous Crab Matriarch'),
 ('Metadata/Monsters/ShellMonster/ShellMonster', 'Brimstone Crab'),
 ('Metadata/Monsters/ShellMonster/ShellMonsterPoison_', 'Caustic Crab'),
 ('Metadata/Monsters/Sanctified/Spider/SanctifiedSpider', 'Fettered Spider'),
 ('Metadata/Monsters/Sanctified/Writhing/SanctifiedWrithing', 'Fettered Writher'),
 ('Metadata/Monsters/ParasiteMonsters/OctopusParasite', 'Infested Octopus'),
 ('Metadata/Monsters/ParasiteMonsters/TurtleParasite__', 'Infested Turtle'),
 ('Metadata/Monsters/ParasiteMonsters/AngerfishParasite', 'Infested Anglerfish'),
 ('Metadata/Monsters/ParasiteMonsters/MantaRayParasite', 'Infested Manta'),
 ('Metadata/Monsters/BoneCultists/BoneCultists_Beast/BoneCultistBeast', 'Drudge Osseodon'),
 ('Metadata/Monsters/Quadrilla/Quadrilla', 'Quadrilla'),
 ('Metadata/Monsters/RatMonster/RatMonster', 'Rotted Rat'),
 ('Metadata/Monsters/RatMonster/RatMonsterPoison__', 'Rotted Rat'),
 ('Metadata/Monsters/Werewolves/WerewolfMoonClan1', 'Voracious Werewolf'),
 ('Metadata/Monsters/Werewolves/WerewolfPack1', 'Pack Werewolf'),
 ('Metadata/Monsters/Werewolves/WerewolfProwler1', 'Werewolf Prowler'),
 ('Metadata/Monsters/Werewolves/WerewolfProwlerRed1', 'Tendril Prowler'),
 ('Metadata/Monsters/Wolves/Wolf1', 'Hungry Wolf'),
 ('Metadata/Monsters/Monkeys/MonkeyJungle', 'Feral Primate'),
 ('Metadata/Monsters/BloodChieftain/MonkeyChiefJungle', 'Alpha Primate'),
 ('Metadata/Monsters/Spiker/Spiker3_', 'Porcupine Goliath'),
 ('Metadata/Monsters/Spiker/Spiker3SanctumTrial__', 'Porcupine Goliath'),
 ('Metadata/Monsters/MudBurrower/BrambleBurrower', 'Bramble Burrower'),
 ('Metadata/Monsters/StonebackRhoa/BrambleRhoa', 'Bramble Rhoa'),
 ('Metadata/Monsters/HuhuGrub/HuhuGrubLarvaeSpectre', 'Flesh Larva'),
 ('Metadata/Monsters/Crow/CrowCarrion', 'Rotting Crow'),
 ('Metadata/Monsters/BrambleHulk/BrambleHulk1', 'Bramble Hulk'),
 ('Metadata/Monsters/Zombies/Fungal/FungalArtillery1__', 'Fungal Artillery'),
 ('Metadata/Monsters/Frog/PaleFrog1', 'Maw Demon'),
 ('Metadata/Monsters/Wolves/RottenWolf1_', 'Rotten Wolf'),
 ('Metadata/Monsters/Wolves/FungalWolf1_', 'Fungal Wolf'),
 ('Metadata/Monsters/Monkeys/Bramble/BrambleMonkey1', 'Bramble Ape'),
 ('Metadata/Monsters/FaridunLizards/FaridunLizard_', 'Rhex'),
 ('Metadata/Monsters/FaridunLizards/FaridunLizard_Armoured_', 'Armoured Rhex'),
 ('Metadata/Monsters/Parasites/FishParasite', 'Chyme Skitterer'),
 ('Metadata/Monsters/Parasites/PirateFishParasite', 'Abyss Fish'),
 ('Metadata/Monsters/LeagueExpeditionNew/RatMonster/ExpeditionRat', 'Druidic Familiar'),
 ('Metadata/Monsters/DemonSpiders/MeleeSpider', 'Vault Lurker'),
 ('Metadata/Monsters/DemonSpiders/SpiderSabre', 'Sabre Spider'),
 ('Metadata/Monsters/HyenaMonster/HyenaMonster', 'Hyena Demon'),
 ('Metadata/Monsters/HyenaMonster/HyenaCentaurSpear', 'Sun Clan Scavenger'),
 ('Metadata/Monsters/VultureRegurgitator/VultureRegurgitator_', 'Regurgitating Vulture'),
 ('Metadata/Monsters/VultureZombie/VultureDemonSpectre', 'Vile Vulture'),
 ('Metadata/Monsters/SandLeaper02/DesertLeaper1_', 'Crag Leaper'),
 ('Metadata/Monsters/WingedFiend/WingedFiend', 'Winged Fiend'),
 ('Metadata/Monsters/SkeletonSnake', 'Gilded Cobra'),
 ('Metadata/Monsters/PorcupineAnt/PorcupineAntSmall', 'Rasp Scavenger'),
 ('Metadata/Monsters/PorcupineAnt/PorcupineAntMedium', 'Rasp Scavenger'),
 ('Metadata/Monsters/PorcupineAnt/PorcupineAntLarge', 'Rasp Scavenger'),
 ('Metadata/Monsters/CaveDweller/CaveDweller', 'Tombshrieker'),
 ('Metadata/Monsters/MineBat/MineBatDesertCaveNoEmerge', 'Vesper Bat'),
 ('Metadata/Monsters/PlagueSwarm/PlagueSwarm', 'Plague Swarm'),
 ('Metadata/Monsters/PlagueNymph/PlagueNymph_', 'Plague Nymph'),
 ('Metadata/Monsters/PlagueBringer/PlagueBringer', 'Plague Harvester'),
 ('Metadata/Monsters/BrainWorm/DuneLurker_', 'Dune Lurker'),
 ('Metadata/Monsters/WingedCreature/WingedCreature', 'Winged Horror'),
 ('Metadata/Monsters/MantisRat/MantisRat', 'Mantis Rat'),
 ('Metadata/Monsters/PlagueSwarm/BloodDrone', 'Bloodthief Wasp'),
 ('Metadata/Monsters/BaneSapling/BaneSapling', 'Bane Sapling'),
 ('Metadata/Monsters/ArmadilloDemon/ArmadilloDemon', 'Antlion Charger'),
 ('Metadata/Monsters/ChawMongrel/ChawMongrel', 'Chaw Mongrel'),
 ('Metadata/Monsters/NettleAnt/NettleAntSummoned', 'Nettle Ant'),
 ('Metadata/Monsters/SnakeHulk/SnakeHulk', 'Entwined Hulk'),
 ('Metadata/Monsters/SerpentHusk/SerpentHusk__', 'Snakethroat Shambler'),
 ('Metadata/Monsters/GutViper/GutViper', 'Entrailhome Shambler'),
 ('Metadata/Monsters/SpittingSnake/SpittingSnake', 'Slitherspitter'),
 ('Metadata/Monsters/ConstrictorCorpse/ConstrictorCorpse', 'Constricted Shambler'),
 ('Metadata/Monsters/ConstrictorCorpse/ConstrictorCorpseRanged_', 'Constricted Spitter'),
 ('Metadata/Monsters/SpiderMonkey/SpiderMonkey', 'Scorpion Monkey'),
 ('Metadata/Monsters/WereCat/TigerChimeral', 'Prowling Chimeral'),
 ('Metadata/Monsters/Taniwha/RiverTaniwhaNoJank', 'River Drake'),
 ('Metadata/Monsters/VaalMonsters/Living/Beasts/VaalJaguar', 'Loyal Jaguar'),
 ('Metadata/Monsters/AscendancyBatMonster/AscendancyBat', 'Feral Bat'),
 ('Metadata/Monsters/RootedGuys/RootedGuy04/RaisedBranchMonster', 'Cultivated Grove'),
 ('Metadata/Monsters/Baron/BaronWerewolfSummon', 'Court Werewolf'),
 ('Metadata/Monsters/ScarecrowBeast/ScarecrowBeast', 'Scarecrow Beast'),
 ('Metadata/Monsters/LeagueRitual/DryadFaction/DruidicFallenStag', 'Forgotten Stag'),
 ('Metadata/Monsters/RabidFeralDogMonster/RabidDog', 'Rabid Dog'),
 ('Metadata/Monsters/KaruiBoar/ExplosivePig', 'Volatile Boar'),
 ('Metadata/Monsters/ChaosGodRangedFodder/ChaosGodRangedFodder_', 'Petulant Stonemaw'),
 ('Metadata/Monsters/ChaosGodJaguar/ChaosGodJaguar_', 'Scute Lizard'),
 ('Metadata/Monsters/ChaosGodTriHeadBat/ChaosGodTri-headBat_', 'Cerberic Bat'),
 ('Metadata/Monsters/ChaosGodGorilla/ChaosGodGorilla_', 'Stoneclad Gorilla'),
 ('Metadata/Monsters/ChaosGodTriceratops/ChaosGodTriceratops_', 'Crested Behemoth'),
 ('Metadata/Monsters/Breach/Monsters/FingersBat/FingersBat', 'It That Watches'),
 ('Metadata/Monsters/LeagueRitual/DryadFaction/RootMonster/RootBehemoth', 'Treant Fungalreaver'),
 ('Metadata/Monsters/LeagueRitual/DemonFaction/CaveDweller_', 'Nameless Dweller'),
 ('Metadata/Monsters/LeagueRitual/DemonFaction/PrimordialMonster3_', 'Nameless Horror'),
 ('Metadata/Monsters/LeagueRitual/DemonFaction/DemonRhoa', 'Nameless Lurker'),
 ('Metadata/Monsters/LeagueRitual/DemonFaction/DemonRat', 'Nameless Vermin'),
 ('Metadata/Monsters/LeagueRitual/DemonFaction/DemonBurrower', 'Nameless Burrower'),
 ('Metadata/Monsters/LeagueRitual/DemonFaction/DemonHulk_', 'Nameless Hulk'),
 ('Metadata/Monsters/LeagueRitual/DemonFaction/DemonMonkey', 'Nameless Imp'),
 ('Metadata/Monsters/KaruiSpiritTortoise/SpiritTortoise_', 'Guardian Turtle'),
 ('Metadata/Monsters/PlagueBringer/TwilightOrderPlagueBringer', 'Gargantuan Wasp'),
 ('Metadata/Monsters/GullGoliath/GullGoliath_', 'Goliath Shrike'),
 ('Metadata/Monsters/GullMen/GullMen', 'Manshrike'),
 ('Metadata/Monsters/GullCarrion/GullCarrion', 'Carrion Gull'),
 ('Metadata/Monsters/WingedFiend/CrawGull', 'Vilespit Gull'),
 ('Metadata/Monsters/HarpyMonster/RavenHarpyShrikeIsland', 'Raven Shrike'),
 ('Metadata/Monsters/HarpyMonster/GullHarpy', 'Gull Shrike'),
 ('Metadata/Monsters/RatMonster/RatMonsterPrison', 'Eaten Rat'),
 ('Metadata/Monsters/ElephantRhino/ElephantRhino', 'Elephant Tortoise'),
 ('Metadata/Monsters/DeepDwellerBoss/SpikedDweller', 'Spiked Scuttler'),
 ('Metadata/Monsters/StonebackRhoa/StonebackRhoa', 'Stoneback Rhoa'),
 ('Metadata/Monsters/StonebackRhoa/GoblinStonebackRhoa', 'Captive Stoneback Rhoa'),
 ('Metadata/Monsters/HarpyMonster/MagmaHarpy/MagmaHarpy', 'Molten Imp'),
 ('Metadata/Monsters/ElectricStingray/ElectricStingray_', 'Spiked Ray'),
 ('Metadata/Monsters/JellfishNettler/JellyfishNettlerSmall', 'Skittering Jellycrab'),
 ('Metadata/Monsters/JellfishNettler/JellyfishNettlerBig', 'Skittering Jellycrab'),
 ('Metadata/Monsters/GiantStarfish/GiantStarfish_', 'Giant Maw'),
 ('Metadata/Monsters/CarrionWing/CarrionWing_', 'Luminous Spinefish'),
 ('Metadata/Monsters/BrineMaiden/BrineMaiden', 'Brine Maiden'),
 ('Metadata/Monsters/ProwlerLeviathan/ProwlerLeviathan', 'Amphibious Prowler'),
 ('Metadata/Monsters/KaruiTuatara/KaruiTuatara_', 'Guardian Lizard'),
 ('Metadata/Monsters/PlagueSwarm/TwilightOrderPlagueSwarm', 'Swarming Wasp'),
 ('Metadata/Monsters/PlagueSwarm/LargeParasiticCrab', 'Clawcrunch'),
 ('Metadata/Monsters/BloodFeverKarui/BloodFeverBoar', 'Blood-fevered Tuskbeast'),
 ('Metadata/Monsters/LeagueAncestral/StandaloneTawhoa/Boar/TawhoaBoarStandalone', "Tawhoa's Boar"),
 ('Metadata/Monsters/LeagueAncestral/StandaloneTawhoa/Tuatata/TawhoaTuataraStandalone', "Tawhoa's Tuatara"),
 ('Metadata/Monsters/LeagueIncursionNew/Thaumaturge/MonkeyExperiment', 'Experimental Primate'),
 ('Metadata/Monsters/LeagueIncursionNew/Thaumaturge/GoreChargerExperiment', 'Experimental Boar'),
 ('Metadata/Monsters/LeagueIncursionNew/Thaumaturge/SpittingSnakeExperiment', 'Experimental Cobra'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/AntFaction/AntCarrierExpedition', 'Dezzic Soldier'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/AntFaction/BaneSaplingExpedition', 'Dezzic Bombardier'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/AntFaction/HoneyAntExpedition', 'Dezzic Burstbug'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/AntFaction/NettleAntExpedition', 'Dezzic Nettler'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/ArachnidFaction/ShakariExpedition', 'Krell Fleshgouger'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/CrustaceanFaction/AnglerFishParasiteExpedition',
  'Cecaelian Angler'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/CrustaceanFaction/ShellMonsterExpedition', 'Cecaelian Crab'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/ParasiteFaction/MantaRayParasiteExpedition', 'Ylth Eater'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/ParasiteFaction/OctopusParasiteExpedition', 'Ylth Grabber'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/ParasiteFaction/ParasiteHostMonsterExpedition', 'Ylth Spewer'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/Fodder/Cocoon3Expedition', 'Starlit Defiler'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/Fodder/PlagueBringerExpedition', 'Starlit Harvester'),
 ('Metadata/Monsters/LeagueExpeditionNew/Expedition2/Fodder/PlagueNymphExpedition', 'Starlit Nymph'),
 ('Metadata/Monsters/VaalMonsters/ViperNapuatzi/ViperNapuatziSnakeMinion', 'Viper Servant'),
 ('Metadata/Monsters/VaalMonsters/Living/Minions/VaalJaguarMinion', 'Jaguar Familiar'),
 ('Metadata/Monsters/VaalMonsters/Living/Minions/VaalSnakeMinion', 'Serpentine Familiar'),
 ('Metadata/Monsters/VaalMonsters/Living/Minions/VaalMonkeyMinion_', 'Primal Familiar'),
 ('Metadata/Monsters/SerpentHusk/snakes/SerpentHuskSnake', 'Snake'),
 ('Metadata/Monsters/SkeletonSnake/SandSkeletonSnake', 'Skeletal Cobra'),
 ('Metadata/Monsters/LeagueIncursionNew/MiniBosses/SoulCoreQuadrillaBoss/SoulCoreQuadrillaMinion',
  'Quadrilla Sergeant'),
 ('Metadata/Monsters/LeagueIncursionNew/MiniBosses/IncursionChainedBeastBoss/ChainedBeastBossMinion_',
  'Unchained Beast'),
 ('Metadata/Monsters/CrowBell/CrowBellBossMinion1', 'The Crowbell'),
 ('Metadata/Monsters/CrowBell/CrowBellBossMinion2', 'The Black Crow'),
 ('Metadata/Monsters/MudBurrower/MudBurrowerHeadBossMinion1', 'The Devourer'),
 ('Metadata/Monsters/MudBurrower/MudBurrowerHeadBossMinion2', 'Gorian, the Moving Earth'),
 ('Metadata/Monsters/ChimeraWetlandsBoss/ChimeraWetlandsBossMinion1', 'Xyclucian, the Chimera'),
 ('Metadata/Monsters/ChimeraWetlandsBoss/ChimeraWetlandsBossMinion2', 'Xilozoma, the Maw-Beast'),
 ('Metadata/Monsters/Ultimatum/ChimeraUltimatumBossMinion1', 'Uxmal, the Beastlord'),
 ('Metadata/Monsters/Ultimatum/ChimeraUltimatumBossMinion2', 'Gressor-Kul, the Apex'),
 ('Metadata/Monsters/Bird2/MutantBird2Minion1', 'Scourge of the Skies'),
 ('Metadata/Monsters/Bird2/MutantBird2Minion2', 'Chetza, the Feathered Plague'),
 ('Metadata/Monsters/HyenaMonster/RathbreakerBossMinion1', 'Rathbreaker'),
 ('Metadata/Monsters/HyenaMonster/RathbreakerBossMinion2', 'Caedron, the Hyena Lord'),
 ('Metadata/Monsters/Quadrilla/QuadrillaBossMinion1', 'Mighty Silverfist'),
 ('Metadata/Monsters/Quadrilla/QuadrillaBossMinion2', 'Zekoa, the Headcrusher'),
 ('Metadata/Monsters/Quadrilla/IcyQuadrillaBossMinion1', 'The Abominable Yeti'),
 ('Metadata/Monsters/Quadrilla/IcyQuadrillaBossMinion2', 'The Frostborn Fiend'),
 ('Metadata/Monsters/GreatWhiteOne/GreatWhiteOneMinion1', 'Great White One'),
 ('Metadata/Monsters/GreatWhiteOne/GreatWhiteOneMinion2', 'The Sandstrider'),
 ('Metadata/Monsters/Goblins/Beast/ArenaBeastBossMinion1_', 'The Ravenous Fang'),
 ('Metadata/Monsters/ChaosGodOwlBoss/ChaosGodOwlBossMinion', 'Bahlak, the Sky Seer'),
 ('Metadata/Monsters/ChaosGodOwlBoss/IcyOwlBossMinion1', 'Thraeven, Wing of Winter'),
 ('Metadata/Monsters/ChaosGodOwlBoss/IcyOwlBossMinion2', 'Thraeven, Wing of Winter'),
 ('Metadata/Monsters/MarakethSanctumTrial/Boss/Shakari/ShakariMinion1_', 'Ashar, the Sand Mother'),
 ('Metadata/Monsters/MarakethSanctumTrial/Boss/Shakari/ShakariMinion2', 'Karash, The Dune Dweller'),
 ('Metadata/Monsters/Goblins/Beast/FireBeastBoss/FireBeastBossMinion1', 'Vornas, the Fell Flame'),
 ('Metadata/Monsters/Goblins/Beast/FireBeastBoss/FireBeastBossMinion2', 'Morvak, the Infernal'),
 ('Metadata/Monsters/MarakethSanctumTrial/Boss/Shakari/ShakariDuoMinion', 'Akthi, the Final Sting'),
 ('Metadata/Monsters/Monkeys/MonkeyJungleTamed', 'Feral Primate'),
 ('Metadata/Monsters/QuillCrab/QuillCrabBigElite', 'Porcupine Crab'),
 ('Metadata/Monsters/QuillCrab/QuillCrabBigPoisonElite', 'Venomous Crab Matriarch'),
 ('Metadata/Monsters/HuhuGrub/HuhuGrubLarvaeRanged1Spectre', 'Flesh Larva'),
 ('Metadata/Monsters/DemonSpiders/BlackStrider', 'Black Strider'),
 ('Metadata/Monsters/DemonSpiders/BlackStriderSanctumTrial', 'Black Strider'),
 ('Metadata/Monsters/EtchedBeetles/SmallEtchedBeetleArmouredDullSanctumScorpionBoss', 'Tarnished Beetle'),
 ('Metadata/Monsters/EtchedBeetles/MediumEtchedBeetleArmouredTuskWideSanctumTrial', 'Adorned Scarab'),
 ('Metadata/Monsters/EtchedBeetles/LargeEtchedBeetleBossMinion', 'Adorned Beetle'),
 ('Metadata/Monsters/HyenaMonster/HyenaMonsterHighAggro', 'Hyena Demon'),
 ('Metadata/Monsters/HyenaMonster/HyenaCentaurSpearBossMinion_', 'Sun Clan Scavenger'),
 ('Metadata/Monsters/PorcupineAnt/PorcupineAntMediumSanctumTrial', 'Rasp Scavenger'),
 ('Metadata/Monsters/PorcupineAnt/PorcupineAntLargeSanctumTrial', 'Rasp Scavenger'),
 ('Metadata/Monsters/CaveDweller/CaveDwellerSanctumTrial__', 'Tombshrieker'),
 ('Metadata/Monsters/PlagueNymph/PlagueNymphFoundry', 'Plague Nymph'),
 ('Metadata/Monsters/ChawMongrel/ChawMongrelLeashBoss', 'Chaw Mongrel'),
 ('Metadata/Monsters/Goblins/Beast/ArenaBeastBossMinion2', 'The Ravenous Fang'),
 ('Metadata/Monsters/ParasiteMonsters/ParasiteMonster01', 'Armoured Parasite'),
 ('Metadata/Monsters/ParasiteMonsters/ParasiteMonster02', 'Kreth Parasite'),
 ('Metadata/Monsters/MorayClanMonster/MorayClan', 'Moray Clan'),
 ('Metadata/Monsters/Baron/BaronWerewolfProwlerSummon', 'Tendril Prowler'),
 ('Metadata/Monsters/RabidFeralDogMonster/RabidDogLargeFarmlandsNoName', 'Rabid Dog'),
 ('Metadata/Monsters/PlagueNymph/TwilightOrderPlagueNymph', 'Nymph Wasp'),
 ('Metadata/Monsters/MudBurrower/DevourerDuo/DevourerBossDuoHeadMinion', 'Anundr, the Sandworm')]

_SUPPORT_NAMES = _index((name, effect) for name, effect in _GEM_ROWS)
_SUPPORT_IDS = {effect for _, effect in _GEM_ROWS}
_SPECIES_NAMES = _index(("Companion: " + name, species) for species, name in _SPECIES_ROWS)
_SPECIES_IDS = {species for species, _ in _SPECIES_ROWS}
_MOD_NAMES = _index((name, identifier) for identifier, name in _MOD_ROWS)
_MOD_IDS = {identifier for identifier, _ in _MOD_ROWS}
_LINK = re.compile(r"\[([^\[\]|\r\n]{1,160})\|([^\[\]\r\n]{1,400})\]")
_HEX = re.compile(r"[0-9a-f]{64}")


class BeastMetadataError(ValueError):
    """Fixed private ingestion diagnostic; never embeds source data."""

    def __init__(self):
        super().__init__("invalid_beast_metadata")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _integer(value, low, high):
    if type(value) is int and low <= value <= high:
        return value
    raise BeastMetadataError()


def _xml_integer(value, low, high):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,5}", value):
        return _integer(int(value), low, high)
    raise BeastMetadataError()


def _text(value, maximum=256):
    if not isinstance(value, str) or len(value) > maximum:
        raise BeastMetadataError()
    return value


def _support_name(value):
    return _SUPPORT_NAMES.get(_normalise(_text(value)))


def _species_name(value):
    return _SPECIES_NAMES.get(_normalise(_text(value)))


def _signature(species, level, quality, supports):
    return ("SummonBeastPlayer", species, level, quality, tuple(sorted(supports)))


def _signature_digest(signature):
    return hashlib.sha256(_json(signature)).hexdigest()


def _properties(value):
    """Bound and classify exact labels. Unknown lines remain incomplete."""
    if not isinstance(value, list) or len(value) > 8:
        raise BeastMetadataError()
    canonical_source, lines = [], []
    for prop in value:
        if not isinstance(prop, dict):
            raise BeastMetadataError()
        name = _text(prop.get("name"))
        mode = _integer(prop.get("displayMode"), 0, 8)
        values = prop.get("values")
        if not isinstance(values, list) or len(values) != 1:
            raise BeastMetadataError()
        cell = values[0]
        if not isinstance(cell, list) or len(cell) != 2:
            raise BeastMetadataError()
        raw = _text(cell[0], 4096)
        colour = _integer(cell[1], 0, 20)
        canonical_source.append({"name": name, "displayMode": mode, "values": [[raw, colour]]})
        # Only the observed modifier-list presentation is understood.
        if mode != 3:
            lines.append(None)
            continue
        for line in raw.splitlines():
            if not line.strip():
                continue
            display = _LINK.sub(lambda match: match[2], line)
            lines.append(_MOD_NAMES.get(_normalise(display)))
    if len(lines) > 4:
        return canonical_source, [], False
    identifiers = sorted({line for line in lines if line is not None})
    complete = bool(lines) and None not in lines and len(identifiers) == len(lines)
    return canonical_source, identifiers, complete


def _model_entries(model):
    groups = model.get("skills", [])
    if not isinstance(groups, list) or len(groups) > 1000:
        raise BeastMetadataError()
    entries, source = [], []
    for group in groups:
        if not isinstance(group, dict):
            raise BeastMetadataError()
        gems = group.get("allGems", [])
        if not isinstance(gems, list) or len(gems) > 32:
            raise BeastMetadataError()
        for active in gems:
            if not isinstance(active, dict) or not isinstance(active.get("itemData"), dict):
                continue
            item = active["itemData"]
            has_properties = "tamedBeastProperties" in item
            # gemSkill is a display string, not a canonical identifier.
            species = _species_name(active.get("name", "")) if item.get("support") is False else None
            if not has_properties and species is None:
                continue
            properties, identifiers, complete = _properties(item["tamedBeastProperties"]) if has_properties else (None, [], False)
            signature = None
            try:
                if species is None or item.get("support") is not False:
                    raise BeastMetadataError()
                # Every supplied active-item display identity must agree.
                for field in ("name", "baseType", "typeLine"):
                    if item.get(field) and _species_name(item[field]) != species:
                        raise BeastMetadataError()
                supports = []
                for gem in gems:
                    if gem is active:
                        continue
                    if not isinstance(gem, dict) or not isinstance(gem.get("itemData"), dict) or gem["itemData"].get("support") is not True:
                        raise BeastMetadataError()
                    support = _support_name(gem.get("name"))
                    if support is None:
                        raise BeastMetadataError()
                    supports.append(support)
                signature = _signature(species, _integer(active.get("level"), 1, 100),
                                       _integer(active.get("quality"), 0, 100), supports)
            except BeastMetadataError:
                pass
            entries.append((signature, identifiers, complete, has_properties))
            # Hash only bounded matching input and private properties. No raw
            # input is written to the sidecar or the public build projection.
            source.append({"signature": signature, "properties": properties})
            if len(entries) > 32:
                raise BeastMetadataError()
    if len(_json(source)) > MAX_BEAST_METADATA_BYTES:
        raise BeastMetadataError()
    return entries, source


def _xml_entries(code):
    xml = decode_pob(code)
    project_pob(xml, "bld_" + "0" * 32)  # Existing bounded XML validation.
    root = ElementTree.fromstring(xml, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    sections = root.findall("Skills")
    if len(sections) != 1:
        return []
    # Current Ninja exports use explicit SkillSet IDs. Legacy direct groups
    # have an engine-specific implicit-set mapping and cannot be safely bound.
    if sections[0].findall("Skill"):
        return [(None, {"skill_set_id": 0, "skill_group": 1, "gem_index": 1})]
    sections = [(_xml_integer(node.get("id"), 1, 10000), node)
                for node in sections[0].findall("SkillSet")]
    if len({set_id for set_id, _ in sections}) != len(sections):
        # Lua indexes sets by ID; duplicate IDs cannot identify one group.
        return [(None, {"skill_set_id": 0, "skill_group": 1, "gem_index": 1})]
    builds = root.findall("Build")
    declared_species = ({beast.get("id") for beast in builds[0].findall("BeastCompanion")}
                        if len(builds) == 1 else set())
    result = []
    for set_id, section in sections:
        for group_index, group in enumerate(section.findall("Skill"), 1):
            gems = group.findall("Gem")
            for gem_index, active in enumerate(gems, 1):
                if active.get("skillId") != "SummonBeastPlayer":
                    continue
                signature = None
                try:
                    species = _species_name(active.get("nameSpec"))
                    if (species is None or active.get("skillMinion") != species
                            or species not in declared_species
                            or active.get("skillMinionCalcs") not in (None, species)
                            or len(gems) > 32):
                        raise BeastMetadataError()
                    supports = []
                    for gem in gems:
                        if gem is active:
                            continue
                        support = _support_name(gem.get("nameSpec"))
                        # Name and saved canonical effect must both agree.
                        if support is None or gem.get("skillId") != support:
                            raise BeastMetadataError()
                        supports.append(support)
                    signature = _signature(species, _xml_integer(active.get("level"), 1, 100),
                                           _xml_integer(active.get("quality", "0"), 0, 100), supports)
                except BeastMetadataError:
                    pass
                result.append((signature, {"skill_set_id": set_id, "skill_group": group_index,
                    "gem_index": gem_index, "skill_id": "SummonBeastPlayer"}))
    return result


def build_beast_metadata(model, code: bytes) -> bytes | None:
    """Capture a bounded canonical sidecar from one model/export response."""
    model_entries, source = _model_entries(model)
    if not any(row[3] for row in model_entries):
        return None
    xml_entries = _xml_entries(code)
    model_counts = Counter(row[0] for row in model_entries)
    xml_counts = Counter(row[0] for row in xml_entries)
    by_signature = {signature: position for signature, position in xml_entries}
    matched, unresolved = [], 0
    # An unidentified beast on either side could duplicate a known signature.
    # Refuse association rather than making an incomplete uniqueness claim.
    uncertain = None in model_counts or None in xml_counts
    for signature, identifiers, complete, supplied in model_entries:
        if not supplied:
            continue
        if uncertain or signature is None or model_counts[signature] != 1 or xml_counts[signature] != 1:
            unresolved += 1
            continue
        matched.append({**by_signature[signature], "species_id": signature[1],
            "level": signature[2], "quality": signature[3],
            "signature_sha256": _signature_digest(signature), "mod_ids": identifiers, "complete": complete})
    result = {"schema_version": 1, "export_sha256": hashlib.sha256(code).hexdigest(),
        "provenance": _PROVENANCE, "species_verified": True,
        "source_metadata_sha256": hashlib.sha256(_json(source)).hexdigest(),
        "unresolved_records": unresolved, "gems": sorted(matched, key=lambda row: (row["skill_set_id"], row["skill_group"], row["gem_index"]))}
    encoded = _json(result)
    if len(encoded) > MAX_BEAST_METADATA_BYTES:
        raise BeastMetadataError()
    return encoded


def validate_beast_metadata(encoded: bytes, code: bytes) -> dict:
    """Verify a private sidecar against unchanged export bytes before use."""
    try:
        if len(encoded) > MAX_BEAST_METADATA_BYTES:
            raise BeastMetadataError()
        value = json.loads(encoded)
        if not isinstance(value, dict) or set(value) != {"schema_version", "export_sha256", "provenance", "species_verified", "source_metadata_sha256", "unresolved_records", "gems"}:
            raise BeastMetadataError()
        if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["provenance"] != _PROVENANCE or value["species_verified"] is not True:
            raise BeastMetadataError()
        if value["export_sha256"] != hashlib.sha256(code).hexdigest() or not isinstance(value["source_metadata_sha256"], str) or not _HEX.fullmatch(value["source_metadata_sha256"]):
            raise BeastMetadataError()
        _integer(value["unresolved_records"], 0, 32)
        if not isinstance(value["gems"], list) or len(value["gems"]) > 32:
            raise BeastMetadataError()
        entries = _xml_entries(code)
        counts = Counter(signature for signature, _ in entries)
        known = {(position["skill_set_id"], position["skill_group"], position["gem_index"]): signature for signature, position in entries}
        seen = set()
        for row in value["gems"]:
            if not isinstance(row, dict) or set(row) != {"skill_set_id", "skill_group", "gem_index", "skill_id", "species_id", "level", "quality", "signature_sha256", "mod_ids", "complete"}:
                raise BeastMetadataError()
            coordinate = (_integer(row["skill_set_id"], 1, 10000), _integer(row["skill_group"], 1, 10000), _integer(row["gem_index"], 1, 32))
            signature = known.get(coordinate)
            if coordinate in seen or signature is None or counts[signature] != 1:
                raise BeastMetadataError()
            seen.add(coordinate)
            if row["signature_sha256"] != _signature_digest(signature) or row["skill_id"] != signature[0] or row["species_id"] != signature[1] or type(row["level"]) is not int or row["level"] != signature[2] or type(row["quality"]) is not int or row["quality"] != signature[3]:
                raise BeastMetadataError()
            if not isinstance(row["mod_ids"], list) or len(row["mod_ids"]) > 4 or any(not isinstance(identifier, str) or identifier not in _MOD_IDS for identifier in row["mod_ids"]) or len(set(row["mod_ids"])) != len(row["mod_ids"]) or type(row["complete"]) is not bool:
                raise BeastMetadataError()
            if row["complete"] and not row["mod_ids"]:
                raise BeastMetadataError()
        return value
    except Exception:
        raise BeastMetadataError() from None
