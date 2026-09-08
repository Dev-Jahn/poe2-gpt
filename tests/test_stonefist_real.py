"""Real-engine synthetic checks; no private account/export fixtures."""
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

FIXTURE = Path(__file__).parent / "fixtures/engine_synthetic.xml"
MODULE = Path(__file__).parents[1] / "src/poe2_companion/lua/stonefist.lua"


def synthetic(nodes="", *, full_life=False, skill=None, support=None, quality=0):
    root = ET.fromstring(FIXTURE.read_bytes())
    root.find("Build").set("className", "Monk")
    root.find("Build").set("ascendClassName", "Martial Artist")
    tree = root.find("./Tree/Spec")
    tree.set("classId", "8")
    tree.set("classInternalId", "10")
    tree.set("ascendClassId", "1")
    tree.set("ascendancyInternalId", "Monk1")
    tree.set("nodes", nodes)
    config = root.find("./Config/ConfigSet")
    for name in ("usePowerCharges", "useFrenzyCharges", "useEnduranceCharges"):
        ET.SubElement(config, "Input", {"name": name, "boolean": "true"})
    ET.SubElement(config, "Input", {"name": "conditionFullLife", "boolean": str(full_life).lower()})
    if skill:
        group = ET.SubElement(root.find("./Skills/SkillSet"), "Skill", {"enabled": "true", "mainActiveSkill": "1"})
        ET.SubElement(group, "Gem", {"skillId": skill, "nameSpec": skill, "level": "1", "quality": str(quality), "enabled": "true"})
        if support:
            ET.SubElement(group, "Gem", {"skillId": support, "nameSpec": support, "level": "1", "quality": "0", "enabled": "true"})
    return ET.tostring(root).decode()


@pytest.fixture
def run_stonefist(tmp_path):
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
module.register()
local result={}
for _,case in ipairs(input.cases) do
 loadBuildFromXML(case.xml,'')
 if case.gloves then
  local item=new('Item'):Item(case.gloves)
  build.itemsTab:AddItem(item)
  build.itemsTab.slots.Gloves:SetSelItemId(item.id)
 end
 if case.weapon then
  local item=new('Item'):Item(case.weapon)
  build.itemsTab:AddItem(item)
  build.itemsTab.slots['Weapon 1']:SetSelItemId(item.id)
 end
 -- Isolate these canonical nodes without allocating unrelated travel stats.
 -- The synthetic XML has no travel paths or anointed items; upstream treats
 -- disconnected Notables as obsolete item grants and otherwise removes them.
 -- This is fixture setup only, never used by the production worker.
 for _,id in ipairs(case.test_nodes) do
  local node=assert(build.spec.nodes[id])
  node.alloc=true;node.isGrantedPassive=nil;node.isFreeAllocate=nil
  build.spec.allocNodes[id]=node
 end
 build.buildFlag=true;runCallback('OnFrame')
 assert(not __mainObject__.promptMsg)
 local env,out=build.calcsTab.mainEnv,build.calcsTab.mainOutput
 local mechanics,issues=module.inspect(build,env,out)
 local unknown={}
 for _,id in ipairs({39595,36643,9652,7847}) do
  local node=build.spec.allocNodes[id]
  if node and (node.unknown or node.extra) then unknown[#unknown+1]=id end
 end
 local glove=env.player.itemList.Gloves
 local row={mechanics=mechanics,issues=issues,unknown=unknown,
  life=out.Life,dps=out.CombinedDPS,req_int=out.ReqInt,req_str=out.ReqStr,req_dex=out.ReqDex,
  recharge=out.EnergyShieldRechargeDelay,
  glove_attributes_ignored=module.ignore_glove_attributes(glove,env) and true or false,
  glove_evasion=glove and glove:GetArmourDataValue('Evasion',build.characterLevel),
  glove_es=glove and glove:GetArmourDataValue('EnergyShield',build.characterLevel),
  glove_level=glove and glove.requirements.level,
 }
 result[#result+1]=row
end
io.write(json.encode(result))
''')
    def run(cases):
        cases = [{**case, "test_nodes": [int(n) for n in ET.fromstring(case["xml"]).find("./Tree/Spec").get("nodes", "").split(",") if n]}
                 for case in cases]
        env = {**os.environ,
               "LUA_PATH": str(Path(source) / "runtime/lua/?.lua") + ";" + str(Path(source) / "runtime/lua/?/init.lua") + ";;"}
        result = subprocess.run([os.environ.get("POE2_TEST_LUAJIT", "luajit"), str(script)],
                                cwd=Path(source) / "src", input=json.dumps({"cases": cases, "module": str(MODULE)}),
                                text=True, capture_output=True, env=env, timeout=85)
        assert result.returncode == 0, result.stderr[-2000:]
        return json.loads(result.stdout)
    return run


def mechanic(row, name):
    value = next(m for m in row["mechanics"] if m["mechanic"] == name)
    return value, {metric["name"]: metric["value"] for metric in value["metrics"]}


def test_stonefist_import_preserves_exact_transformed_affixes(run_stonefist):
    glove = "Rarity: RARE\nSynthetic Gloves\nFists of Stone\nImplicits: 2\nHas +3 to Evasion Rating per player level\nHas +1 to maximum Energy Shield per player level\nHas +1 to Evasion Rating per player level\nHas +1 to maximum Energy Shield per player level\n+123 to maximum Life"
    cases = [{"xml": synthetic("39595"), "gloves": glove}, {"xml": synthetic(), "gloves": glove}]
    with_node, missing_node = run_stonefist(cases)
    assert not with_node["unknown"]
    assert with_node["glove_evasion"] == 360
    assert with_node["glove_es"] == 180
    assert with_node["life"] == missing_node["life"]
    assert mechanic(with_node, "stonefist")[0]["status"] == "calculated"
    assert mechanic(missing_node, "stonefist")[0]["status"] == "unsupported"
    assert {i["code"] for i in missing_node["issues"]} == {"stonefist_passive_missing"}


def test_glove_exemption_does_not_erase_other_requirements_or_guess_transform(run_stonefist):
    gloves = "Rarity: RARE\nSynthetic Gloves\nSombre Gloves\nLevelReq: 99\nImplicits: 0\n+38 to maximum Energy Shield"
    cases = [{"xml": synthetic(nodes), "gloves": gloves} for nodes in ("", "39595")]
    cases.append({"xml": synthetic("39595", skill="FireballPlayer"), "gloves": gloves,
                  "weapon": "Rarity: RARE\nSynthetic Weapon\nLong Quarterstaff\nImplicits: 0"})
    normal, exempt, other_requirement = run_stonefist(cases)
    assert normal["req_int"] > 0 and exempt.get("req_int", 0) == 0
    assert exempt["glove_level"] == 99
    assert exempt["glove_attributes_ignored"]
    assert any(other_requirement.get("req_" + attribute, 0) > 0 for attribute in ("str", "dex", "int"))
    assert mechanic(exempt, "stonefist")[0]["status"] == "unsupported"
    assert any(i["code"] == "unsupported_item_transformation" for i in exempt["issues"])


def test_charge_events_are_numeric_and_do_not_fabricate_player_dps(run_stonefist):
    base = "Rarity: RARE\nSynthetic Gloves\nFists of Stone\nImplicits: 0\n"
    ally = "6% chance to grant a Endurance Charge to Allies in your Presence on Hit\n6% chance to grant a Frenzy Charge to Allies in your Presence on Hit\n8% chance to grant a Power Charge to Allies in your Presence on Hit"
    plain, grants = run_stonefist([{"xml": synthetic("39595,36643"), "gloves": base},
                                    {"xml": synthetic("39595,36643"), "gloves": base + ally}])
    assert not grants["unknown"]
    assert grants["dps"] == plain["dps"]
    row, values = mechanic(grants, "ally_charges")
    assert row["status"] == "partial"
    assert values == {"power_grant_chance_per_hit": 8, "frenzy_grant_chance_per_hit": 6, "endurance_grant_chance_per_hit": 6}
    assert mechanic(grants, "charge_gain")[1]["power_extra_charge_chance"] == 10


def test_mending_deflection_applies_conditional_recharge_without_global_recoup(run_stonefist):
    gloves = "Rarity: RARE\nSynthetic Gloves\nFists of Stone\nImplicits: 0\n+100 to maximum Energy Shield"
    cases = [{"xml": synthetic("39595,9652", full_life=full_life), "gloves": gloves}
             for full_life in (False, True)]
    cases.append({"xml": synthetic("39595,9652"), "gloves": gloves + "\n50% increased Life Recovery Rate"})
    low, full, recovery = run_stonefist(cases)
    assert not low["unknown"] and not full["unknown"]
    assert low["recharge"] == pytest.approx(full["recharge"] / 1.2)
    row, values = mechanic(low, "deflected_recoup")
    assert row["status"] == "partial" and values["life_recoup_percent_per_deflected_hit"] == 15
    assert values["recoup_duration_seconds"] == 8
    assert mechanic(recovery, "deflected_recoup")[1]["life_recoup_percent_per_deflected_hit"] == 22.5


def test_charge_regulation_quality_changes_actual_consumption_interval(run_stonefist):
    rows = run_stonefist([{"xml": synthetic(skill="ChargeRegulationPlayer", quality=q)} for q in (0, 20)])
    for row, seconds in zip(rows, (10, 12.4), strict=True):
        info, values = mechanic(row, "charge_regulation")
        assert info["status"] == "partial" and info["skill_id"] == "ChargeRegulationPlayer"
        assert values["regulation_interval_seconds"] == pytest.approx(seconds)
        assert values["regulation_removals_per_charge_type_per_second"] == pytest.approx(1 / seconds)


def test_perpetual_charge_and_fabled_stag_combine_without_changing_burst_damage(run_stonefist):
    weapon = "Rarity: RARE\nSynthetic Weapon\nWrapped Quarterstaff\nImplicits: 0"
    rows = run_stonefist([{"xml": synthetic("7847", skill="FlickerStrikePlayer", support=support), "weapon": weapon}
                         for support in (None, "SupportPerpetualChargePlayer")])
    assert not rows[1]["unknown"]
    assert rows[0]["dps"] == rows[1]["dps"]
    assert mechanic(rows[0], "charge_consumption")[1]["charge_retention_chance"] == 10
    values = mechanic(rows[1], "charge_consumption")[1]
    assert values["charge_retention_chance"] == 35
    assert values["expected_removed_fraction"] == pytest.approx(.65)


def test_charge_profusion_two_projects_correct_generating_skill(run_stonefist):
    rows = run_stonefist([{"xml": synthetic(skill="CombatFrenzyPlayer", support="SupportChargeProfusionPlayerTwo")}])
    row, values = mechanic(rows[0], "charge_skill_gain")
    assert row["skill_id"] == "CombatFrenzyPlayer" and row["status"] == "partial"
    assert values == {"same_type_extra_charge_chance": 30, "random_type_extra_charge_chance": 15}


def test_inactive_nonselected_charge_groups_do_not_add_sustain_issues(run_stonefist):
    cases = []
    for enabled, slot in (("false", ""), ("true", "Weapon 1 Swap")):
        root = ET.fromstring(synthetic(skill="FireballPlayer"))
        group = ET.SubElement(root.find("./Skills/SkillSet"), "Skill", {"enabled": enabled, "slot": slot, "mainActiveSkill": "1"})
        ET.SubElement(group, "Gem", {"skillId": "ChargeRegulationPlayer", "nameSpec": "Charge Regulation", "level": "1", "quality": "0", "enabled": "true"})
        cases.append({"xml": ET.tostring(root).decode()})
    for row in run_stonefist(cases):
        assert not any(m["mechanic"] == "charge_regulation" for m in row["mechanics"])
        assert not any(i["code"] == "charge_sustain_unverified" for i in row["issues"])
