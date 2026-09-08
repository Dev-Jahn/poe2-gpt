"""Calculate Spirit Vessel actors and the attacks actually socketed into them.

Sources: https://poe2db.tw/us/DNT_Spirit_Vessel (actor Life multiplier 2.1)
and https://poe2db.tw/us/Spirit_Vessel (minion level 2 * gem level, quality,
and 20% more Damage per different eligible socketed skill). Its empty static
monster skill list is replaced by copies of eligible socketed attack skills.
Per-skill hit calculations do not imply an AI rotation or charge/rage uptime.
"""
from pathlib import Path


SPIRIT_VESSEL_SKILLS = r'''
-- PoE2Companion: Spirit Vessel copies socketed skills, not the player's weapon
-- or passive damage. Keep the source instance/quality/level, then build every
-- copy with the ordinary minion support and offence pipeline.
local function spiritVesselCopies(env, owner)
	local result, seen = { }, { }
	for _, gem in ipairs(owner.socketGroup and owner.socketGroup.gemList or { }) do
		local granted = gem.gemData and gem.gemData.grantedEffect or gem.grantedEffect
		local types = granted and granted.skillTypes or { }
		if gem.enabled ~= false and granted and not granted.support and types[SkillType.Shapeshift]
			and (types[SkillType.Bear] or types[SkillType.Wolf] or types[SkillType.Wyvern])
			and not types[SkillType.InbuiltTrigger] and not seen[granted.id] then
			seen[granted.id] = true
			local effect
			for _, source in ipairs(env.player.activeSkillList or { }) do
				if source.activeEffect.srcInstance == gem and source.activeEffect.grantedEffect.id == granted.id then
					effect = source.activeEffect
					break
				end
			end
			result[#result + 1] = { granted = granted, gem = gem, effect = effect }
		end
	end
	return result
end

local function spiritVesselActorData(env, owner)
	local copies = spiritVesselCopies(env, owner)
	local attacks = 0
	for _, copy in ipairs(copies) do if copy.granted.skillTypes[SkillType.Attack] then attacks = attacks + 1 end end
	if attacks == 0 or owner.activeEffect.level < 1 or owner.activeEffect.level > 40 then return nil end
	local id = "Metadata/Monsters/Companions/SpiritVessel"
	-- Public monster base stats, including its explicit intrinsic attack-speed mod.
	env.data.minions[id] = { name = "Spirit Vessel", life = 2.1, damage = 2.1, damageSpread = 0,
		attackTime = 1, attackRange = 6, accuracy = 1, critChance = 5,
		fireResist = 0, coldResist = 0, lightningResist = 0, chaosResist = 0, skillList = { },
		modList = { modLib.createMod("Speed", "INC", 25, "Spirit Vessel", ModFlag.Attack),
			modLib.createMod("Damage", "MORE", (owner.skillData.spiritVesselDamagePerSkill or 20) * #copies, "Spirit Vessel") } }
	return id
end

local function createSpiritVesselSkills(env, owner)
	local minion = owner.minion
	minion.activeSkillList = { }
	local supports = { }
	for _, support in ipairs(owner.supportList or { }) do
		-- The hidden meta support disables self-casting; it must not disable copies.
		if support.grantedEffect.id ~= "SpiritVesselSupport" then supports[#supports + 1] = support end
	end
	for _, copy in ipairs(spiritVesselCopies(env, owner)) do
		if copy.granted.skillTypes[SkillType.Attack] then
			local source = copy.effect
			local effect = { grantedEffect = copy.granted, gemData = copy.gem.gemData,
				level = source and source.level or copy.gem.level or 1,
				quality = source and source.quality or copy.gem.quality or 0,
				srcInstance = copyTable(copy.gem, true),
				statSet = { index = source and source.statSet and source.statSet.index or 1 },
				statSetCalcs = { index = source and source.statSetCalcs and source.statSetCalcs.index or 1 } }
			-- The Vessel's static minion types only describe melee attacks. Use
			-- this actual copy's types for projectile/area support compatibility.
			local summon = setmetatable({ minionSkillTypes = copy.granted.skillTypes }, { __index = owner })
			local skill = calcs.createActiveSkill(effect, supports, env, minion, nil, summon)
			calcs.buildActiveSkillModList(env, skill)
			local flags = env.mode == "CALCS" and effect.statSetCalcs.skillFlags or effect.statSet.skillFlags
			flags.minion, flags.minionSkill, flags.haveMinion = true, true, true
			skill.companionCopiedSkill = true
			minion.activeSkillList[#minion.activeSkillList + 1] = skill
		end
	end
	local index = env.mode == "CALCS" and owner.activeEffect.srcInstance.skillMinionSkillCalcs or owner.activeEffect.srcInstance.skillMinionSkill
	index = m_max(1, m_min(index or 1, #minion.activeSkillList))
	minion.mainSkill = minion.activeSkillList[index]
	return minion.mainSkill ~= nil
end

'''


SPIRIT_VESSEL_LIFE = r'''
	-- PoE2Companion: project the Vessel Life pool independently of its selected
	-- copied attack. This also covers builds with no socketed attack and avoids
	-- selecting an arbitrary attack merely to calculate damage redirection.
	env.player.companionSpiritVesselLifeList = { }
	local seenSpiritVesselInstances = { }
	for _, activeSkill in ipairs(env.player.activeSkillList) do
		local effect = activeSkill.activeEffect
		local count, enabled = calcs.getActiveSkillCount(activeSkill)
		if effect.grantedEffect.id == "SpiritVesselPlayer" and calcs.companionIsActiveSkill(env, activeSkill) and enabled and count > 0
			and not seenSpiritVesselInstances[effect.srcInstance]
			and not (calcs.companionIsGrantMirror and calcs.companionIsGrantMirror(env, activeSkill)) then
			seenSpiritVesselInstances[effect.srcInstance] = true
			-- Public level progression is verified for gem levels 1 through 40.
			-- Never extrapolate the unrelated generated actorLevel float.
			if effect.level >= 1 and effect.level <= 40 then
				local level = 2 * effect.level
				local idleSkill = { activeEffect = { statSet = { skillFlags = { } }, statSetCalcs = { skillFlags = { } } }, skillData = { }, skillTypes = { }, skillModList = new("ModList"):ModList() }
				local vessel = { type = "Metadata/Monsters/Companions/SpiritVessel", level = level, lifeTable = env.data.monsterAllyLifeTable,
					minionData = { name = "Spirit Vessel", life = 2.1, fireResist = 0, coldResist = 0, lightningResist = 0, chaosResist = 0, modList = { } },
					parent = env.player, enemy = env.enemy, itemList = { }, weaponData1 = { type = "None" }, weaponData2 = { },
					mainSkill = idleSkill, activeSkillList = { }, output = { }, hiddenDamageFixup = 0, modDB = new("ModDB"):ModDB() }
				vessel.modDB.actor = vessel
				local probe = setmetatable({ minion = vessel }, { __index = activeSkill })
				initMinionModDB(env, probe)
				addMinionModifiers(activeSkill.skillModList, activeSkill.skillCfg, vessel)
				for _, name in ipairs(vessel.modDB:List(nil, "Keystone")) do
					if env.spec.tree.keystoneMap[name] then vessel.modDB:AddList(env.spec.tree.keystoneMap[name].modList) end
				end
				for _, modList in pairs(buffs) do addMinionModifiers(modList, activeSkill.skillCfg, vessel) end
				doActorAttribsConditions(env, vessel)
				calcs.doActorLifeManaSpirit(vessel, true)
				local distinctSkills, seenSkills = 0, { }
				for _, gem in ipairs(activeSkill.socketGroup and activeSkill.socketGroup.gemList or { }) do
					local granted = gem.gemData and gem.gemData.grantedEffect
					local types = granted and granted.skillTypes or { }
					if gem.enabled ~= false and granted and not granted.support and types[SkillType.Shapeshift]
						and (types[SkillType.Bear] or types[SkillType.Wolf] or types[SkillType.Wyvern])
						and not types[SkillType.InbuiltTrigger] and not seenSkills[granted.id] then
						seenSkills[granted.id] = true
						distinctSkills = distinctSkills + 1
					end
				end
				t_insert(env.player.companionSpiritVesselLifeList, { skill_id = "SpiritVesselPlayer", minion_id = vessel.type,
					life = vessel.output.Life, level = level, socketed_skill_count = distinctSkills, damage_more_percent = 20 * distinctSkills,
					damageable = not activeSkill.skillTypes[SkillType.MinionsAreUndamagable] })
			end
		end
	end

'''


def _replace(path: Path, old: str, new: str) -> None:
    source = path.read_text()
    if new in source:
        return
    if source.count(old) != 1:
        raise SystemExit('spirit_vessel_patch_anchor_mismatch')
    path.write_text(source.replace(old, new, 1))


def patch_spirit_vessel(destination: Path) -> None:
    other = destination / 'src/Data/Skills/other.lua'
    _replace(other, '\t\t\tlabel = "Spirit Vessel",\n', '''\t\t\tlabel = "Spirit Vessel",
\t\t\tstatMap = {
\t\t\t\t["spirit_vessel_damage_+%_final_per_skill_socketed_in_meta_gem"] = {
\t\t\t\t\tskill("spiritVesselDamagePerSkill", nil),
\t\t\t\t},
\t\t\t},
''')
    active = destination / 'src/Modules/CalcActiveSkill.lua'
    _replace(active, '-- Build list of modifiers for given active skill', SPIRIT_VESSEL_SKILLS + '-- Build list of modifiers for given active skill')
    _replace(active, '\tif activeGrantedEffect.minionList and activeGrantedEffect.name:match("^Spectre") then', '''\tif activeGrantedEffect.id == "SpiritVesselPlayer" then
\t\tlocal id = spiritVesselActorData(env, activeSkill)
\t\tminionList = id and { id } or { }
\t\tactiveSkill.skillData.minionLevel = 2 * activeEffect.level
\telseif activeGrantedEffect.minionList and activeGrantedEffect.name:match("^Spectre") then''')
    _replace(active, 'function calcs.createMinionSkills(env, activeSkill)\n', '''function calcs.createMinionSkills(env, activeSkill)
\tif activeSkill.activeEffect.grantedEffect.id == "SpiritVesselPlayer" and createSpiritVesselSkills(env, activeSkill) then return end
''')
    perform = destination / 'src/Modules/CalcPerform.lua'
    _replace(perform, '\t\t\treturn activeSkill.skillTypes[SkillType.Companion] and not activeSkill.skillTypes[SkillType.MinionsAreUndamagable]', '\t\t\treturn activeSkill.activeEffect.grantedEffect.id ~= "SpiritVesselPlayer" and activeSkill.skillTypes[SkillType.Companion] and not activeSkill.skillTypes[SkillType.MinionsAreUndamagable]')
    anchor = '\t-- Total life of spectres, for "% of Damage from Hits is taken from your Spectres\' Life before you"'
    source = perform.read_text()
    legacy = '\t-- PoE2Companion: Spirit Vessel has a verified Life actor but no imported\n'
    if legacy in source:
        if source.count(legacy) != 1 or source.count(anchor) != 1:
            raise SystemExit('spirit_vessel_patch_anchor_mismatch')
        start, end = source.index(legacy), source.index(anchor)
        if end <= start:
            raise SystemExit('spirit_vessel_patch_anchor_mismatch')
        perform.write_text(source[:start] + SPIRIT_VESSEL_LIFE + source[end:])
    _replace(perform, anchor, SPIRIT_VESSEL_LIFE + anchor)
    anchor = '\t\tmodDB:NewMod("TotalCompanionLife", "BASE", totalCompanionLife, "Companions")'
    _replace(perform, anchor, '''\t\t-- Spirit Vessel has no fabricated damage skill, but its Life still
\t\t-- protects the player when incoming damage is redirected to Companions.
\t\tfor _, vessel in ipairs(env.player.companionSpiritVesselLifeList or { }) do
\t\t\tif vessel.damageable then
\t\t\t\ttotalCompanionLife = totalCompanionLife + vessel.life
\t\t\t\tt_insert(companionLifeList, { name = "Spirit Vessel", life = vessel.life })
\t\t\tend
\t\tend
''' + anchor)
