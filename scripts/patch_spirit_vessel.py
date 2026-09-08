"""Calculate the verified Spirit Vessel Life pool without inventing copied attacks.

Sources: https://poe2db.tw/us/DNT_Spirit_Vessel (actor Life multiplier 2.1)
and https://poe2db.tw/us/Spirit_Vessel (minion level 2 * gem level, quality,
and 20% more Damage per different eligible socketed skill). The monster's
public skill list is empty; copied attack damage and rotations remain unsupported.
"""
from pathlib import Path


SPIRIT_VESSEL_LIFE = r'''
	-- PoE2Companion: Spirit Vessel has a verified Life actor but no imported
	-- attack list. Keep it separate from the selected skill and calculate only
	-- the Life pool and exact distinct-skill damage multiplier.
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
    perform = destination / 'src/Modules/CalcPerform.lua'
    anchor = '\t-- Total life of spectres, for "% of Damage from Hits is taken from your Spectres\' Life before you"'
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
