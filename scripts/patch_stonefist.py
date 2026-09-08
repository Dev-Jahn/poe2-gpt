"""Narrow, source-anchored 0.5 patches for Stonefist and charge events.

Sources: PoE2DB Way_of_the_Stonefist, Lochtonial_Caress, The_Fabled_Stag,
Mending_Deflection, and the pinned upstream skill data. PR2350 was reviewed
but its inferred source affixes and midpoint target rolls are not imported.
"""
from pathlib import Path


def _replace(path: Path, old: str, new: str, code: str) -> None:
    source = path.read_text()
    if source.count(old) != 1 or new in source:
        raise SystemExit(code)
    path.write_text(source.replace(old, new))


def patch_stonefist(destination: Path) -> None:
    target = destination / "src/Modules/ModParser.lua"
    anchor = '\t["ignore attribute requirements"] = { flag("IgnoreAttributeRequirements") },'
    extra = '''
\t-- A slot exemption is not a global exemption. Explicit transformed item
\t-- rolls are authoritative; the companion does not infer transformed rolls.
\t["ignore attribute requirements to equip gloves"] = { flag("IgnoreGloveAttributeRequirements") },
\t["gloves you equip have their base type transformed to fists of stone while equipped, and their explicit modifiers are transformed into more powerful related modifiers"] = { flag("WayOfTheStonefist") },
\t["gloves you equip have their base type transformed to fists of stone while equipped, and their explicit modifiers are transformed into more powerful related modifiers ignore attribute requirements to equip gloves"] = {
\t\tflag("WayOfTheStonefist"), flag("IgnoreGloveAttributeRequirements"),
\t},
\t["(%d+)%% chance when you gain a power charge to gain an additional power charge"] = function(num) return { mod("AdditionalPowerChargeChance", "BASE", num) } end,
\t["(%d+)%% chance when you gain a frenzy charge to gain an additional frenzy charge"] = function(num) return { mod("AdditionalFrenzyChargeChance", "BASE", num) } end,
\t["(%d+)%% chance when you gain an endurance charge to gain an additional endurance charge"] = function(num) return { mod("AdditionalEnduranceChargeChance", "BASE", num) } end,
\t["skills have (%d+)%% chance to not remove charges but still count as consuming them"] = function(num) return { mod("ChargeNotRemovedChance", "BASE", num) } end,
\t["(%d+)%% chance to grant a power charge to allies in your presence on hit"] = function(num) return { mod("GrantAllyPowerChargeOnHitChance", "BASE", num) } end,
\t["(%d+)%% chance to grant a frenzy charge to allies in your presence on hit"] = function(num) return { mod("GrantAllyFrenzyChargeOnHitChance", "BASE", num) } end,
\t["(%d+)%% chance to grant a endurance charge to allies in your presence on hit"] = function(num) return { mod("GrantAllyEnduranceChargeOnHitChance", "BASE", num) } end,
\t["(%d+)%% chance to grant an endurance charge to allies in your presence on hit"] = function(num) return { mod("GrantAllyEnduranceChargeOnHitChance", "BASE", num) } end,
\t["(%d+)%% of damage taken from deflected hits recouped as life"] = function(num) return { mod("DeflectedLifeRecoup", "BASE", num) } end,
'''
    _replace(target, anchor, anchor + extra, "upstream_stonefist_parser_patch_mismatch")

    # Clear only the actual glove requirement row. This leaves helmet/weapon,
    # gem, support-gem, level, and class requirements untouched.
    target = destination / "src/Modules/CalcSetup.lua"
    anchor = '\t\t\t\tif item.requirements and not accelerate.requirementsItems then\n'
    extra = '\t\t\t\tlocal ignoreGloveAttributes = item.base and item.base.type == "Gloves" and nodesModsList:Flag(nil, "IgnoreGloveAttributeRequirements")\n'
    _replace(target, anchor, extra + anchor, "upstream_stonefist_requirements_patch_mismatch")
    for attr in ("Str", "Dex", "Int"):
        old = f'\t\t\t\t\t\t{attr} = item.requirements.{attr.lower()}Mod,'
        new = f'\t\t\t\t\t\t{attr} = not ignoreGloveAttributes and item.requirements.{attr.lower()}Mod or nil,'
        _replace(target, old, new, "upstream_stonefist_requirements_patch_mismatch")

    # An equipped item can grant the same narrowly scoped exemption. At this
    # stage the complete player mod DB is available, unlike the tree-only list
    # above. Level requirements remain a separate validation.
    target = destination / "src/Modules/CalcPerform.lua"
    anchor = '\t\t\t\t\t\toutput[attr.."RequirementsOn"..reqSource.sourceSlot] = req;'
    extra = '''\t\t\t\t\t\tif reqSource.sourceItem.base.type == "Gloves" and modDB:Flag(nil, "IgnoreGloveAttributeRequirements") then
\t\t\t\t\t\t\treq = 0
\t\t\t\t\t\tend
'''
    _replace(target, anchor, extra + anchor, "upstream_glove_requirement_total_patch_mismatch")

    # The global mapping applies to Perpetual Charge and anomalous Flicker
    # quality. It does not multiply burst damage or fabricate charge uptime.
    target = destination / "src/Data/SkillStatMap.lua"
    anchor = '["chance_to_gain_1_more_charge_%"] = {'
    extra = '''["charge_skip_consume_chance_%"] = {
\tmod("ChargeNotRemovedChance", "BASE", nil),
},
["consume_frenzy_power_and_endurance_charge_every_x_ms"] = {
\tskill("chargeRegulationInterval", nil),
\tdiv = 1000,
},
["chance_to_gain_1_more_random_charge_%"] = {
\tmod("AdditionalRandomChargeChance", "BASE", nil),
},
'''
    _replace(target, anchor, extra + anchor, "upstream_charge_stat_map_patch_mismatch")

    # Main imports the generated cache BEFORE loading the tree. Patching only
    # ModParser would keep the pinned cache's old failures for these exact
    # lines, including combinations attempted by PassiveTree.ProcessStats.
    target = destination / "src/Data/ModCache.lua"
    source = target.read_text()
    affected = (
        "gloves you equip have their base type transformed to fists of stone",
        "ignore attribute requirements to equip gloves",
        "chance when you gain a power charge to gain an additional power charge",
        "chance when you gain a frenzy charge to gain an additional frenzy charge",
        "chance when you gain an endurance charge to gain an additional endurance charge",
        "chance to not remove charges but still count as consuming them",
        "chance to grant a power charge to allies in your presence on hit",
        "chance to grant a frenzy charge to allies in your presence on hit",
        "chance to grant a endurance charge to allies in your presence on hit",
        "chance to grant an endurance charge to allies in your presence on hit",
        "of damage taken from deflected hits recouped as life",
    )
    lines = source.splitlines(keepends=True)
    kept = [line for line in lines if not (line.startswith('c["') and any(token in line.lower() for token in affected))]
    if len(kept) == len(lines):
        raise SystemExit("upstream_stonefist_mod_cache_patch_mismatch")
    target.write_text("".join(kept))
    patch_charge_scenarios(destination)
    patch_mountain_teachings(destination)


def patch_charge_scenarios(destination: Path) -> None:
    """Expose source-owned event rules without assuming combat event rates.

    PoE2DB Killing_Palm, Flicker_Strike, Charges, Recoup (0.5.5).
    PR1947 already supplies Flicker/Heightened burst scaling; this adds the
    event data deliberately omitted by the snapshot-only upstream planner.
    """
    target = destination / "src/Data/SkillStatMap.lua"
    anchor = '["chance_to_gain_1_more_charge_%"] = {'
    extra = '''["chance_to_gain_endurance_charge_on_armour_break_%"] = {
	skill("enduranceChargeOnFullArmourBreakChance", nil),
},
["skill_grant_X_power_charges_against_normal_and_magic_monsters"] = {
	skill("powerChargesFromNormalMagicKill", nil),
},
["skill_grant_X_power_charges_against_rare_monsters"] = {
	skill("powerChargesFromRareKill", nil),
},
["skill_grant_X_power_charges_against_unique_monsters"] = {
	skill("powerChargesFromUniqueKill", nil),
},
["skill_can_add_multiple_charges_per_action"] = {
	skill("chargeGainPerEnemyKilled", true),
},
["skill_can_flicker"] = {
	skill("chainsToAdditionalCullableTargets", true),
},
'''
    _replace(target, anchor, extra + anchor, "upstream_charge_scenario_stat_map_mismatch")
    target = destination / "src/Data/Skills/act_int.lua"
    old = '''				["cannot_gain_power_charges_during_skill"] = {
					-- Display Only
				},'''
    new = '''				["cannot_gain_power_charges_during_skill"] = {
					skill("cannotGainPowerChargesDuringSkill", true),
				},'''
    _replace(target, old, new, "upstream_flicker_charge_lockout_mismatch")
    target = destination / "src/Modules/ModParser.lua"
    anchor = '\t["recoup effects instead occur over 4 seconds"] = { flag("4SecondRecoup") },'
    extra = '''	["(%d+)%% increased speed of recoup effects"] = function(num) return { mod("RecoupSpeed", "INC", num) } end,
	["(%d+)%% reduced speed of recoup effects"] = function(num) return { mod("RecoupSpeed", "INC", -num) } end,
'''
    _replace(target, anchor, extra + anchor, "upstream_recoup_speed_parser_mismatch")
    target = destination / "src/Modules/CalcDefence.lua"
    anchor = 'local function calcRecoup(output, breakdown, modDB, recoup, recoupType, damageType)'
    extra = '''-- Recoup speed changes duration, never the total percentage recovered.
function calcs.companionRecoupDuration(modDB, resource)
	local base = (modDB:Flag(nil, "4Second"..resource.."Recoup") or modDB:Flag(nil, "4SecondRecoup")) and 4 or 8
	local speed = 1 + modDB:Sum("INC", nil, "RecoupSpeed") / 100
	return speed > 0 and base / speed or math.huge
end
'''
    _replace(target, anchor, extra + anchor, "upstream_recoup_duration_helper_mismatch")
    old = '\t\t\tlocal recoupTime = (modDB:Flag(nil, "4Second"..recoupType.."Recoup") or modDB:Flag(nil, "4SecondRecoup")) and 4 or 8'
    new = '\t\t\tlocal recoupTime = calcs.companionRecoupDuration(modDB, recoupType)'
    _replace(target, old, new, "upstream_recoup_duration_calc_mismatch")
    source = target.read_text()
    old = '(modDB:Flag(nil, "4Second" .. recoupType .. "Recoup") or modDB:Flag(nil, "4SecondRecoup")) and 4 or 8'
    if source.count(old) != 2:
        raise SystemExit("upstream_recoup_duration_breakdown_mismatch")
    source = source.replace(old, 'calcs.companionRecoupDuration(modDB, recoupType)')
    source = source.replace('over %d seconds', 'over %.2f seconds')
    target.write_text(source)
    target = destination / "src/Data/ModCache.lua"
    source = target.read_text()
    target.write_text("".join(line for line in source.splitlines(keepends=True)
        if not (line.startswith('c["') and 'speed of recoup effects' in line.lower())))


def patch_mountain_teachings(destination: Path) -> None:
    """Current Way of the Mountain (PoE2DB); reviewed PR2073 is older.

    Native snapshot buffs require explicit stacks. Thresholded damage taken is
    reserved for supplied hit events; it is never made a global 40% less mod.
    """
    target = destination / "src/Modules/ModParser.lua"
    anchor = '\t["ignore attribute requirements"] = { flag("IgnoreAttributeRequirements") },'
    extra = """
\t[\"(%d+)%% surpassing chance per enemy power to gain mountain's teachings on immobilising an enemy, up to a maximum of (%d+)\"] = function(num, _, maximum) return {
\t\tflag(\"MountainTeachings\"), mod(\"MountainTeachingsGainChance\", \"BASE\", num), mod(\"MountainTeachingsMaximum\", \"BASE\", tonumber(maximum)),
\t\tmod(\"Damage\", \"MORE\", 15, ModFlag.Attack, 0, { type=\"Condition\", var=\"MountainsTeachings\" }, { type=\"Condition\", var=\"MountainTeachingsAttackEligible\" }),
\t\tmod(\"StunThreshold\", \"MORE\", 50, 0, 0, { type=\"Condition\", var=\"MountainsTeachings\" }),
\t} end,
\t[\"lose a mountain's teaching when you are hit, or when you use or sustain an attack that benefits from mountain's teachings\"] = { flag(\"MountainTeachingsConsumeOnHitOrAttack\") },
"""
    _replace(target, anchor, anchor + extra, "upstream_mountain_parser_mismatch")
    target = destination / "src/Modules/ConfigOptions.lua"
    anchor = '\t-- Section: Skill-specific options\n'
    extra = """	{ var = "mountainTeachings", type = "count", label = "Mountain's Teachings:", ifFlag = "MountainTeachings", apply = function(val, modList, enemyModList)
		modList:NewMod("Multiplier:MountainTeachings", "BASE", math.min(30, math.max(0, val)), "Config")
		if val > 0 then modList:NewMod("Condition:MountainsTeachings", "FLAG", true, "Config") end
	end },
"""
    _replace(target, anchor, extra + anchor, "upstream_mountain_configuration_mismatch")
    target = destination / "src/Modules/CalcOffence.lua"
    anchor = 'function calcs.offence(env, actor, activeSkill)'
    extra = """-- Attacks from Martial Artist are explicitly eligible even when triggered
-- or used by Hollow Form copies. Other proxy/minion attacks remain excluded.
function calcs.companionMountainAttackEligible(active)
	local types = active.skillTypes or { }
	if not types[SkillType.Attack] then return false end
	if types[SkillType.SupportedByHollowForm] then return true end
	if active.minion or types[SkillType.Minion] or types[SkillType.Totem]
		or types[SkillType.Trap] or types[SkillType.Mine] then return false end
	return not types[SkillType.Triggered] and not types[SkillType.UsedByProxy]
end
"""
    _replace(target, anchor, extra + anchor, "upstream_mountain_eligibility_mismatch")
    anchor = '\tlocal skillCfg = activeSkill.skillCfg\n'
    extra = '\tskillCfg.skillCond.MountainTeachingsAttackEligible = calcs.companionMountainAttackEligible(activeSkill)\n'
    _replace(target, anchor, anchor + extra, "upstream_mountain_offence_mismatch")
    target = destination / "src/Data/ModCache.lua"
    source = target.read_text()
    target.write_text("".join(line for line in source.splitlines(keepends=True)
        if not (line.startswith('c["') and "mountain's teaching" in line.lower())))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    patch_stonefist(parser.parse_args().destination)
