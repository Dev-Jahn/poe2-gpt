"""Differential PoE2 hit mechanics checks using only generated fixtures."""
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

FIXTURE = Path(__file__).parent / "fixtures/engine_synthetic.xml"
MODULE = Path(__file__).parents[1] / "src/poe2_companion/lua/damage_rules.lua"


def synthetic(skill="MeleeAtAnimationSpeed", support=None, *, extra_skill=None, level=1, quality=0):
    root = ET.fromstring(FIXTURE.read_bytes())
    group = root.find("./Skills/SkillSet/Skill")
    if group is None:
        group = ET.SubElement(root.find("./Skills/SkillSet"), "Skill", {"enabled": "true", "mainActiveSkill": "1"})
    for gem in list(group):
        group.remove(gem)
    ET.SubElement(group, "Gem", {"skillId": skill, "nameSpec": skill,
                  "level": str(level), "quality": str(quality), "enabled": "true"})
    if support:
        ET.SubElement(group, "Gem", {"skillId": support, "nameSpec": support,
                      "level": "1", "quality": "0", "enabled": "true"})
    if extra_skill:
        group.set("includeInFullDPS", "true")
        other = ET.SubElement(root.find("./Skills/SkillSet"), "Skill", {"enabled": "true", "mainActiveSkill": "1", "includeInFullDPS": "true"})
        ET.SubElement(other, "Gem", {"skillId": extra_skill, "nameSpec": extra_skill,
                      "level": "1", "quality": "0", "enabled": "true"})
    return ET.tostring(root).decode()


@pytest.fixture
def run_damage(tmp_path):
    source = os.environ.get("POE2_TEST_ENGINE_DIR")
    if not source:
        pytest.skip("Set POE2_TEST_ENGINE_DIR to run real PoE2 LuaJIT integration")
    script = tmp_path / "synthetic.lua"
    script.write_text('''
print=function() end
local json=require('dkjson')
local input=assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
local module=dofile(input.module)
local result={}
for _,case in ipairs(input.cases) do
 loadBuildFromXML(case.xml,'')
 build.configTab.input.customMods=case.mods or ''
 if case.main_group then build.mainSocketGroup=case.main_group end
 build.configTab.input.enemyLevel=case.enemy_level or 83
 if case.full_life then build.configTab.input.conditionFullLife=true end
 if case.resistance~=nil then build.configTab.input.companionLeechResistance=case.resistance end
 if case.impale~=nil then build.configTab.input.companionImpaleMagnitude=case.impale end
 build.configTab:BuildModList()
 build.buildFlag=true;runCallback('OnFrame')
 assert(not __mainObject__.promptMsg)
 local env,out=build.calcsTab.mainEnv,build.calcsTab.mainOutput
 local selected=env.minion and env.minion.output or out
 local mechanics,issues=module.inspect(build,env,out)
 local row={mechanics=mechanics,issues=issues,stats={},minion={},full_skills={}}
 for _,skill in ipairs(out.SkillDPS or {}) do row.full_skills[#row.full_skills+1]={name=skill.name,dps=skill.dps} end
 for _,key in ipairs(input.fields) do
  row.stats[key]=out[key] or 0
  row.stats['MH_'..key]=out.MainHand and out.MainHand[key] or 0
  row.minion[key]=env.minion and env.minion.output[key] or 0
 end
 result[#result+1]=row
end
io.write(json.encode(result))
''')
    def run(cases):
        cases = [{"xml": synthetic(), **case} for case in cases]
        env = {**os.environ, "LUA_PATH": str(Path(source) / "runtime/lua/?.lua") + ";" + str(Path(source) / "runtime/lua/?/init.lua") + ";;"}
        fields = ["Life", "Mana", "EnergyShield", "CombinedDPS", "TotalDPS", "TotalDotDPS", "Speed", "HitChance", "CritChance",
                  "PhysicalStoredHitAvg", "PhysicalStoredCritAvg", "PhysicalHitAverage", "PhysicalCritAverage",
                  "FireHitAverage", "ColdHitAverage", "LightningHitAverage", "ChaosHitAverage",
                  "FireCritAverage", "ColdCritAverage", "LightningCritAverage", "ChaosCritAverage",
                  "EnemyLeechResistance", "LifeLeech", "LifeLeechPerHit", "LifeLeechRate", "LifeLeechDuration",
                  "LifeLeechInstances", "LifeLeechInstanceRate", "LifeLeechInstant", "LifeLeechInstantRate",
                  "ManaLeechPerHit", "ManaLeechDuration", "EnergyShieldLeechPerHit", "EnergyShieldLeechRate", "ManaLeechRate",
                  "MaxLifeLeechRate", "MaxManaLeechRate", "MaxEnergyShieldLeechRate",
                  "ImpaleChance", "ImpaleChanceOnCrit", "ImpaleStoredDamage", "ImpaleStoredHitMagnitude", "ImpaleStoredCritMagnitude",
                  "ImpaleExtractedOnHit", "ImpaleExtractedOnCrit", "ImpaleInflicted", "ImpaleDPS", "FullDPS"]
        result = subprocess.run([os.environ.get("POE2_TEST_LUAJIT", "luajit"), str(script)],
                                cwd=Path(source) / "src", input=json.dumps({"cases": cases, "module": str(MODULE), "fields": fields}),
                                text=True, capture_output=True, env=env, timeout=100)
        assert result.returncode == 0, result.stderr[-2500:]
        return json.loads(result.stdout)
    return run


BASE = "Your Hits can't be Evaded\nNever deal Critical Hits\nAdds 10000 to 10000 Physical Damage to Attacks\nLeech 10% of Physical Attack Damage as Life"


def test_leech_total_hit_cap_and_resistance(run_damage):
    rows = run_damage([
        {"mods": BASE, "resistance": 0},
        {"mods": BASE.replace("10000", "100000"), "resistance": 0},
        {"mods": BASE.replace("10000", "100000"), "resistance": 75},
        {"mods": BASE.replace("10000", "100000"), "resistance": 100},
    ])
    low, capped, reduced, blocked = [r["stats"] for r in rows]
    assert low["LifeLeechPerHit"] == pytest.approx(low["MH_PhysicalHitAverage"] * .1)
    assert capped["LifeLeechPerHit"] == pytest.approx(4000)
    assert reduced["LifeLeechPerHit"] == pytest.approx(1000)
    assert blocked["LifeLeechPerHit"] == 0
    assert capped["LifeLeechPerHit"] > capped["Life"] * .1


def test_leech_preserves_damage_type_ratios(run_damage):
    mods = BASE.replace("10000", "100000") + "\nAdds 100000 to 100000 Fire Damage to Attacks"
    only_physical, both_types = [r["stats"] for r in run_damage([
        {"mods": mods, "resistance": 0},
        {"mods": mods + "\nLeech 10% of Fire Damage as Life", "resistance": 0},
    ])]
    physical = only_physical["MH_PhysicalHitAverage"]
    total = sum(only_physical["MH_" + t + "HitAverage"] for t in ["Physical", "Fire", "Cold", "Lightning", "Chaos"])
    assert only_physical["LifeLeechPerHit"] == pytest.approx(4000 * physical / total)
    assert both_types["LifeLeechPerHit"] == pytest.approx(4000)


def test_leech_single_instance_speed_and_amount(run_damage):
    rows = run_damage([
        {"mods": BASE, "resistance": 0},
        {"mods": BASE + "\n1000% increased Attack Speed", "resistance": 0},
        {"mods": BASE + "\n100% increased amount of Life Leeched", "resistance": 0},
        {"mods": BASE + "\nLeech Life 20% slower", "resistance": 0},
        {"mods": BASE + "\n50% increased Life Recovery rate", "resistance": 0},
    ])
    base, fast, amount, slow, recovery = [r["stats"] for r in rows]
    assert base["LifeLeechDuration"] == 1
    assert fast["Speed"] > base["Speed"]
    assert fast["LifeLeechRate"] == pytest.approx(base["LifeLeechRate"])
    assert all(r["stats"]["LifeLeechInstances"] <= 1 for r in rows)
    assert amount["LifeLeechPerHit"] == pytest.approx(base["LifeLeechPerHit"] * 2)
    assert slow["LifeLeechDuration"] == pytest.approx(1.25)
    assert slow["LifeLeechPerHit"] == pytest.approx(base["LifeLeechPerHit"])
    assert slow["LifeLeechRate"] == pytest.approx(base["LifeLeechRate"] * .8)
    assert recovery["LifeLeechPerHit"] == pytest.approx(base["LifeLeechPerHit"] * 1.5)


def test_impale_generation_and_explicit_extraction(run_damage):
    mods = "Your Hits can't be Evaded\nNever deal Critical Hits\nAdds 1000 to 1000 Physical Damage to Attacks\n100% chance to Impale Enemies on Hit"
    rows = run_damage([
        {"mods": mods}, {"mods": mods, "impale": 500},
        {"mods": mods + "\n100% increased Physical Damage", "impale": 500},
        {"mods": mods + "\n100% increased Impale Magnitude"},
    ])
    base, extract, scaled, magnitude = [r["stats"] for r in rows]
    assert base["ImpaleChance"] == 100
    assert base["ImpaleStoredHitMagnitude"] == pytest.approx(base["MH_PhysicalStoredHitAvg"] * .3)
    assert base["ImpaleDPS"] == 0
    assert extract["MH_PhysicalStoredHitAvg"] - base["MH_PhysicalStoredHitAvg"] == pytest.approx(500)
    assert extract["CombinedDPS"] > base["CombinedDPS"]
    assert scaled["ImpaleExtractedOnHit"] == 500
    assert magnitude["ImpaleStoredHitMagnitude"] == pytest.approx(base["ImpaleStoredHitMagnitude"] * 2)
    assert magnitude["CombinedDPS"] == pytest.approx(base["CombinedDPS"])


def test_impale_support_prevents_extraction(run_damage):
    mods = "Your Hits can't be Evaded\nNever deal Critical Hits\nAdds 1000 to 1000 Physical Damage to Attacks"
    normal, supported = [r["stats"] for r in run_damage([
        {"mods": mods, "impale": 500},
        {"mods": mods, "impale": 500, "xml": synthetic(support="SupportImpalePlayer")},
    ])]
    assert supported["ImpaleChance"] == 100
    assert supported["ImpaleStoredHitMagnitude"] > 0
    assert supported["ImpaleExtractedOnHit"] == 0
    assert normal["CombinedDPS"] > supported["CombinedDPS"]


def test_impale_spell_generation_has_no_extraction(run_damage):
    rows = run_damage([
        {"xml": synthetic("BonestormPlayer")},
        {"xml": synthetic("BonestormPlayer"), "impale": 10000},
        {"xml": synthetic("FireballPlayer"), "impale": 10000},
    ])
    source, configured, elemental = [r["stats"] for r in rows]
    assert source["ImpaleStoredHitMagnitude"] == pytest.approx(source["PhysicalStoredHitAvg"] * .9)
    assert source["ImpaleStoredHitMagnitude"] > 0
    assert configured["CombinedDPS"] == pytest.approx(source["CombinedDPS"])
    assert configured["ImpaleExtractedOnHit"] == 0
    assert elemental["ImpaleStoredHitMagnitude"] == 0
    assert elemental["ImpaleExtractedOnHit"] == 0


def test_leech_crit_and_noncrit_are_capped_separately(run_damage):
    mods = BASE.replace("Never deal Critical Hits\n", "").replace("10000", "30000")
    row = run_damage([{"mods": mods, "resistance": 0}])[0]["stats"]
    chance = row["CritChance"] / 100
    assert 0 < chance < 1
    assert row["MH_PhysicalHitAverage"] < 40000 < row["MH_PhysicalCritAverage"]
    expected = (1-chance) * row["MH_PhysicalHitAverage"] * .1 + chance * 4000
    assert row["LifeLeechPerHit"] == pytest.approx(expected)


def test_leech_instant_and_converted_resource_scope(run_damage):
    rows = run_damage([
        {"mods": BASE, "resistance": 0},
        {"mods": BASE + "\nLife Leech is instant", "resistance": 0},
        {"mods": BASE + "\nLife Leech is converted to Energy Shield Leech\n+1000 to maximum Energy Shield\n100% increased amount of Life Leeched", "resistance": 0},
        {"mods": BASE + "\nLeech 10% of Physical Attack Damage as Mana\nMana Leech is instant\nMana Leech effects also recover Energy Shield\n+1000 to maximum Energy Shield", "resistance": 0},
        {"mods": BASE + "\nLeech 10% of Physical Attack Damage as Mana\nMana Leech effects also recover Energy Shield\n+1000 to maximum Energy Shield", "resistance": 0},
        {"mods": BASE + "\nExcess Life Recovery from Leech is applied to Energy Shield\n+1000 to maximum Energy Shield", "resistance": 0, "full_life": True},
    ])
    normal, instant, converted, copied, mana_over_time, excess_life = [r["stats"] for r in rows]
    assert instant["LifeLeechPerHit"] == pytest.approx(normal["LifeLeechPerHit"])
    assert instant["LifeLeechDuration"] == 0
    assert instant["LifeLeechInstantRate"] == pytest.approx(instant["LifeLeechPerHit"] * instant["Speed"] * instant["HitChance"] / 100)
    assert converted["LifeLeechPerHit"] == 0
    assert converted["EnergyShieldLeechPerHit"] == pytest.approx(normal["LifeLeechPerHit"])
    assert copied["EnergyShieldLeechPerHit"] == pytest.approx(copied["ManaLeechPerHit"])
    assert copied["EnergyShieldLeechRate"] == pytest.approx(copied["ManaLeechRate"])
    assert mana_over_time["EnergyShieldLeechRate"] == pytest.approx(mana_over_time["ManaLeechRate"])
    assert mana_over_time["MaxEnergyShieldLeechRate"] == pytest.approx(mana_over_time["MaxManaLeechRate"])
    assert excess_life["LifeLeechRate"] == excess_life["MaxLifeLeechRate"] == 0
    assert excess_life["EnergyShieldLeechPerHit"] == pytest.approx(normal["LifeLeechPerHit"])
    assert excess_life["MaxEnergyShieldLeechRate"] == pytest.approx(normal["MaxLifeLeechRate"])


def test_leech_attack_spell_dot_and_minion_scopes(run_damage):
    rows = run_damage([
        {"xml": synthetic("FireballPlayer"), "mods": BASE, "resistance": 0},
        {"xml": synthetic("FireballPlayer"), "mods": "10% of Spell Damage Leeched as Life", "resistance": 0},
        {"xml": synthetic("ContagionPlayer"), "mods": "10% of Spell Damage Leeched as Life", "resistance": 0},
        {"xml": synthetic("RaiseZombiePlayer"), "mods": "Minions Leech 10% of Damage as Life\n+1000 to maximum Life", "resistance": 0},
    ])
    attack_mod_spell, spell_mod_spell, dot, minion = rows
    assert attack_mod_spell["stats"]["LifeLeechPerHit"] == 0
    assert spell_mod_spell["stats"]["LifeLeechPerHit"] > 0
    assert dot["stats"]["TotalDotDPS"] > 0
    assert dot["stats"]["LifeLeechPerHit"] == 0
    assert minion["stats"]["LifeLeechPerHit"] == 0
    assert minion["minion"]["LifeLeechPerHit"] > 0


def test_impale_crit_restriction_and_no_physical(run_damage):
    mods = "Your Hits can't be Evaded\nAdds 1000 to 1000 Physical Damage to Attacks\nCritical Hits inflict Impale\nCritical Hits cannot Extract Impale"
    rows = run_damage([
        {"mods": mods, "impale": 500},
        {"mods": mods + "\nDeal no Physical Damage", "impale": 500},
    ])
    normal, no_physical = [r["stats"] for r in rows]
    assert normal["ImpaleChance"] == 0
    assert normal["ImpaleChanceOnCrit"] == 100
    assert normal["ImpaleStoredHitMagnitude"] == 0
    assert normal["ImpaleStoredCritMagnitude"] > 0
    assert normal["ImpaleExtractedOnHit"] == 500
    assert normal["ImpaleExtractedOnCrit"] == 0
    assert no_physical["ImpaleStoredCritMagnitude"] == 0
    assert no_physical["ImpaleExtractedOnHit"] == 0


def test_impale_does_not_apply_to_minions_or_other_full_dps_groups(run_damage):
    xml = synthetic(extra_skill="MeleeAtAnimationSpeed")
    rows = run_damage([
        {"xml": xml, "mods": BASE},
        {"xml": xml, "mods": BASE, "impale": 500},
        {"xml": synthetic("RaiseZombiePlayer"), "impale": 500},
        {"xml": synthetic("RaiseZombiePlayer")},
    ])
    baseline, configured, minion_configured, minion_baseline = rows
    assert len(configured["full_skills"]) == len(baseline["full_skills"]) == 2
    assert configured["full_skills"][0]["dps"] > baseline["full_skills"][0]["dps"]
    assert configured["full_skills"][1]["dps"] == pytest.approx(baseline["full_skills"][1]["dps"])
    assert minion_configured["minion"]["CombinedDPS"] > 0
    assert minion_configured["minion"]["CombinedDPS"] == pytest.approx(minion_baseline["minion"]["CombinedDPS"])
    assert minion_configured["minion"]["ImpaleExtractedOnHit"] == 0


def test_leech_resistance_table_provenance_and_override_diagnostic(run_damage):
    rows = run_damage([
        {"mods": BASE, "enemy_level": 1},
        {"mods": BASE, "enemy_level": 83},
        {"mods": BASE, "enemy_level": 83, "resistance": 75},
    ])
    low, high, explicit = rows
    assert low["stats"]["EnemyLeechResistance"] == 60
    assert high["stats"]["EnemyLeechResistance"] == 97.47
    assert high["stats"]["LifeLeechPerHit"] < low["stats"]["LifeLeechPerHit"]
    provisional = next(m for m in high["mechanics"] if m["mechanic"] == "leech_recovery")
    verified = next(m for m in explicit["mechanics"] if m["mechanic"] == "leech_recovery")
    assert "leech_resistance_percent" in provisional["required_inputs"]
    assert "leech_resistance_percent" not in verified["required_inputs"]


def test_current_vaal_pact_amount_and_duration(run_damage):
    base, pact = [r["stats"] for r in run_damage([
        {"mods": BASE, "resistance": 0},
        {"mods": BASE + "\nVaal Pact", "resistance": 0},
    ])]
    assert pact["LifeLeechPerHit"] == pytest.approx(base["LifeLeechPerHit"] * 1.5)
    assert pact["LifeLeechDuration"] == pytest.approx(1 / .33)
    assert pact["LifeLeechRate"] == pytest.approx(base["LifeLeechRate"] * 1.5 * .33)


def test_mana_drain_flat_amount_quality_and_no_monster_resistance(run_damage):
    rows = run_damage([
        {"xml": synthetic("ManaDrainPlayer"), "resistance": 0},
        {"xml": synthetic("ManaDrainPlayer"), "resistance": 100},
        {"xml": synthetic("ManaDrainPlayer", level=20, quality=20), "resistance": 100},
        {"xml": synthetic("ManaDrainPlayer"), "mods": "Cannot Leech Mana"},
    ])
    base, resisted, quality, blocked = [r["stats"] for r in rows]
    assert base["ManaLeechPerHit"] == 30
    assert base["ManaLeechDuration"] == pytest.approx(1 / .3)
    assert resisted["ManaLeechPerHit"] == 30
    assert quality["ManaLeechPerHit"] == 408 + 90
    assert blocked["ManaLeechPerHit"] == 0
    recovery = next(m for m in rows[0]["mechanics"] if m["mechanic"] == "leech_recovery")
    assert "leech_resistance_percent" not in recovery["required_inputs"]
    assert next(m["value"] for m in recovery["metrics"] if m["name"] == "mana_leech_per_use") == 30
