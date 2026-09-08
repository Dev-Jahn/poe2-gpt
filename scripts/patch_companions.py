"""Reviewed Offering and Companion corrections for the pinned PoB2 engine.

Game facts: https://poe2db.tw/us/Offering_Spike,
https://poe2db.tw/us/Trusted_Kinship, https://poe2db.tw/us/Companion.
The separate spike actor calculates Life only; it has no fabricated attack or
steady-state explosion DPS, and does not change the selected player skill.
"""
from pathlib import Path
import re


def _replace(path: Path, old: str, new: str) -> None:
    source = path.read_text()
    if new in source:
        return
    if source.count(old) != 1:
        raise SystemExit('companion_patch_anchor_mismatch')
    path.write_text(source.replace(old, new, 1))


OFFERING_LIFE = r'''
	-- PoE2Companion: calculate Offering spike Life with a separate non-attacking
	-- actor. PoE2DB Offering_Spike: Pain/Power .18, Bone .35 of ally base Life.
	-- Preserve the existing Offering buff actor and never invent spike DPS.
	env.player.companionOfferingLifeList = { }
	local offeringLifeMultipliers = { BoneOfferingPlayer = 0.35, PainOfferingPlayer = 0.18, SoulOfferingPlayer = 0.18 }
	local seenOfferingInstances = { }
	for _, activeSkill in ipairs(env.player.activeSkillList) do
		local effect = activeSkill.activeEffect
		local id = effect.grantedEffect.id
		local lifeMultiplier = offeringLifeMultipliers[id]
		local flags = env.mode == "CALCS" and effect.statSetCalcs.skillFlags or effect.statSet.skillFlags
		if lifeMultiplier and calcs.companionIsActiveSkill(env, activeSkill) and not seenOfferingInstances[effect.srcInstance] then
			seenOfferingInstances[effect.srcInstance] = true
			local level = m_min(m_max(activeSkill.skillData.minionLevel or data.minionLevelTable[effect.level] or 1, 1), 100)
			local idleSkill = { activeEffect = { statSet = { skillFlags = { } }, statSetCalcs = { skillFlags = { } } }, skillData = { }, skillTypes = { }, skillModList = new("ModList"):ModList() }
			local spike = { type = "PoE2CompanionOfferingSpike", level = level, lifeTable = env.data.monsterAllyLifeTable,
				minionData = { name = "Offering Spike", life = lifeMultiplier, fireResist = 0, coldResist = 0, lightningResist = 0, chaosResist = 0, modList = { } },
				parent = env.player, enemy = env.enemy, itemList = { }, weaponData1 = { type = "None" }, weaponData2 = { },
				mainSkill = idleSkill, activeSkillList = { }, output = { }, hiddenDamageFixup = 0, modDB = new("ModDB"):ModDB() }
			spike.modDB.actor = spike
			local probe = setmetatable({ minion = spike }, { __index = activeSkill })
			initMinionModDB(env, probe)
			addMinionModifiers(activeSkill.skillModList, activeSkill.skillCfg, spike)
			for _, name in ipairs(spike.modDB:List(nil, "Keystone")) do
				if env.spec.tree.keystoneMap[name] then spike.modDB:AddList(env.spec.tree.keystoneMap[name].modList) end
			end
			for _, modList in pairs(buffs) do addMinionModifiers(modList, activeSkill.skillCfg, spike) end
			doActorAttribsConditions(env, spike)
			calcs.doActorLifeManaSpirit(spike, true)
			t_insert(env.player.companionOfferingLifeList, { skill_id = id, life = spike.output.Life, level = level })
		end
	end

'''


def patch_companions(destination: Path) -> None:
    # Cached parse failures predate these exact parser additions. Reparse only
    # affected lines, including cached multi-line passive attempts.
    cache = destination / 'src/Data/ModCache.lua'
    affected = ('Offerings have ', 'Companions of different types', 'Unique Tamed Beasts',
                'Unique Tamed Beast summoned', 'Tame Beast can capture Unique Beasts',
                'Quantity of Gold Dropped by Slain Enemies')
    lines = cache.read_text().splitlines(keepends=True)
    cache.write_text(''.join(line for line in lines if not (line.startswith('c[') and any(key in line for key in affected))))
    parser = destination / 'src/Modules/ModParser.lua'
    anchor = '\t["^offering skills [hd][ae][va][el] "] ='
    source = parser.read_text()
    if '["^offerings [hd][ae][va][el] "]' not in source:
        if source.count(anchor) != 1:
            raise SystemExit('companion_parser_anchor_mismatch')
        source = source.replace(anchor, '\t["^offerings [hd][ae][va][el] "] = { addToMinion = true, addToMinionTag = { type = "SkillType", skillType = SkillType.Offering } },\n' + anchor)
        parser.write_text(source)
    # Store genuine modifiers/flags; the private projection validates all caps.
    anchor = '\t["companions gain your dexterity"] ='
    additions = '''\t-- PoE2Companion: distinct Companion limits are not additive.
\t["you can have two companions of different types"] = { flag("CompanionLimitTwo") },
\t["you can have any number of companions of different types"] = { flag("CompanionLimitUnlimited") },
\t["tame beast can capture unique beasts"] = { flag("CanCaptureUniqueBeasts") },
\t["can have up to one unique tamed beast summoned"] = { flag("UniqueTamedBeastLimitOne") },
\t["unique tamed beasts have (%d+)%% increased movement speed"] = function(num) return { mod("MinionModifier", "LIST", { mod = mod("MovementSpeed", "INC", num, { type = "Condition", var = "UniqueTamedBeast" }) }, { type = "SkillName", skillName = "Companion: {0}" }) } end,
\t["unique tamed beasts are possessed by random azmeri spirits, changing every 20 seconds"] = { flag("UniqueTamedBeastRandomAzmeriSpirits") },
\t["(%d+)%% increased quantity of gold dropped by slain enemies"] = function(num) return { mod("GoldQuantity", "INC", num) } end,
'''
    source = parser.read_text()
    if additions not in source:
        if source.count(anchor) != 1:
            raise SystemExit('companion_limit_anchor_mismatch')
        parser.write_text(source.replace(anchor, additions + anchor, 1))

    # The pinned data labels the unique boss block explicitly. Preserve a
    # factual per-monster classification for the same IDs used by PoB.
    spectres = destination / 'src/Data/Spectres.lua'
    source = spectres.read_text()
    if '-- PoE2Companion: unique tamed beast identity' not in source:
        unique_block = source.split('-- Unique Bosses\n', 1)
        if len(unique_block) != 2:
            raise SystemExit('companion_unique_data_anchor_mismatch')
        ids = re.findall(r'^minions\["([^"\n]+)"\] = \{', unique_block[1], re.M)
        if not ids or any(not value.startswith('Metadata/Monsters/') for value in ids):
            raise SystemExit('companion_unique_data_invalid')
        additions = '\n-- PoE2Companion: unique tamed beast identity from pinned Unique Bosses data.\n'
        additions += '\n'.join(f'minions["{value}"].companionUnique = true' for value in ids) + '\n'
        anchor = '\t\t\t    return minions'
        _replace(spectres, anchor, additions + anchor)

    perform = destination / 'src/Modules/CalcPerform.lua'
    anchor = '-- Finalises the environment and performs the stat calculations:'
    mirror_helper = '''-- PoE2Companion: imports can save an explicit socket group for a skill
-- also regenerated from its equipped item or allocated passive. Prefer the
-- explicit group (which carries the actual supports) for finite actor counts.
-- Compare saved base levels: linked Minion Mastery can raise the explicit
-- group's effective level without creating another physical companion.
function calcs.companionIsGrantMirror(env, skill)
\tlocal group = skill.socketGroup
\tif not group or not (group.sourceItem or group.sourceNode) then return false end
\tlocal effect = skill.activeEffect
\tfor _, other in ipairs(env.player.activeSkillList or { }) do
\t\tlocal otherGroup = other.socketGroup
\t\tlocal otherEffect = other.activeEffect
\t\tlocal flags = env.mode == "CALCS" and otherEffect.statSetCalcs.skillFlags or otherEffect.statSet.skillFlags
\t\tlocal count, enabled = calcs.getActiveSkillCount(other)
\t\tif other ~= skill and otherGroup and not otherGroup.source and calcs.companionIsActiveSkill(env, other) and enabled and count > 0
\t\t\tand effect.grantedEffect.id == otherEffect.grantedEffect.id
\t\t\tand effect.srcInstance.level == otherEffect.srcInstance.level then return true end
\tend
\treturn false
end

'''
    _replace(perform, anchor, mirror_helper + anchor)
    anchor = '\tlocal baseLife = minion.lifeTable[minion.level] * minion.minionData.life'
    _replace(perform, anchor, '\tminion.modDB.conditions.UniqueTamedBeast = skillFlags.summonBeast and minion.minionData.companionUnique == true\n' + anchor)
    anchor = '\t-- Total life of spectres, for "% of Damage from Hits is taken from your Spectres\' Life before you"'
    if '-- PoE2Companion: calculate Offering spike Life' not in perform.read_text():
        _replace(perform, anchor, OFFERING_LIFE + anchor)
    anchor = 'if minion and not seenMinions[minion] and not skillFlags.disable and includeSkill(activeSkill, skillFlags) then'
    _replace(perform, anchor, 'if minion and not seenMinions[minion] and calcs.companionIsActiveSkill(env, activeSkill) and not calcs.companionIsGrantMirror(env, activeSkill) and includeSkill(activeSkill, skillFlags) then')

    stat_map = destination / 'src/Data/SkillStatMap.lua'
    anchor = '["skill_hyena_cackle_size"] = {'
    _replace(stat_map, anchor, '["skill_wolf_pack_size"] = {\n\tmod("WolfLimit", "BASE", nil),\n},\n' + anchor)

    # Damageable pack members all contribute to the finite pool used when
    # damage is redirected to Companions. They still count as one Companion.
    anchor = '\t\t\t\ttotalLife = totalLife + minion.output.Life\n\t\t\t\tt_insert(lifeList, { name = minion.minionData and minion.minionData.name or activeSkill.activeEffect.grantedEffect.name, life = minion.output.Life })'
    replacement = '''\t\t\t\tlocal poolCount = 1
\t\t\t\tlocal effectId = activeSkill.activeEffect.grantedEffect.id
\t\t\t\tif effectId == "WolfPackPlayer" or effectId == "HyenaCacklePlayer" then
\t\t\t\t\tpoolCount = m_max(0, m_floor(calcLib.val(activeSkill.skillModList, minion.minionData.limit, activeSkill.skillCfg) * activeSkill.skillModList:More(activeSkill.skillCfg, "ActiveMinionLimit")))
\t\t\t\tend
\t\t\t\tlocal poolLife = minion.output.Life * poolCount
\t\t\t\ttotalLife = totalLife + poolLife
\t\t\t\tt_insert(lifeList, { name = minion.minionData and minion.minionData.name or activeSkill.activeEffect.grantedEffect.name, life = poolLife })'''
    _replace(perform, anchor, replacement)

    from patch_companion_states import patch_companion_states
    patch_companion_states(destination)
