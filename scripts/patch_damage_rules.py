"""Implement PoE2 hit leech and explicit-target Impale calculations.

Rules: https://poe2db.tw/us/Life_Leech, /Mana_Leech,
/Energy_Shield_Leech and /Impale (verified 2026-09-08).
The monster resistance export comes from upstream PR #1938 at
2cc94561a8d048df48433696d019a56de1a949f0. Its PoE1 cap/rate formulas
are deliberately not used. PR #1820 supplies parser naming references;
its reflected-damage / multi-stack formula is also not used.

All anchors are checked before any files are written.
"""
from pathlib import Path


LEECH_RESISTANCE = (
    [6000] * 30
    + [6099, 6255, 6395, 6566, 6734, 6898, 7054, 7205, 7354, 7497,
       7631, 7762, 7887, 8009, 8123, 8181, 8240, 8300, 8357, 8415,
       8471, 8526, 8581, 8634, 8687, 8739, 8789, 8839, 8887, 8935,
       8981, 9026, 9070, 9112, 9153, 9201, 9247, 9291, 9333, 9373,
       9411, 9448, 9483, 9516, 9547, 9577, 9605, 9632, 9657, 9681,
       9705, 9726, 9747, 9766, 9784, 9801, 9817, 9831, 9845, 9858,
       9870, 9881, 9891, 9901, 9910, 9918, 9925, 9932, 9939, 9945]
)


def patch_damage_rules(destination: Path) -> None:
    prepared: dict[Path, str] = {}

    def replace(relative: str, old: str, new: str) -> None:
        target = destination / relative
        source = prepared.get(target, target.read_text())
        if source.count(old) != 1 or new in source:
            raise SystemExit("upstream_damage_rules_patch_mismatch")
        prepared[target] = source.replace(old, new)

    def section(relative: str, first: str, last: str, new: str) -> None:
        target = destination / relative
        source = prepared.get(target, target.read_text())
        if source.count(first) != 1 or source.count(last) != 1:
            raise SystemExit("upstream_damage_rules_patch_mismatch")
        start, end = source.index(first), source.index(last)
        replace(relative, source[start:end], new)

    offence = "src/Modules/CalcOffence.lua"
    replace("src/Data/Misc.lua", "-- From MinionGemLevelScaling.dat\n",
            "-- DefaultMonsterStats.dat export, upstream PR #1938 (0.5.0).\n"
            "data.monsterLeechResistanceTable = { "
            + ", ".join(map(str, LEECH_RESISTANCE)) + " }\n\n"
            "-- From MinionGemLevelScaling.dat\n")
    replace("src/Modules/Data.lua", "\tImpaleStoredDamageBase = 0.1,",
            '\tImpaleStoredDamageBase = data.gameConstants["ImpalePercentage"],')
    replace("src/Modules/CalcSetup.lua", '\tmodDB:NewMod("ImpaleStacksMax", "BASE", 5, "Base")',
            '\tmodDB:NewMod("ImpaleStacksMax", "BASE", data.gameConstants["ImpaleMaximumStacks"], "Base")')
    replace("src/Modules/CalcSetup.lua", '\t\t\t\t\tenv.player.mainSkill = socketGroupSkillList[activeSkillIndex]\n',
            '\t\t\t\t\tenv.player.mainSkill = socketGroupSkillList[activeSkillIndex]\n'
            '\t\t\t\t\tenv.companionImpaleSelectedEffectId = env.player.mainSkill.activeEffect.grantedEffect.id\n')

    replace("src/Modules/ModParser.lua", '["amount of life leeched"] = "MaxLifeLeechRate"',
            '["amount of life leeched"] = "LifeLeechAmount"')
    replace("src/Modules/ModParser.lua", '["amount of mana leeched"] = "MaxManaLeechRate"',
            '["amount of mana leeched"] = "ManaLeechAmount"')
    replace("src/Modules/ModParser.lua", '["impale effect"] = "ImpaleEffect",',
            '["impale effect"] = "ImpaleEffect",\n'
            '\t["impale magnitude"] = "ImpaleEffect",\n'
            '\t["magnitude of impales you inflict"] = "ImpaleEffect",\n'
            '\t["amount of energy shield leeched"] = "EnergyShieldLeechAmount",')
    replace("src/Modules/ModParser.lua", '\t["critical hits with spells inflict impale"] =',
            '\t["critical hits inflict impale"] = { mod("ImpaleChance", "BASE", 100, nil, 0, 0, { type = "Condition", var = "CriticalStrike" }) },\n'
            '\t["critical hits cannot extract impale"] = { flag("CannotExtractImpale", { type = "Condition", var = "CriticalStrike" }) },\n'
            '\t["cannot extract impale"] = { flag("CannotExtractImpale") },\n'
            '\t["critical hits with spells inflict impale"] =')
    replace("src/Modules/ModParser.lua", '\t["leech life (%d+)%% slower"] =',
            '\t["leech life (%d+)%% less quickly"] = function(num) return { mod("LifeLeechRate", "MORE", -num) } end,\n'
            '\t["leech mana (%d+)%% slower"] = function(num) return { mod("ManaLeechRate", "INC", -num) } end,\n'
            '\t["leech mana (%d+)%% faster"] = function(num) return { mod("ManaLeechRate", "INC", num) } end,\n'
            '\t["leech energy shield (%d+)%% slower"] = function(num) return { mod("EnergyShieldLeechRate", "INC", -num) } end,\n'
            '\t["leech energy shield (%d+)%% faster"] = function(num) return { mod("EnergyShieldLeechRate", "INC", num) } end,\n'
            '\t["leech life (%d+)%% slower"] =')
    replace("src/Modules/ModParser.lua", '\t["life leech effects recover energy shield instead while on full life"] =',
            '\t["excess life recovery from leech is applied to energy shield"] = { flag("ImmortalAmbition", { type = "Condition", var = "FullLife" }) },\n'
            '\t["life leech effects recover energy shield instead while on full life"] =')
    replace("src/Data/SkillStatMap.lua", '-- Impale\n', '''-- Impale
["impale_magnitude_+%"] = { mod("ImpaleEffect", "INC", nil) },
["active_skill_impale_magnitude_+%_final"] = { mod("ImpaleEffect", "MORE", nil) },
["cannot_consume_impale"] = { flag("CannotExtractImpale") },
["number_of_additional_impaled_debuffs_to_apply"] = { mod("ImpaleAdditionalInflicted", "BASE", nil) },
["life_leech_from_source_not_removed_at_full_life"] = { flag("CanLeechLifeOnFullLife") },
["base_life_leech_amount_+%"] = { mod("LifeLeechAmount", "INC", nil) },
["base_mana_leech_amount_+%"] = { mod("ManaLeechAmount", "INC", nil) },
["base_life_leech_rate_+%"] = { mod("LifeLeechRate", "INC", nil) },
["base_mana_leech_rate_+%"] = { mod("ManaLeechRate", "INC", nil) },
["base_energy_shield_leech_rate_+%"] = { mod("EnergyShieldLeechRate", "INC", nil) },
["mana_drain_base_mana_leech_amount"] = { skill("manaLeechPerUse", nil) },
''')
    # Never allow the generated cache to retain the old amount-as-cap parser.
    cache = destination / "src/Data/ModCache.lua"
    original = cache.read_text()
    prepared[cache] = "\n".join(line for line in original.split("\n")
        if not (line.startswith('c["') and any(word in line.lower() for word in
                ("impale", "amount of life leeched", "amount of mana leeched", "amount of energy shield leeched", "leech life", "leech mana", "leech energy shield", "excess life recovery from leech"))))

    section(offence, '\t-- Calculate leech\n\tlocal function getLeechInstances(',
            '\t-- dynamic way of calculating the Ancestral Boost', '''	-- PoE2 recovers each non-instant leech instance over one second.
	-- Only one instance can recover a resource; hit rate changes uptime,
	-- never the maximum number of simultaneously recovering instances.
	output.LeechUsesHitDamage = 0
	local function getLeechInstances(amount, total, hitRate, resource)
		local speed = m_max(0, calcLib.mod(skillModList, skillCfg, resource .. "LeechRate"))
		if amount <= 0 or total <= 0 or speed <= 0 then return 0, 0 end
		local duration = 1 / speed
		return duration, m_min(1, duration * m_max(0, hitRate))
	end
''')
    replace(offence, '\t\t\tlocal manaLeechTotal = 0\n',
            '\t\t\tlocal manaLeechTotal = 0\n\t\t\tlocal leechHitDamage = 0\n')
    replace(offence, '\t\t\t\t\t-- Beginning of Leech Calculation for this DamageType\n',
            '\t\t\t\t\tleechHitDamage = leechHitDamage + damageTypeHitAvg\n'
            '\t\t\t\t\t-- Beginning of Leech Calculation for this DamageType\n')
    replace(offence, '\t\t\tif skillData.lifeLeechPerUse then\n', '''			-- Apply the 40,000 cap to TOTAL hit damage while preserving type
			-- ratios, then monster resistance to the amount actually leeched.
			local cap = data.gameConstants["EffectiveMaxDamageForLeech"]
			if leechHitDamage > 0 and (lifeLeechTotal > 0 or manaLeechTotal > 0 or energyShieldLeechTotal > 0) then
				globalOutput.LeechUsesHitDamage = 1
			end
			local capScale = leechHitDamage > 0 and m_min(1, cap / leechHitDamage) or 0
			local resistance = data.monsterLeechResistanceTable[m_min(100, m_max(1, env.enemyLevel))] / 100
			if tonumber(env.configInput.companionLeechResistance) then
				resistance = m_min(100, m_max(0, tonumber(env.configInput.companionLeechResistance)))
			end
			local leechScale = capScale * m_max(0, 1 - resistance / 100)
			output.EnemyLeechResistance = resistance
			globalOutput.EnemyLeechResistance = resistance
			lifeLeechTotal = lifeLeechTotal * leechScale
			energyShieldLeechTotal = energyShieldLeechTotal * leechScale
			manaLeechTotal = manaLeechTotal * leechScale
			-- Flat leech per use did not damage a monster and has no hit cap
			-- or monster-resistance penalty.
			if skillData.lifeLeechPerUse and not noLifeLeech then
''')
    replace(offence, '\t\t\tif skillData.manaLeechPerUse then\n',
            '\t\t\tif skillData.manaLeechPerUse and not noManaLeech then\n')
    section(offence, '\t\t\t-- leech caps per instance\n', '\t\t\tlocal portion = (pass == 1)', '''			-- These modifiers change amount, never an obsolete PoE1 pool cap.
			lifeLeechTotal = lifeLeechTotal * calcLib.mod(skillModList, cfg, "LifeLeechAmount")
			energyShieldLeechTotal = energyShieldLeechTotal * calcLib.mod(skillModList, cfg, "EnergyShieldLeechAmount")
			manaLeechTotal = manaLeechTotal * calcLib.mod(skillModList, cfg, "ManaLeechAmount")

''')
    for resource in ("Life", "Mana", "EnergyShield"):
        replace(offence, f'getLeechInstances(output.{resource}Leech, globalOutput.{resource}, hitRate)',
                f'getLeechInstances(output.{resource}Leech, globalOutput.{resource}, hitRate, "{resource}")')
        replace(offence, f'\t\tcombineStat("{resource}LeechDuration", "DPS")',
                f'\t\tcombineStat("{resource}Leech", "AVERAGE")\n'
                f'\t\tcombineStat("{resource}LeechDuration", "AVERAGE")')
    replace(offence, '\t\tif skillModList:Flag(cfg, "ManaLeechRecoversEnergyShield") then\n\t\t\toutput.EnergyShieldLeechInstantProportion = output.EnergyShieldLeechInstantProportion + output.ManaLeechInstantProportion\n\t\tend\n',
            '\t\t-- Mana leech recovery is copied after its own instant/rate calculation.\n')
    section(offence, '\t-- Calculate leech rates\n', '\tif breakdown then\n\t\tlocal hitRate = output.HitChance / 100 * (globalOutput.HitSpeed or globalOutput.Speed) * output.DpsMultiplier\n', '''	-- PoE2 per-instance amounts and conditional periodic-hit recovery.
	-- The legacy pool-relative caps and 2%-of-pool instance rate do not apply.
	for _, resource in ipairs({ "Life", "Mana", "EnergyShield" }) do
		local amount = output[resource .. "Leech"] or 0
		local instant = output[resource .. "LeechInstant"] or 0
		local duration = output[resource .. "LeechDuration"] or 0
		local instances = m_min(1, output[resource .. "LeechInstances"] or 0)
		local recovery = output[resource .. "RecoveryRateMod"] or 1
		local instanceRate = duration > 0 and amount / duration or 0
		if resource == "Life" and skillModList:Flag(nil, "UnaffectedByNonInstantLifeLeech") then
			amount, instanceRate, instances = 0, 0, 0
		end
		output[resource .. "LeechInstanceRate"] = instanceRate
		output[resource .. "LeechInstances"] = instances
		output[resource .. "LeechRate"] = (output[resource .. "LeechInstantRate"] or 0) + instanceRate * instances * recovery
		output[resource .. "LeechPerHit"] = instant + amount * recovery
		output["Max" .. resource .. "LeechInstance"] = instant + amount
		output["Max" .. resource .. "LeechRate"] = instanceRate * recovery
	end
	if skillModList:Flag(nil, "ImmortalAmbition") then
		output.EnergyShieldLeechRate = output.EnergyShieldLeechRate + output.LifeLeechRate
		output.EnergyShieldLeechPerHit = output.EnergyShieldLeechPerHit + output.LifeLeechPerHit
		output.MaxEnergyShieldLeechRate = output.MaxEnergyShieldLeechRate + output.MaxLifeLeechRate
		output.MaxLifeLeechRate = 0
		output.LifeLeechRate, output.LifeLeechPerHit = 0, 0
	end
	if skillModList:Flag(skillCfg, "ManaLeechRecoversEnergyShield") then
		output.EnergyShieldLeechRate = output.EnergyShieldLeechRate + output.ManaLeechRate
		output.EnergyShieldLeechPerHit = output.EnergyShieldLeechPerHit + output.ManaLeechPerHit
		output.MaxEnergyShieldLeechRate = output.MaxEnergyShieldLeechRate + output.MaxManaLeechRate
	end
	skillFlags.leechLife = output.LifeLeechRate > 0
	skillFlags.leechES = output.EnergyShieldLeechRate > 0
	skillFlags.leechMana = output.ManaLeechRate > 0
	for _, resource in ipairs({ "Life", "Mana", "EnergyShield" }) do
		output[resource .. "LeechGainPerHit"] = output[resource .. "LeechPerHit"] + (output[resource .. "OnHit"] or 0)
		output[resource .. "LeechGainRate"] = output[resource .. "LeechRate"] + (output[resource .. "OnHitRate"] or 0)
	end
''')
    # Old breakdown text would falsely present PoE1 pool caps and duration.
    section(offence, '\tif breakdown then\n\t\tlocal hitRate = output.HitChance / 100 * (globalOutput.HitSpeed or globalOutput.Speed) * output.DpsMultiplier\n',
            '\tlocal ailmentData = data.nonDamagingAilment\n', '''	if breakdown then
		for _, resource in ipairs({ "Life", "Mana", "EnergyShield" }) do
			breakdown[resource .. "Leech"] = {
				s_format("%.2f ^8(recovery per hit, after total hit cap and monster leech resistance)", output[resource .. "LeechPerHit"]),
				s_format("%.3fs ^8(non-instant instance duration)", output[resource .. "LeechDuration"] or 0),
				"Only one instance per resource recovers at a time; rate assumes repeated average hits and a depleted resource.",
			}
		end
	end

''')
    # Extracted damage is already scaled by the SOURCE hit. Add it after
    # attacker conversion/scaling/crit, before target mitigation exactly once.
    replace(offence, '\t\t\t\t\t-- Store pre-resist/armour/penetration hit damage for ailment calculations\n', '''					-- Explicit existing-target Impale: strongest one only, on the
					-- selected player attack. Never multiply by 60 stored debuffs,
					-- repeat attacker scaling, or apply it to spell/minion hits.
					local selected = env.build.skillsTab.socketGroupList[env.build.mainSocketGroup]
					local extraction = 0
					if damageType == "Physical" and skillFlags.attack and actor == env.player
						and not (skillFlags.bothWeaponAttack and skillData.combinesHitsWhenDualWielding)
						and (not selected or activeSkill.socketGroup == selected)
						and (not env.companionImpaleSelectedEffectId or activeSkill.activeEffect.grantedEffect.id == env.companionImpaleSelectedEffectId)
						and not skillModList:Flag(cfg, "CannotExtractImpale") then
						extraction = m_min(1e9, m_max(0, tonumber(env.configInput.companionImpaleMagnitude) or 0))
						damageTypeHitMin = damageTypeHitMin + extraction
						damageTypeHitMax = damageTypeHitMax + extraction
						damageTypeHitAvg = damageTypeHitAvg + extraction
					end
					if damageType == "Physical" then
						output[pass == 1 and "ImpaleExtractedOnCrit" or "ImpaleExtractedOnHit"] = extraction
					end
					-- Store pre-resist/armour/penetration hit damage for ailment calculations
''')
    replace(offence, '\t\toutput.ImpaleChance = 0\n\t\toutput.ImpaleChanceOnCrit = 0\n', '''		local previousCriticalStrike = cfg.skillCond.CriticalStrike
		cfg.skillCond.CriticalStrike = true
		output.ImpaleChanceOnCrit = skillFlags.hit and canDeal.Physical and m_min(100, m_max(0, skillModList:Sum("BASE", cfg, "ImpaleChance"))) or 0
		cfg.skillCond.CriticalStrike = false
		output.ImpaleChance = skillFlags.hit and canDeal.Physical and m_min(100, m_max(0, skillModList:Sum("BASE", cfg, "ImpaleChance"))) or 0
		cfg.skillCond.CriticalStrike = previousCriticalStrike
''')
    section(offence, '\t\t-- Calculate impale chance and modifiers\n', '\t-- Combine secondary effect stats\n', '''		-- Generation is separate from extraction. A stored magnitude is not
		-- reflected DPS and no automatic self-sustaining feedback is assumed.
		output.ImpaleModifier = 1
		local priorCriticalStrike = cfg.skillCond.CriticalStrike
		cfg.skillCond.CriticalStrike = false
		output.ImpaleStoredDamage = 100 * data.misc.ImpaleStoredDamageBase * m_max(0, calcLib.mod(skillModList, cfg, "ImpaleEffect"))
		output.ImpaleStoredHitMagnitude = output.ImpaleChance > 0 and (output.PhysicalStoredHitAvg or 0) * output.ImpaleStoredDamage / 100 or 0
		cfg.skillCond.CriticalStrike = true
		local criticalMagnitude = data.misc.ImpaleStoredDamageBase * m_max(0, calcLib.mod(skillModList, cfg, "ImpaleEffect"))
		output.ImpaleStoredCritMagnitude = output.ImpaleChanceOnCrit > 0 and (output.PhysicalStoredCritAvg or 0) * criticalMagnitude or 0
		cfg.skillCond.CriticalStrike = priorCriticalStrike
		output.ImpaleInflicted = 1 + m_max(0, skillModList:Sum("BASE", cfg, "ImpaleAdditionalInflicted"))
		globalOutput.ImpaleStacksMax = data.gameConstants["ImpaleMaximumStacks"]
		globalOutput.ImpaleStacks = 0
		if output.ImpaleStoredHitMagnitude > 0 or output.ImpaleStoredCritMagnitude > 0 then skillFlags.impale = true end
	end

''')
    replace(offence, '\t\tcombineStat("ImpaleStoredDamage", "AVERAGE")\n', '''		combineStat("ImpaleStoredDamage", "AVERAGE")
		combineStat("ImpaleChanceOnCrit", "AVERAGE")
		combineStat("ImpaleStoredHitMagnitude", "AVERAGE")
		combineStat("ImpaleStoredCritMagnitude", "AVERAGE")
		combineStat("ImpaleExtractedOnHit", "AVERAGE")
		combineStat("ImpaleExtractedOnCrit", "AVERAGE")
		combineStat("ImpaleInflicted", "AVERAGE")
''')
    # Prevent unrelated skill FullDPS caches from reusing a result calculated
    # with a different explicit target debuff.
    replace("src/Modules/Calcs.lua", '\tlocal surface = { mods = { }, meta = { } }\n',
            '\tlocal surface = { mods = { }, meta = { } }\n'
            '\tsurface.meta[#surface.meta + 1] = "impaleMagnitude/" .. tostring(env.configInput.companionImpaleMagnitude or 0)\n'
            '\tsurface.meta[#surface.meta + 1] = "impaleSelectedGroup/" .. tostring(env.build.mainSocketGroup or 0)\n'
            '\tsurface.meta[#surface.meta + 1] = "leechResistance/" .. tostring(env.configInput.companionLeechResistance or "default")\n')
    for target, source in prepared.items():
        target.write_text(source)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    patch_damage_rules(parser.parse_args().destination)
