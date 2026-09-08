"""Private captured-beast state and explicit Natural Order snapshots.

Reviewed PR2147 f2593c10320df3faf74008081548e433d5e849e8 supplies the
captured modifier catalogue and persistence format. The headless backport
rejects ambiguous names, bounds retained modifiers, and never fabricates them.
Azmeri values use PoE2DB's monster possession (Haunted), not player/charm buffs:
https://poe2db.tw/us/Azmeri_Spirit. Periodic summoned-animal attacks remain
separate from these static possession bonuses.
"""
from pathlib import Path
import hashlib
import re


def replace(path, old, new):
    source = path.read_text()
    if new in source:
        return
    if source.count(old) != 1:
        raise SystemExit('companion_states_patch_anchor_mismatch')
    path.write_text(source.replace(old, new, 1))


DATA_HELPERS = r'''
-- PoE2Companion: exact imported captured modifiers; no inferred random roll.
data.tamedBeastMods = { }
LoadModule("Data/TamedBeastMods", data.tamedBeastMods, makeSkillMod, makeFlagMod)
-- PoE2DB Tame_Beast / Archnemesis Mods supplies these currently unmapped
-- game stats. Use native actor modifiers, not generic player modifiers.
data.tamedBeastMods.PlayerMonsterStunDamageIncrease1.modList = { makeSkillMod("EnemyHeavyStunBuildup", "INC", 100) }
data.tamedBeastMods.PlayerMonsterStunDamageIncrease1.companionIncomplete = false
data.tamedBeastMods.PlayerMonsterExtraEnergyShield1.modList = { makeSkillMod("EnergyShield", "BASE", 1, 0, 0, { type = "PercentStat", stat = "Life", percent = 25 }) }
data.tamedBeastMods.PlayerMonsterExtraEnergyShield1.companionIncomplete = false
data.tamedBeastMods.PlayerMonsterAreaOfEffect1.modList = { makeSkillMod("AreaOfEffect", "MORE", 100) }
data.tamedBeastMods.PlayerMonsterAreaOfEffect1.companionIncomplete = false
table.insert(data.tamedBeastMods.PlayerMonsterArmourPenetration1.modList, makeSkillMod("ArmourBreakPhysicalDamagePercent", "BASE", 1000))
for _, element in ipairs({ "Cold", "Lightning", "Chaos" }) do
	table.insert(data.tamedBeastMods.PlayerMonsterIgniteChanceIncrease1.modList, makeFlagMod(element .. "CanIgnite"))
end
for _, element in ipairs({ "Cold", "Fire", "Chaos" }) do
	table.insert(data.tamedBeastMods.PlayerMonsterShockChanceIncrease1.modList, makeFlagMod(element .. "CanShock"))
end
-- Chill's minimum potency is not implemented by the pinned damage calculator;
-- apply its verified damage eligibility and keep the row partial.
for _, element in ipairs({ "Physical", "Fire", "Lightning", "Chaos" }) do
	table.insert(data.tamedBeastMods.PlayerMonsterFreezeDamageIncrease1.modList, makeFlagMod(element .. "CanChill"))
end
function data.normaliseBeastModLine(line)
	return (line:lower():gsub("^%s+", ""):gsub("%s+$", ""))
end
function data.beastModCanSpawn(beastMod, monsterTags, unique)
	local tags = { boss = unique == true }
	for _, tag in ipairs(monsterTags or { }) do tags[tag] = true end
	for _, entry in ipairs(beastMod.spawnWeights or { }) do
		if entry.tag == "default" or tags[entry.tag] then return entry.weight > 0 end
	end
	return false
end
data.tamedBeastModsByDisplay = { }
do
	local function index(text, id)
		local key = data.normaliseBeastModLine(text)
		local old = data.tamedBeastModsByDisplay[key]
		if old == nil then data.tamedBeastModsByDisplay[key] = id
		elseif old ~= id then data.tamedBeastModsByDisplay[key] = false end
	end
	for id, beastMod in pairs(data.tamedBeastMods) do
		for _, mod in ipairs(beastMod.modList) do mod.source = "Beast Mod:" .. id end
		for _, line in ipairs(beastMod.statDescriptions) do index(line, id) end
		index(beastMod.name, id)
	end
end
'''

IMPORT_HELPER = r'''
-- PoE2Companion: unsupported labels stay private, never become guessed IDs.
function ImportTabClass:ParseTamedBeastProperties(properties)
	local list = { }
	for _, property in ipairs(properties or { }) do
		local text = property.values and property.values[1] and property.values[1][1]
		if type(text) == "string" then
			for line in text:gmatch("[^\n]+") do
				local display = escapeGGGString(line)
				local id = line:match("^%[([%w_]+)%s*|[^%]]*%]$")
				if not (id and self.build.data.tamedBeastMods[id]) then
					id = self.build.data.tamedBeastModsByDisplay[self.build.data.normaliseBeastModLine(display)]
				end
				t_insert(list, { modId = id or nil, enabled = true })
				if #list >= 5 then return list end -- invalid excess remains observable
			end
		end
	end
	return list[1] and list or nil
end

'''

CALC_HELPERS = r'''
-- PoE2Companion: eligibility and completeness shared by calculation/projection.
function calcs.companionBeastModState(env, skill)
	local effect, applied, missing = skill.activeEffect, { }, 0
	if effect.grantedEffect.id ~= "SummonBeastPlayer" then return applied, 0, false end
	local entries = effect.srcInstance.tamedBeastModList
	if not entries then return applied, 0, false end
	if effect.srcInstance.companionCapturedModsComplete == false then missing = missing + 1 end
	if #entries > 4 then return applied, #entries, true end
	local seen = { }
	for _, entry in ipairs(entries) do
		if entry.enabled ~= false then
			local model = entry.modId and env.data.tamedBeastMods[entry.modId]
			local minion = skill.minion
			if not model or seen[entry.modId] or not minion
				or not data.beastModCanSpawn(model, minion.minionData.monsterTags, minion.minionData.companionUnique) then
				missing = missing + 1
			else
				seen[entry.modId] = true
				applied[#applied + 1] = model
				if model.companionIncomplete or #model.modList == 0 then missing = missing + 1 end
			end
		end
	end
	return applied, missing, true
end

local companionSpiritBonuses = {
	owl = { { "DamageGainAsCold", "BASE", 20 }, { "EnergyShield", "INC", 60 }, { "Damage", "INC", 80 } },
	serpent = { { "PoisonChance", "BASE", 100 }, { "FireCanPoison", "FLAG", true }, { "ColdCanPoison", "FLAG", true }, { "LightningCanPoison", "FLAG", true }, { "Damage", "INC", 80 } },
	primate = { { "EnemyFreezeBuildup", "INC", 60 }, { "PhysicalCanChill", "FLAG", true }, { "FireCanChill", "FLAG", true }, { "LightningCanChill", "FLAG", true }, { "ChaosCanChill", "FLAG", true }, { "Damage", "INC", 80 } },
	bear = { { "Life", "INC", 20 }, { "EnemyHeavyStunBuildup", "INC", 60 }, { "StunThreshold", "INC", 60 }, { "DamageTaken", "INC", -20 } },
	boar = { { "DamageGainAsFire", "BASE", 20 }, { "BleedChance", "BASE", 100 }, { "DamageTaken", "INC", -20 } },
	ox = { { "Armour", "INC", 60 }, { "AilmentThreshold", "INC", 60 }, { "DamageTaken", "INC", -20 } },
	wolf = { { "MaimChance", "BASE", 50, ModFlag.Attack }, { "ArmourBreakDamagePercent", "BASE", 10 }, { "MovementSpeed", "INC", 15 }, { "Speed", "INC", 30 } },
	stag = { { "DamageGainAsLightning", "BASE", 20 }, { "ElementalResist", "BASE", 30 }, { "MovementSpeed", "INC", 15 }, { "Speed", "INC", 30 } },
	cat = { { "Evasion", "INC", 60 }, { "CritChance", "INC", 100 }, { "MovementSpeed", "INC", 15 }, { "Speed", "INC", 30 } },
}
function calcs.companionApplyCapturedState(env, skill)
	if skill.activeEffect.grantedEffect.id ~= "SummonBeastPlayer" then return end
	local minion = skill.minion
	local mods = calcs.companionBeastModState(env, skill)
	for _, model in ipairs(mods) do minion.modDB:AddList(model.modList) end
	if not minion.minionData.companionUnique or not env.modDB:Flag(nil, "UniqueTamedBeastRandomAzmeriSpirits") then return end
	local spirit = env.build.configTab.input.companionNaturalOrderSpirit
	local bonuses = companionSpiritBonuses[spirit]
	if not bonuses then return end
	for _, stat in ipairs(bonuses) do minion.modDB:NewMod(stat[1], stat[2], stat[3], "Natural Order:" .. spirit, stat[4] or 0) end
	minion.companionNaturalOrderSpirit = spirit
end

'''


def patch_companion_states(destination: Path) -> None:
    data_file = Path(__file__).with_name('data') / 'TamedBeastMods.lua'
    source = data_file.read_text()
    if hashlib.sha256(source.encode()).hexdigest() != 'f280bc35a45f833922a27d2f83d98410379edeb70c287d6ec24f2f91e51bfa51':
        raise SystemExit('companion_modifier_data_hash_mismatch')
    # Preserve verified native modifiers and mark every unmapped/generated aura
    # row partial. Upstream's presence of one mapped stat is not completeness.
    blocks = re.split(r'(?=^mods\[")', source, flags=re.M)
    for index, block in enumerate(blocks):
        match = re.match(r'mods\["([A-Za-z0-9_]+)"\]', block)
        if match and (re.search(r'^\s*-- PlayerMonster', block, re.M) or 'Aura' in match[1]):
            blocks[index] = block.replace('\n\tname = ', '\n\tcompanionIncomplete = true,\n\tname = ', 1)
    (destination / 'src/Data/TamedBeastMods.lua').write_text(''.join(blocks))
    replace(destination / 'src/Modules/Data.lua', 'data.printMissingMinionSkills = function()', DATA_HELPERS + 'data.printMissingMinionSkills = function()')
    skills = destination / 'src/Classes/SkillsTab.lua'
    anchor = '\t\tfor _, child in ipairs(child) do\n\t\t\tif child.elem == "StatSetIndex"'
    replacement = '\t\tfor _, child in ipairs(child) do\n\t\t\tif child.elem == "TamedBeastMod" then\n\t\t\t\tgemInstance.tamedBeastModList = gemInstance.tamedBeastModList or { }\n\t\t\t\tif #gemInstance.tamedBeastModList < 5 then t_insert(gemInstance.tamedBeastModList, { modId = child.attrib.modId, enabled = child.attrib.enabled ~= "false" }) end\n\t\t\telseif child.elem == "StatSetIndex"'
    replace(skills, anchor, replacement)
    anchor = '\t\t\t\tt_insert(node, gemInfo)'
    replacement = '''\t\t\t\tfor _, entry in ipairs(gemInstance.tamedBeastModList or { }) do
\t\t\t\t\tt_insert(gemInfo, { elem = "TamedBeastMod", attrib = { modId = entry.modId, enabled = tostring(entry.enabled ~= false) } })
\t\t\t\tend
''' + anchor
    replace(skills, anchor, replacement)
    importer = destination / 'src/Classes/ImportTab.lua'
    replace(importer, 'function ImportTabClass:ImportItemsAndSkills(charData)', IMPORT_HELPER + 'function ImportTabClass:ImportItemsAndSkills(charData)')
    anchor = '\t\t\tgemInstance.nameSpec = self.build.data.gems[gemId].name'
    replace(importer, anchor, '\t\t\tgemInstance.tamedBeastModList = self:ParseTamedBeastProperties(skillData.tamedBeastProperties)\n' + anchor)
    perform = destination / 'src/Modules/CalcPerform.lua'
    replace(perform, 'local function initMinionModDB(env, activeSkill)', CALC_HELPERS + 'local function initMinionModDB(env, activeSkill)')
    anchor = '\tif env.talismanModList then\n\t\t-- Adding mods provided by "Necromantic Talisman"'
    replace(perform, anchor, '\tcalcs.companionApplyCapturedState(env, activeSkill)\n' + anchor)
    options = destination / 'src/Modules/ConfigOptions.lua'
    anchor = '\t{ var = "prideEffect",'
    values = ('unknown', 'none', 'owl', 'serpent', 'primate', 'bear', 'boar', 'ox', 'wolf', 'stag', 'cat')
    choices = ','.join('{val="' + key + '",label="' + key + '"}' for key in values)
    replace(options, anchor, '\t{ var = "companionNaturalOrderSpirit", type = "list", label = "Natural Order spirit snapshot:", list = {' + choices + '}, apply = function() end },\n' + anchor)
    stats = destination / 'src/Data/SkillStatMap.lua'
    anchor = '["skill_hyena_cackle_size"] = {'
    replace(stats, anchor, '["loyalty_%_of_redirected_damage_recouped_as_life_for_owner"] = {\n\tskill("companionRedirectedDamageRecoupForOwner", nil),\n},\n' + anchor)
    replace(stats, anchor, '["display_tame_beast_mod_limit"] = {\n\tskill("companionCapturedModifierLimit", nil),\n},\n["armour_break_damage_%_dealt_as_armour_break"] = {\n\tmod("ArmourBreakDamagePercent", "BASE", nil),\n},\n' + anchor)
    offence = destination / 'src/Modules/CalcOffence.lua'
    anchor = '\t\toutput.AverageDamage = output.AverageHit * output.HitChance / 100'
    replace(offence, anchor, anchor + '''
\t\tlocal physicalHit = (output.PhysicalHitAverage or 0) * (1 - output.CritChance / 100) + (output.PhysicalCritAverage or 0) * output.CritChance / 100
\t\toutput.CompanionArmourBreakFromHit = (output.AverageHit * skillModList:Sum("BASE", cfg, "ArmourBreakDamagePercent") + physicalHit * skillModList:Sum("BASE", cfg, "ArmourBreakPhysicalDamagePercent")) / 100 * calcLib.mod(skillModList, cfg, "ArmourBreakPerHit")''')
    anchor = '\t\tcombineStat("AverageDamage", "DPS")'
    replace(offence, anchor, anchor + '\n\t\tcombineStat("CompanionArmourBreakFromHit", "DPS")')
    anchor = '\toutput.CombinedDPS = output.CombinedDPS * bestCull * output.ReservationDpsMultiplier'
    replace(offence, anchor, anchor + '''
\t\t-- PoE2Companion: armour removed by this hit, without assuming a future
\t\t-- hit sequence has already fully broken the enemy's Armour.
\t\toutput.ArmourBreakPerHit = skillModList:Flag(skillCfg, "CannotArmourBreak") and 0 or (output.ArmourBreakPerHit or 0) + (output.CompanionArmourBreakFromHit or 0)''')
