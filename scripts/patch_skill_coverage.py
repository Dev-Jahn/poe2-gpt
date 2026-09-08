"""Backport reviewed Verglas calculations from upstream PR #2390.

Only exact source anchors are accepted. The new condition is default-off;
having an Ice Crystal skill does not prove that a crystal was destroyed.
Source: https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2390
Mechanic: https://poe2db.tw/us/Verglas
"""
from pathlib import Path


def patch_skill_coverage(destination: Path) -> None:
    replacements = [
        (
            'src/Data/Skills/sup_int.lua',
            '\t\t\tlabel = "Verglas",\n\t\t\tincrementalEffectiveness = 0.054999999701977,\n\t\t\tstatDescriptionScope = "gem_stat_descriptions",\n',
            '\t\t\tlabel = "Verglas",\n\t\t\tincrementalEffectiveness = 0.054999999701977,\n\t\t\tstatDescriptionScope = "gem_stat_descriptions",\n' + '''\t\t\tstatMap = {
\t\t\t\t["support_crystalshatter_buff_damage_%_gained_as_extra_cold_per_2000_crystal_life"] = {
\t\t\t\t\tmod("DamageGainAsCold", "BASE", nil, 0, 0, { type = "Condition", var = "DestroyedIceCrystalPast6Seconds" }, { type = "Multiplier", var = "DestroyedIceCrystalLife", div = 2000 }),
\t\t\t\t},
\t\t\t\t["support_crystalshatter_buff_duration"] = { }, -- Display-only duration of the explicit recent-destruction condition.
\t\t\t},
''',
        ),
        (
            'src/Modules/CalcSetup.lua',
            '\tenv.virtuousMoteSkillCount = virtuousMoteSkillCount\n',
            '''\t-- Verglas is local to supported skills. Distinct crystal-Life values
\t-- require an explicit source; never assume the most favorable crystal.
\tlocal automaticDestroyedIceCrystalLife = 0
\tlocal destroyedIceCrystalLifeAmbiguous = false
\tfor _, activeSkill in pairs(env.player.activeSkillList) do
\t\tlocal socketGroup = activeSkill.socketGroup
\t\tif not activeSkill.disableReason and (not socketGroup or (socketGroup.enabled and socketGroup.slotEnabled)) and activeSkill.skillModList then
\t\t\tlocal baseLife = activeSkill.skillModList:Sum("BASE", activeSkill.skillCfg, "IceCrystalLifeBase")
\t\t\tif baseLife > 0 then
\t\t\t\tlocal life = baseLife * calcLib.mod(activeSkill.skillModList, activeSkill.skillCfg, "IceCrystalLife")
\t\t\t\tif automaticDestroyedIceCrystalLife > 0 and automaticDestroyedIceCrystalLife ~= life then destroyedIceCrystalLifeAmbiguous = true end
\t\t\t\tautomaticDestroyedIceCrystalLife = life
\t\t\tend
\t\tend
\tend
\tif destroyedIceCrystalLifeAmbiguous then automaticDestroyedIceCrystalLife = 0 end
\tlocal configuredDestroyedIceCrystalLife = tonumber(env.configInput.multiplierDestroyedIceCrystalLife) or 0
\tlocal resolvedDestroyedIceCrystalLife = configuredDestroyedIceCrystalLife > 0 and configuredDestroyedIceCrystalLife or automaticDestroyedIceCrystalLife
\tenv.player.automaticDestroyedIceCrystalLife = automaticDestroyedIceCrystalLife
\tenv.player.destroyedIceCrystalLife = resolvedDestroyedIceCrystalLife
\tenv.player.destroyedIceCrystalLifeAmbiguous = destroyedIceCrystalLifeAmbiguous
\tif configuredDestroyedIceCrystalLife <= 0 and automaticDestroyedIceCrystalLife > 0 then
\t\tenv.modDB.multipliers.DestroyedIceCrystalLife = automaticDestroyedIceCrystalLife
\telse
\t\tenv.modDB.multipliers.DestroyedIceCrystalLife = nil
\tend
\tif mode == "MAIN" then
\t\tlocal control = build.configTab.varControls.multiplierDestroyedIceCrystalLife
\t\tif control then control:SetPlaceholder(automaticDestroyedIceCrystalLife > 0 and math.floor(automaticDestroyedIceCrystalLife + 0.5) or "", false) end
\tend

\tenv.virtuousMoteSkillCount = virtuousMoteSkillCount
''',
        ),
        (
            'src/Modules/Calcs.lua',
            'local function captureCouplingSurface(env)\n\tlocal surface = { mods = { }, meta = { } }\n',
            'local function captureCouplingSurface(env)\n\tlocal surface = { mods = { }, meta = { } }\n'
            '\t-- A different crystal source can change Verglas without changing its own gems.\n'
            '\tsurface.meta[#surface.meta + 1] = "destroyedIceCrystalLife/" .. tostring(env.player.destroyedIceCrystalLife or 0)\n',
        ),
        (
            'src/Modules/ConfigOptions.lua',
            '\t{ var = "conditionKilledPoisonedLast2Seconds",',
            '''\t{ var = "conditionDestroyedIceCrystalPast6Seconds", type = "check", label = "Ice Crystal destroyed (past 6s)?", ifCond = "DestroyedIceCrystalPast6Seconds", apply = function(val, modList, enemyModList)
\t\tmodList:NewMod("Condition:DestroyedIceCrystalPast6Seconds", "FLAG", true, "Config", { type = "Condition", var = "Combat" })
\tend },
\t{ var = "multiplierDestroyedIceCrystalLife", type = "count", label = "Ice Crystal Life override:", ifOption = "conditionDestroyedIceCrystalPast6Seconds", ifMult = "DestroyedIceCrystalLife", tooltip = "Automatic only when enabled Ice Crystal skills agree on maximum Life. Enter a positive value when crystal sources differ.", apply = function(val, modList, enemyModList)
\t\tmodList:NewMod("Multiplier:DestroyedIceCrystalLife", "BASE", val, "Config", { type = "Condition", var = "Combat" })
\tend },
\t{ var = "conditionKilledPoisonedLast2Seconds",''',
        ),
    ]
    prepared = {}
    for relative, old, new in replacements:
        target = destination / relative
        source = prepared.get(target, target.read_text())
        if source.count(old) != 1 or new in source:
            raise SystemExit('upstream_skill_coverage_patch_mismatch')
        prepared[target] = source.replace(old, new)
    for target, source in prepared.items():
        target.write_text(source)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    patch_skill_coverage(parser.parse_args().destination)
