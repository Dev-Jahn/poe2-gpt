"""Captured beast ally auras with explicit recipient state.

Aura payloads and owner modifiers are distinct in PR2147's generated catalogue
(f2593c10320df3faf74008081548e433d5e849e8). PoE2DB Tame_Beast verifies the
captured modifier identities; Buffs verifies strongest-instance semantics.
No proximity, survival, or aura uptime is inferred from a character export.
"""
from pathlib import Path


def replace(path: Path, old: str, new: str) -> None:
    source = path.read_text()
    if new in source:
        return
    if source.count(old) != 1:
        raise SystemExit('beast_aura_patch_anchor_mismatch')
    path.write_text(source.replace(old, new, 1))


DATA = r'''
-- PoE2Companion: emitted ally aura differs from the owner's intrinsic stats.
data.tamedBeastMods.PlayerMonsterPhysicalDamageAura1.companionAura = {
	{ "PhysicalDamage", "INC", 40 },
}
data.tamedBeastMods.PlayerMonsterIncreasedSpeedAura1.companionAura = {
	{ "Speed", "INC", 20, ModFlag.Attack },
	{ "Speed", "INC", 20, ModFlag.Cast },
	{ "MovementSpeed", "INC", 10 },
}
for _, id in ipairs({ "PlayerMonsterPhysicalDamageAura1", "PlayerMonsterIncreasedSpeedAura1" }) do
	data.tamedBeastMods[id].companionIncomplete = false
end
-- Minimum magnitude has a separate projection; do not turn a tiny hit into an
-- observed enemy Chill. The 10% special floor / 30% ordinary threshold
-- interaction is retained as a limitation pending a verified game rule.
table.insert(data.tamedBeastMods.PlayerMonsterFreezeDamageIncrease1.modList,
	makeSkillMod("CompanionChillMinimum", "BASE", 10))
'''

HELPERS = r'''
-- Resolve saved socket groups only, never positions in the active-skill list.
function calcs.companionAuraGroup(env, skill)
	for index, group in ipairs(env.build.skillsTab.socketGroupList) do
		if group == skill.socketGroup then return index end
	end
end
local function companionAuraActive(env, skill)
	local count, enabled = calcs.getActiveSkillCount(skill)
	return skill.minion and enabled and count > 0 and calcs.companionIsActiveSkill(env, skill)
		and not calcs.companionIsGrantMirror(env, skill)
end
function calcs.companionAuraSources(env)
	local sources, seen = {}, {}
	for _, skill in ipairs(env.player.activeSkillList or {}) do
		if skill.activeEffect.grantedEffect.id == "SummonBeastPlayer" and companionAuraActive(env, skill) then
			local group = calcs.companionAuraGroup(env, skill)
			if group and not seen[group] then
				seen[group] = true
				local models = calcs.companionBeastModState(env, skill)
				local auras = {}
				for _, model in ipairs(models) do
					if model.companionAura then auras[#auras + 1] = model end
				end
				if #auras > 0 then sources[#sources + 1] = {group = group, skill = skill, auras = auras} end
			end
		end
	end
	return sources
end
local function companionAuraState(env, group)
	for _, row in ipairs(env.build.companionAuraConfiguration or {}) do
		if row.skill_group == group then return row end
	end
end
local function companionAuraRecipient(env, source, recipientGroup)
	local state = companionAuraState(env, source.group)
	if not state or not state.source_alive then return false end
	if not recipientGroup then return state.player_within_radius end
	-- "Allies" excludes the emitter. Its intrinsic modifier is already applied.
	if recipientGroup == source.group then return false end
	for _, row in ipairs(state.minion_recipients) do
		if row.skill_group == recipientGroup then return row.within_radius end
	end
	return false
end
function calcs.companionApplyAllyAuras(env, buffs, minionBuffs)
	if not env.mode_buffs then return end
	local sources = calcs.companionAuraSources(env)
	local recipientGroup = env.minion and calcs.companionAuraGroup(env, env.player.mainSkill)
	local function apply(source, targetDB, recipient, bucket)
		if not companionAuraRecipient(env, source, recipient) or targetDB:Flag(nil, "AlliesAurasCannotAffectSelf")
			or targetDB:Flag(nil, "HiddenMonster") then return end
		local effect = calcLib.mod(targetDB, nil, "BuffEffectOnSelf", "AuraEffectOnSelf")
		for _, model in ipairs(source.auras) do
			local base = new("ModList"):ModList()
			for _, stat in ipairs(model.companionAura) do
				base:NewMod(stat[1], stat[2], stat[3], "Captured Beast Aura:" .. model.name, stat[4] or 0)
			end
			local list = new("ModList"):ModList()
			list:ScaleAddList(base, effect)
			mergeBuff(list, bucket, "Captured Beast Aura:" .. model.name)
			targetDB.conditions.AffectedByAura = true
		end
	end
	for _, source in ipairs(sources) do
		apply(source, env.modDB, nil, buffs)
		if recipientGroup then apply(source, env.minion.modDB, recipientGroup, minionBuffs) end
	end
end
'''

CHILL = r'''
		-- Candidate per-hit magnitude for this captured modifier, not sustained
		-- target state. Keep unresolved minimum/threshold interaction observable.
		local companionChillMinimum = skillModList:Sum("BASE", cfg, "CompanionChillMinimum")
		if companionChillMinimum > 0 then
			local hit, crit = 0, 0
			local critUsesOrdinaryHit = skillModList:Flag(cfg, "AilmentsAreNeverFromCrit")
			for _, damageType in ipairs(dmgTypeList) do
				local eligible = damageType == "Cold" or data.defaultAilmentDamageTypes.Chill.ScalesFrom[damageType]
					or skillModList:Flag(cfg, damageType .. "CanChill") or skillModList:Flag(cfg, "CanChill")
				if canDeal[damageType] and eligible and not skillModList:Flag(cfg, damageType .. "CannotChill") then
					hit = hit + (output[damageType .. "HitAverage"] or 0)
					crit = crit + (output[damageType .. (critUsesOrdinaryHit and "HitAverage" or "CritAverage")] or 0)
				end
			end
			local magnitude = calcLib.mod(skillModList, cfg, "EnemyChillMagnitude", "AilmentMagnitude")
				* calcLib.mod(enemyDB, cfg, "SelfChillMagnitude", "AilmentMagnitude") * skillModList:More(cfg, "ChillAsThoughDealing")
			local maximum = skillModList:Override(cfg, "ChillMax") or ailmentData.Chill.max
			local cannot = skillModList:Flag(cfg, "CannotChill") or not skillFlags.hit
			local function candidate(damage)
				if cannot or damage <= 0 or magnitude <= 0 then return 0 end
				return m_min(maximum, m_max(companionChillMinimum, data.gameConstants.ChillEffectMultiplier * damage / enemyThreshold * magnitude))
			end
			output.CompanionChillMinimum = companionChillMinimum
			output.CompanionChillHitCandidate = candidate(hit)
			output.CompanionChillCritCandidate = candidate(crit)
			-- The ordinary 30% threshold is unambiguous. A smaller candidate
			-- remains unverified; never claim automatic Chill from its 10% floor.
			local avoid = m_min(100, m_max(0, enemyDB:Sum("BASE", nil, "AvoidChill", "AvoidElementalAilments", "AvoidAilments")))
			output.ChillChanceOnHit = output.CompanionChillHitCandidate >= ailmentData.Chill.min and (output.ChillChanceOnHit or 0) * (1 - avoid / 100) or 0
			output.ChillChanceOnCrit = output.CompanionChillCritCandidate >= ailmentData.Chill.min and (output.ChillChanceOnCrit or 0) * (1 - avoid / 100) or 0
			output.CompanionChillHitChance = output.ChillChanceOnHit
			output.CompanionChillCritChance = output.ChillChanceOnCrit
			skillFlags.inflictChill = output.ChillChanceOnHit + output.ChillChanceOnCrit > 0
		end
'''


def patch_beast_auras(destination: Path) -> None:
    replace(destination / 'src/Modules/Data.lua', 'function data.normaliseBeastModLine(line)', DATA + '\nfunction data.normaliseBeastModLine(line)')
    perform = destination / 'src/Modules/CalcPerform.lua'
    replace(perform, 'local function initMinionModDB(env, activeSkill)', HELPERS + '\nlocal function initMinionModDB(env, activeSkill)')
    old = 'if model.companionIncomplete or #model.modList == 0 then missing = missing + 1 end'
    new = '''if model.companionIncomplete or #model.modList == 0 then missing = missing + 1 end
				if model.companionAura then
					local group = calcs.companionAuraGroup(env, skill)
					local configured = false
					for _, state in ipairs(env.build.companionAuraConfiguration or {}) do
						if state.skill_group == group then configured = true end
					end
					if not configured then missing = missing + 1 end
				end'''
    replace(perform, old, new)
    replace(perform, '\t-- Apply buff/debuff modifiers', '\tcalcs.companionApplyAllyAuras(env, buffs, minionBuffs)\n\n\t-- Apply buff/debuff modifiers')
    offence = destination / 'src/Modules/CalcOffence.lua'
    replace(offence, '\t\toutput["FreezeChanceOnHit"] = 0', CHILL + '\n\t\toutput["FreezeChanceOnHit"] = 0')
    anchor = '\t\tcombineStat("ChillEffectMod", "AVERAGE")'
    replace(offence, anchor, anchor + '\n\t\tcombineStat("CompanionChillMinimum", "AVERAGE")\n\t\tcombineStat("CompanionChillHitCandidate", "AVERAGE")\n\t\tcombineStat("CompanionChillCritCandidate", "AVERAGE")\n\t\tcombineStat("CompanionChillHitChance", "AVERAGE")\n\t\tcombineStat("CompanionChillCritChance", "AVERAGE")')
