"""Implement verified 0.5 defensive and Martial Artist skill mechanics.

Sources: https://poe2db.tw/us/Ghost_Dance, /Hollow_Focus, /Hollow_Form,
/Tempest_Bell, /Wind_Dancer, /Refutation, /Heightened_Charges, /Recently.
Upstream PR #2099 was reviewed; its support speed/damage correction is
already present in the pinned source. These additions calculate missing
recovery, generation rates, event costs and limits without assuming uptime.
"""
from pathlib import Path


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if new in text:
        return
    # Several independently named config entries share one stable insertion
    # anchor. A later entry can separate an earlier entry from that anchor.
    # Recognize the complete inserted block, never just a short marker.
    if old == '\t{ var = "useGhostShrouds", legacy = true,' and old in new:
        before, after = new.split(old, 1)
        inserted = before if before and not after else after if after and not before else ""
        if len(inserted) > 80 and text.count(inserted) == 1:
            return
    if text.count(old) != 1:
        raise SystemExit("martial_mechanics_patch_anchor_mismatch")
    path.write_text(text.replace(old, new, 1))


def patch_martial_mechanics(destination: Path) -> None:
    target = destination / "src/Data/Skills/act_int.lua"
    anchor = '\t\t\tstatDescriptionScope = "ghost_dance",\n'
    extra = '''\t\t\tstatMap = {
\t\t\t\t["base_cooldown_modifiable_repeat_interval_ms"] = { skill("ghostShroudInterval", nil), div = 1000 },
\t\t\t\t["cooldown_recovery_modifiers_also_apply_to_repeat_interval"] = { flag("GhostShroudCooldownRate") },
\t\t\t\t["ghost_dance_max_stacks"] = { skill("ghostShroudMaximum", nil) },
\t\t\t\t["skill_base_ghost_dance_grants_%_evasion_as_es_regeneration_per_minute_if_have_lost_ghost_dance_shroud_recently"] = {
\t\t\t\t\tmod("GhostDanceEvasionAsRegenPercent", "BASE", nil, 0, 0, { type = "GlobalEffect", effectType = "Buff" }, { type = "Condition", var = "LostGhostShroudRecently" }),
\t\t\t\t\tdiv = 60,
\t\t\t\t},
\t\t\t},
'''
    _replace(target, anchor, anchor + extra)
    # Tempest Bell's creation condition and lifetime are independent of the
    # impact/shockwave damage stat set selected for display.
    for index in range(3):
        anchor = f'\t\t\tstatDescriptionScope = "tempest_bell_statset_{index}",\n'
        _replace(target, anchor, anchor + '''\t\t\tstatMap = {
\t\t\t\t["active_skill_required_number_of_combo_stacks"] = { skill("tempestBellComboRequired", nil) },
\t\t\t\t["base_combo_stacks_decay_delay_ms"] = { skill("tempestBellComboDecay", nil), div = 1000 },
\t\t\t\t["base_number_of_tempest_bells_allowed"] = { skill("tempestBellLimit", nil) },
\t\t\t\t["bell_hit_limit"] = { skill("tempestBellHitLimit", nil) },
\t\t\t\t["bell_shockwave_cooldown_ms"] = { skill("tempestBellShockwaveInterval", nil), div = 1000 },
\t\t\t\t["tempest_bell_damage_+%_final_per_time_hit"] = { mod("Damage", "MORE", nil, 0, 0, { type = "Multiplier", var = "TempestBellPriorHits" }) },
\t\t\t\t["tempest_bell_physical_damage_%_as_elemental_per_ailment"] = {
\t\t\t\t\tmod("PhysicalDamageGainAsFire", "BASE", nil, 0, 0, { type = "Condition", var = "TempestBellFireAilment" }),
\t\t\t\t\tmod("PhysicalDamageGainAsCold", "BASE", nil, 0, 0, { type = "Condition", var = "TempestBellColdAilment" }),
\t\t\t\t\tmod("PhysicalDamageGainAsLightning", "BASE", nil, 0, 0, { type = "Condition", var = "TempestBellLightningAilment" }),
\t\t\t\t},
\t\t\t\t["tempest_bell_area_of_effect_+%_final_per_1_unit_of_knockback"] = { mod("AreaOfEffect", "MORE", nil, 0, 0, { type = "Multiplier", var = "TempestBellKnockbackUnits" }) },
\t\t\t},
''')
    target = destination / "src/Data/Skills/act_dex.lua"
    anchor = '\t\t\t\t["wind_dancer_evasion_rating_+%_final_per_stage"] = {\n'
    _replace(target, anchor, '\t\t\t\t["wind_dancer_stages_gained_every_x_ms"] = { skill("windDancerStageInterval", nil), div = 1000 },\n' + anchor)
    target = destination / "src/Data/Skills/other.lua"
    anchor = '\t\t\tlabel = "Bells",\n\t\t\tincrementalEffectiveness = 0.054999999701977,\n\t\t\tstatDescriptionScope = "hollow_focus",\n'
    extra = '''\t\t\tstatMap = {
\t\t\t\t["base_cooldown_modifiable_repeat_interval_ms"] = { skill("hollowBellInterval", nil), div = 1000 },
\t\t\t\t["cooldown_recovery_modifiers_also_apply_to_repeat_interval"] = { flag("HollowBellCooldownRate") },
\t\t\t\t["spectral_bells_maximum_active_bells"] = { mod("ActiveSkillLimit", "BASE", nil) },
\t\t\t\t["bell_hit_limit"] = { skill("hollowBellHits", nil) },
\t\t\t},
'''
    _replace(target, anchor, anchor + extra)
    anchor = '\t\t\tlabel = "Shockwave",\n\t\t\tincrementalEffectiveness = 0.054999999701977,\n\t\t\tstatDescriptionScope = "hollow_focus",\n'
    _replace(target, anchor, anchor + '''\t\t\tstatMap = {
\t\t\t\t["bell_hit_limit"] = { skill("hollowBellHits", nil) },
\t\t\t},
''')
    anchor = '\t\t\tlabel = "Hollow Form",\n\t\t\tincrementalEffectiveness = 0.054999999701977,\n\t\t\tstatDescriptionScope = "hollow_form",\n'
    _replace(target, anchor, anchor + '''\t\t\tstatMap = {
\t\t\t\t["mantra_of_illusions_bonus_illusions_when_consuming_power_charge"] = { skill("hollowFormAdditionalImages", nil) },
\t\t\t\t["mantra_of_illusions_cloned_skill_mana_cost_%"] = { skill("hollowFormCostMultiplier", nil), div = 100 },
\t\t\t\t["base_power_charge_skip_consume_chance_%"] = { mod("PowerChargeNotRemovedChance", "BASE", nil) },
\t\t\t},
''')
    anchor = '\t\t\tstatDescriptionScope = "refutation",\n'
    _replace(target, anchor, anchor + '''\t\t\tstatMap = {
\t\t\t\t-- This skill-specific display stat states automatic all-direction
\t\t\t\t-- blocking; it is functional, not a globally ignorable display ID.
\t\t\t\t["display_statset_no_hit_damage"] = { flag("RefutationAutomaticBlock", { type = "GlobalEffect", effectType = "Buff" }, { type = "Condition", var = "RefutationActive" }) },
\t\t\t\t["runic_fortress_stun_threshold_+%_final"] = {
\t\t\t\t\tmod("RefutationStunThreshold", "MORE", nil, 0, 0, { type = "GlobalEffect", effectType = "Buff" }, { type = "Condition", var = "RefutationActive" }),
\t\t\t\t},
\t\t\t\t["runic_fortress_stun_threshold_+%_final_per_10_ward_spent"] = {
\t\t\t\t\tmod("RefutationWardStunThreshold", "MORE", nil, 0, 0, { type = "Multiplier", var = "RefutationWardSpent", div = 10 }, { type = "GlobalEffect", effectType = "Buff" }, { type = "Condition", var = "RefutationActive" }),
\t\t\t\t},
\t\t\t},
''')
    target = destination / "src/Modules/CalcPerform.lua"
    anchor = '\t\tactiveSkill.skillModList = new("ModList"):ModList(activeSkill.baseSkillModList)\n'
    _replace(target, anchor, anchor + '''\t\tif activeSkill.activeEffect.grantedEffect.id == "TempestBellPlayer" then
\t\t\tlocal effect = activeSkill.activeEffect
\t\t\tlocal base = calcLib.buildSkillInstanceStats(effect, effect.grantedEffect, effect.grantedEffect.statSets[1], env.useAltGemQualityStats)
\t\t\tlocal maximum = base.bell_hit_limit or 0
\t\t\tfor _, support in ipairs(activeSkill.effectList or {}) do
\t\t\t\tif support.grantedEffect.support then
\t\t\t\t\tfor _, set in ipairs(support.grantedEffect.statSets or {}) do
\t\t\t\t\t\tlocal values = calcLib.buildSkillInstanceStats(support, support.grantedEffect, set, env.useAltGemQualityStats)
\t\t\t\t\t\tmaximum = maximum + (values.support_number_of_additional_uses_before_expiry or 0)
\t\t\t\t\tend
\t\t\t\tend
\t\t\tend
\t\t\tlocal hits = tonumber(env.configInput.tempestBellPriorHits) or 0
\t\t\tactiveSkill.companionTempestBellInvalidHitCount = hits < 0 or hits >= maximum or hits ~= math.floor(hits)
\t\t\tactiveSkill.skillModList.multipliers.TempestBellPriorHits = not activeSkill.companionTempestBellInvalidHitCount and hits or 0
\t\tend
''')
    target = destination / "src/Modules/CalcDefence.lua"
    anchor = '\t\t\tbaseRegen = modDB:Sum("BASE", nil, resource.."Regen") + pool * modDB:Sum("BASE", nil, resource.."RegenPercent") / 100\n'
    _replace(target, anchor, anchor + '\t\t\t-- Keep fractional regeneration; PercentStat rounds values up to whole points.\n\t\t\tif resource == "EnergyShield" then baseRegen = baseRegen + (output.Evasion or 0) * modDB:Sum("BASE", nil, "GhostDanceEvasionAsRegenPercent") / 100 end\n')
    anchor = '\tif modDB:Flag(nil, "CannotBlockAttacks") or enemyDB:Flag(nil, "CannotBeBlocked") then\n'
    _replace(target, anchor, '''\t-- Refutation automatically blocks blockable hits. Keep the following
\t-- CannotBlock / Unblockable checks authoritative; this is not immunity.
\tif modDB:Flag(nil, "RefutationAutomaticBlock") then
\t\toutput.BlockChance = 100
\t\toutput.ProjectileBlockChance = 100
\t\toutput.SpellBlockChance = 100
\t\toutput.SpellProjectileBlockChance = 100
\tend
''' + anchor)
    anchor = '\t\tlocal StunThresholdMore = modDB:More("INC", nil, "StunThreshold")'
    _replace(target, anchor, anchor + ' * modDB:More(nil, "RefutationStunThreshold", "RefutationWardStunThreshold")')
    target = destination / "src/Modules/ConfigOptions.lua"
    for element in ("Fire", "Cold", "Lightning"):
        anchor = '\t{ var = "useGhostShrouds", legacy = true,'
        config = f'''\t{{ var = "conditionTempestBell{element}Ailment", type = "check", label = "{element} ailment on Tempest Bell?", ifSkill = "Tempest Bell", apply = function(val, modList, enemyModList)
\t\tmodList:NewMod("Condition:TempestBell{element}Ailment", "FLAG", true, "Config", {{ type = "Condition", var = "Combat" }})
\tend }},
'''
        _replace(target, anchor, config + anchor)
    anchor = '\t{ var = "useGhostShrouds", legacy = true,'
    _replace(target, anchor, '''\t{ var = "tempestBellPriorHits", type = "countAllowZero", label = "Previous hits taken by Tempest Bell:", ifSkill = "Tempest Bell", apply = function(val, modList, enemyModList)
\t\t-- Validated against the actual Bell hit limit during calculation.
\tend },
\t{ var = "tempestBellKnockbackMetres", type = "countAllowZero", label = "Triggering hit knockback distance (metres):", ifSkill = "Tempest Bell", apply = function(val, modList, enemyModList)
\t\tmodList:NewMod("Multiplier:TempestBellKnockbackUnits", "BASE", math.floor(math.max(0, val) * 10 + 0.00000001), "Config")
\tend },
''' + anchor)
    anchor = '\t{ var = "useGhostShrouds", legacy = true,'
    _replace(target, anchor, '''\t{ var = "conditionRefutationActive", type = "check", label = "Refutation buff active?", ifSkill = "Refutation", apply = function(val, modList, enemyModList)
\t\tmodList:NewMod("Condition:RefutationActive", "FLAG", true, "Config", { type = "Condition", var = "Combat" })
\tend },
\t{ var = "refutationWardSpent", type = "countAllowZero", label = "Runic Ward spent on Refutation:", ifSkill = "Refutation", apply = function(val, modList, enemyModList)
\t\tmodList:NewMod("Multiplier:RefutationWardSpent", "BASE", val, "Config")
\tend },
''' + anchor)
    anchor = '\t{ var = "useGhostShrouds", legacy = true,'
    extra = '''\t{ var = "conditionLostGhostShroudRecently", type = "check", label = "Lost a Ghost Shroud in past 4 seconds?", ifCond = "LostGhostShroudRecently", apply = function(val, modList, enemyModList)
\t\tmodList:NewMod("Condition:LostGhostShroudRecently", "FLAG", true, "Config", { type = "Condition", var = "Combat" })
\tend },
'''
    _replace(target, anchor, extra + anchor)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    patch_martial_mechanics(parser.parse_args().destination)
