"""Per-hit cap expectation. Rules: PoE2DB Life_Leech / Only_Minimum_or_Maximum_Damage.

Analytic single-type uniform/lucky, exact enumeration for independently rolled
min/max types, bounded quadrature otherwise. Upstream mitigation and averaged
double/triple/exerted effects retain an explicit approximation diagnostic.
"""
from pathlib import Path


def patch_leech_distribution(destination: Path):
    target = destination / 'src/Modules/CalcOffence.lua'
    source = target.read_text()
    def replace(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise RuntimeError('leech_distribution_anchor_mismatch')
        source = source.replace(old, new)
    replace('local leechHitDamage = 0', 'local leechHitDamage = 0\n\t\t\tlocal leechTypes = {}')
    replace('damageTypeHitAvg = damageTypeHitAvgNotLucky * (1 - damageTypeLuckyChance) + damageTypeHitAvgLucky * damageTypeLuckyChance', '''local leechEndpoints = source.OnlyMinMaxDamage or source[damageType.."OnlyMinMaxDamage"] or skillModList:Flag(cfg, damageType.."OnlyMinMaxDamage")
					if leechEndpoints then damageTypeHitAvgLucky = damageTypeHitMin / 4 + 3 * damageTypeHitMax / 4 end
					damageTypeHitAvg = damageTypeHitAvgNotLucky * (1 - damageTypeLuckyChance) + damageTypeHitAvgLucky * damageTypeLuckyChance''')
    anchor = '\t\t\t\t\tif lifeLeech > 0 and not noLifeLeech then'
    replace(anchor, '''\t\t\t\t\tleechTypes[#leechTypes+1] = {minimum=damageTypeHitMin,maximum=damageTypeHitMax,lucky=damageTypeLuckyChance,
						endpoints=not not leechEndpoints,life=not noLifeLeech and lifeLeech/100 or 0,
						mana=not noManaLeech and manaLeech/100 or 0,es=not noEnergyShieldLeech and energyShieldLeech/100 or 0}
''' + anchor)
    replace('local leechScale = capScale * m_max(0, 1 - resistance / 100)', '''local distributionExact
			lifeLeechTotal,manaLeechTotal,energyShieldLeechTotal,distributionExact = require('Modules.CompanionLeechDistribution').integrate(leechTypes,cap)
			if not distributionExact or (output.DoubleDamageEffect or 0)~=0 or (output.TripleDamageEffect or 0)~=0
				or (output.FistOfWarDamageEffect or 1)~=1 or (globalOutput.OffensiveWarcryEffect or 1)~=1
				or (env.mode_effective and (enemyDB:Sum("BASE",nil,"Armour") or 0)>0) then
				globalOutput.LeechDistributionApproximation=1
			end
			local leechScale = m_max(0, 1 - resistance / 100)''')
    target.write_text(source)
    parser = destination / 'src/Modules/ModParser.lua'
    source = parser.read_text()
    anchor = '\t["no physical damage"] ='
    additions = '''\t["rolls only the minimum or maximum damage value for each damage type"] = { mod("WeaponData", "LIST", { key = "OnlyMinMaxDamage", value = true }) },
	["rolls only the minimum or maximum damage value for physical damage"] = { mod("WeaponData", "LIST", { key = "PhysicalOnlyMinMaxDamage", value = true }) },
'''
    if source.count(anchor) != 1:
        raise RuntimeError('leech_distribution_parser_anchor_mismatch')
    parser.write_text(source.replace(anchor, additions + anchor))
    stats = destination / 'src/Data/SkillStatMap.lua'
    source = stats.read_text()
    if source.count('-- Impale\n') != 1:
        raise RuntimeError('leech_distribution_stat_anchor_mismatch')
    stats.write_text(source.replace('-- Impale\n', '-- Impale\n["lightning_damage_roll_always_min_or_max"] = { flag("LightningOnlyMinMaxDamage") },\n'))
    cache = destination / 'src/Data/ModCache.lua'
    cache.write_text('\n'.join(line for line in cache.read_text().splitlines() if 'Rolls only the minimum or maximum Damage value' not in line)+'\n')
    module=Path(__file__).with_name('leech_distribution.lua')
    if not module.exists():
        module=Path(__file__).parents[1] / 'src/poe2_companion/lua/leech_distribution.lua'
    (destination / 'src/Modules/CompanionLeechDistribution.lua').write_bytes(module.read_bytes())


if __name__ == '__main__':
    import sys
    patch_leech_distribution(Path(sys.argv[1]))
