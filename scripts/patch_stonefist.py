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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    patch_stonefist(parser.parse_args().destination)
