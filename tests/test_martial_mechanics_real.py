"""Numeric 0.5 mechanics regressions using synthetic, non-account fixtures."""
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

FIXTURE = Path(__file__).parent / "fixtures/engine_synthetic.xml"
MODULE = Path(__file__).parents[1] / "src/poe2_companion/lua/martial_mechanics.lua"
COVERAGE = MODULE.with_name("skill_coverage.lua")


def synthetic(skill, *, level=1, quality=0, support=None, clone=None, recent=None,
              custom="", enabled=True, set_index=1, main=2):
    root = ET.fromstring(FIXTURE.read_bytes())
    root.find("Build").set("mainSocketGroup", str(main))
    dummy = ET.SubElement(root.find("./Skills/SkillSet"), "Skill", {"enabled":"true", "mainActiveSkill":"1"})
    ET.SubElement(dummy,"Gem",{"skillId":"FireballPlayer","nameSpec":"Fireball","level":"1","quality":"0","enabled":"true"})
    group = ET.SubElement(root.find("./Skills/SkillSet"), "Skill", {
        "enabled": str(enabled).lower(), "mainActiveSkill": str(2 if clone else 1)})
    gem = ET.SubElement(group, "Gem", {"skillId": skill, "nameSpec": skill, "level": str(level),
                                  "quality": str(quality), "enabled": "true"})
    ET.SubElement(gem, "StatSetIndex", {"grantedEffect": skill, "index": str(set_index)})
    for name in (support, clone):
        if name:
            ET.SubElement(group, "Gem", {"skillId": name, "nameSpec": name, "level": "1",
                                          "quality": "0", "enabled": "true"})
    config = root.find("./Config/ConfigSet")
    ET.SubElement(config,"Input",{"name":"enemyArmour","number":"0"})
    if recent is not None:
        ET.SubElement(config, "Input", {"name": "conditionLostGhostShroudRecently", "boolean": str(recent).lower()})
    ET.SubElement(config, "Input", {"name": "customMods", "string": custom})
    return ET.tostring(root).decode()


@pytest.fixture
def run_martial(tmp_path):
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
local coverage=dofile(input.coverage)
local result={}
for _,case in ipairs(input.cases) do
 loadBuildFromXML(case.xml,'')
 for _,id in ipairs(case.nodes or {}) do
  local node=assert(build.spec.nodes[id]);node.alloc=true;node.isGrantedPassive=nil;node.isFreeAllocate=nil;build.spec.allocNodes[id]=node
 end
 local weapon=new('Item'):Item('Rarity: RARE\\nSynthetic Staff\\nWrapped Quarterstaff\\nImplicits: 0\\nAdds 50 to 50 Physical Damage')
 build.itemsTab:AddItem(weapon);build.itemsTab.slots['Weapon 1']:SetSelItemId(weapon.id)
 local chest=new('Item'):Item('Rarity: RARE\\nSynthetic Armour\\nSilk Robe\\nImplicits: 0\\n+1000 to Evasion Rating\\n+500 to maximum Energy Shield')
 build.itemsTab:AddItem(chest);build.itemsTab.slots['Body Armour']:SetSelItemId(chest.id)
 build.buildFlag=true;runCallback('OnFrame')
 assert(not __mainObject__.promptMsg)
 local env,out=build.calcsTab.mainEnv,build.calcsTab.mainOutput
 if case.clear_caches then wipeGlobalCache() end
 local mechanics,issues=module.inspect(build,env,out,case.configuration)
 local skills={}
 for _,active in ipairs(env.player.activeSkillList) do
  skills[#skills+1]={id=active.activeEffect.grantedEffect.id,disabled=active.disableReason~=nil,
    clone=active.skillTypes[SkillType.SupportedByHollowForm] or false,
    cannot_consume=active.skillModList:Flag(active.skillCfg,'Condition:CannotConsumeCharges'),
    statset=active.activeEffect.statSet and active.activeEffect.statSet.statSet==active.activeEffect.grantedEffect.statSets[2]}
 end
 result[#result+1]={mechanics=mechanics,issues=issues,coverage=coverage.inspect(build),
  evasion=out.Evasion,es_regen=out.EnergyShieldRegenRecovery,dps=out.CombinedDPS,
  average=out.AverageDamage,speed=out.Speed,cost=out.ManaCost,skills=skills,
  stun_threshold=out.StunThreshold,block=out.BlockChance,spell_block=out.SpellBlockChance}
end
io.write(json.encode(result))
''')
    def run(cases):
        env = {**os.environ, "LUA_PATH": str(Path(source)/"runtime/lua/?.lua")+";"+str(Path(source)/"runtime/lua/?/init.lua")+";;"}
        result = subprocess.run([os.environ.get("POE2_TEST_LUAJIT", "luajit"), str(script)],
                                cwd=Path(source)/"src", input=json.dumps({"cases": cases, "module": str(MODULE), "coverage": str(COVERAGE)}),
                                text=True, capture_output=True, env=env, timeout=100)
        assert result.returncode==0, result.stderr[-2000:]
        return json.loads(result.stdout)
    return run


def mechanic(row, name):
    result = next(m for m in row["mechanics"] if m["mechanic"]==name)
    return result, {m["name"]: m["value"] for m in result["metrics"]}


def test_ghost_dance_real_regeneration_is_conditional_and_scales_once(run_martial):
    rows=run_martial([{"xml":synthetic("GhostDancePlayer",recent=value,custom=custom)}
                      for value,custom in ((None,""),(False,""),(True,""),(True,"50% increased Energy Shield Recovery Rate"))])
    unknown,off,on,recovery=rows
    assert unknown["es_regen"]==off["es_regen"]==0
    assert on["es_regen"]==pytest.approx(on["evasion"]*.02,abs=.051)
    assert recovery["es_regen"]==pytest.approx(on["evasion"]*.02*1.5,abs=.051)
    assert mechanic(unknown,"ghost_dance")[0]["required_inputs"]==["ghost_shroud_lost_recently"]
    assert mechanic(off,"ghost_dance")[0]["status"]=="calculated"
    assert not [x for x in on["coverage"] if x.get("skill_id")=="GhostDancePlayer"]


def test_ghost_interval_uses_cooldown_rate_not_duration_or_flat_cooldown(run_martial):
    rows=run_martial([{"xml":synthetic("GhostDancePlayer",level=level,custom=custom,recent=False)}
                     for level,custom in ((1,""),(20,""),(1,"50% increased Cooldown Recovery Rate"),
                                          (1,"100% increased Skill Effect Duration"),(1,"-2 seconds to all Cooldowns"))])
    periods=[mechanic(row,"ghost_dance")[1]["ghost_shroud_interval_seconds"] for row in rows]
    assert periods==pytest.approx([12,10.1,8,12,12])


def test_hollow_focus_limits_duration_and_period_are_distinct(run_martial):
    rows=run_martial([{"xml":synthetic("HollowFocusPlayer",support=support,custom=custom)}
                     for support,custom in ((None,""),("SupportIncreaseLimitPlayer",""),
                                             (None,"50% increased Cooldown Recovery Rate"),
                                             (None,"100% increased Skill Effect Duration"))])
    values=[mechanic(row,"hollow_focus")[1] for row in rows]
    assert [v["bell_active_limit"] for v in values]==[3,4,3,3]
    assert [v["bell_duration_seconds"] for v in values]==pytest.approx([21,10.5,21,42])
    assert [v["bell_spawn_interval_seconds"] for v in values]==pytest.approx([3,3,2,3])
    assert all(v["bell_hits_to_destroy"]==1 for v in values)
    assert not [i for i in rows[0]["coverage"] if i.get("skill_id")=="HollowFocusPlayer" and i["code"]=="unsupported_skill_stat"]


def test_hollow_form_event_cost_count_retention_and_no_empty_socket_damage(run_martial):
    rows=run_martial([{"xml":synthetic("MetaHollowFormPlayer",quality=quality,support=support)}
                     for quality,support in ((0,None),(20,None),(20,"SupportPerpetualChargePlayer"))])
    values=[mechanic(row,"hollow_form")[1] for row in rows]
    assert [v["hollow_form_charge_retention_chance"] for v in values]==[0,10,35]
    assert [v["hollow_form_expected_charges_removed_per_charged_use"] for v in values]==pytest.approx([1,.9,.65])
    assert all(v["hollow_form_images_without_charge"]==1 and v["hollow_form_expected_images_with_charge"]==3 for v in values)
    assert all(v["hollow_form_cost_multiplier_per_image"]==.8 for v in values)
    assert all(v["hollow_form_socketed_attack_count"]==0 for v in values)
    assert all("hollow_form_unrounded_mana_cost_per_image" not in v for v in values)


def test_disabled_martial_skills_do_not_supply_recovery_or_mechanics(run_martial):
    rows=run_martial([{"xml":synthetic(skill,recent=True,enabled=False,main=1)}
                      for skill in ("GhostDancePlayer","HollowFocusPlayer","MetaHollowFormPlayer")])
    assert all(not row["mechanics"] and row["es_regen"]==0 for row in rows)


def test_hollow_form_cloned_attacks_keep_verified_damage_speed_and_charge_block(run_martial):
    plain,manual,clone=run_martial([{"xml":synthetic("StormWavePlayer")},
                           {"xml":synthetic("StormWavePlayer",custom="15% less Damage")},
                           {"xml":synthetic("MetaHollowFormPlayer",clone="StormWavePlayer")}])
    assert any(skill["clone"] and skill["cannot_consume"] for skill in clone["skills"]), clone
    assert clone["average"]==pytest.approx(manual["average"])
    assert clone["average"] < plain["average"]
    assert clone["speed"]==pytest.approx(plain["speed"]*.7)
    values=mechanic(clone,"hollow_form")[1]
    assert values["hollow_form_socketed_attack_count"]==1
    assert values["hollow_form_unrounded_mana_cost_per_image"]==pytest.approx(clone["cost"]*.8)


def test_hollow_form_explicit_rate_projects_image_hits_without_multiplying_dps(run_martial):
    xml=synthetic("MetaHollowFormPlayer",clone="StormWavePlayer",quality=20)
    cases=[{"xml":xml,"configuration":{"hollow_form_attack_skill_id":name,
               "hollow_form_channel_uses_per_second":.5,"hollow_form_power_charge_use_fraction":fraction}}
           for name,fraction in (("StormWavePlayer",0),("StormWavePlayer",1),("FireballPlayer",1))]
    cases.append({"xml":synthetic("MetaHollowFormPlayer",clone="StormWavePlayer",main=1),
                  "clear_caches":True,"configuration":cases[1]["configuration"]})
    uncharged,charged,invalid,uncached=run_martial(cases)
    a=mechanic(uncharged,"hollow_form_simulation")[1]
    b=mechanic(charged,"hollow_form_simulation")[1]
    assert a["hollow_form_images_per_second"]==.5
    assert b["hollow_form_images_per_second"]==1.5
    assert b["hollow_form_image_hit_dps"]==pytest.approx(charged["average"]*1.5)
    assert b["hollow_form_expected_charges_removed_per_second"]==pytest.approx(.45)
    assert a["hollow_form_expected_charges_removed_per_second"]==0
    assert b["hollow_form_unrounded_mana_per_second"]==pytest.approx(charged["cost"]*.8*1.5)
    assert not any(m["mechanic"]=="hollow_form_simulation" for m in invalid["mechanics"])
    assert "hollow_form_socketed_skill" in mechanic(invalid,"hollow_form")[0]["required_inputs"]
    assert not any(m["mechanic"]=="hollow_form_simulation" for m in uncached["mechanics"])
    assert "hollow_form_socketed_skill" in mechanic(uncached,"hollow_form")[0]["required_inputs"]


def test_heightened_charges_scales_additional_images_not_base_image(run_martial):
    normal,heightened=run_martial([{"xml":synthetic("MetaHollowFormPlayer",support=support)}
                                    for support in (None,"SupportHeightenedChargesPlayer")])
    assert mechanic(normal,"hollow_form")[1]["hollow_form_expected_images_with_charge"]==3
    assert mechanic(heightened,"hollow_form")[1]["hollow_form_expected_images_with_charge"]==pytest.approx(3.4)


def test_tempest_bell_limit_progression_combo_and_durability(run_martial):
    rows=run_martial([{"xml":synthetic("TempestBellPlayer",level=level,support=support)}
                      for level,support in ((1,None),(8,None),(16,None),(24,None),
                                             (16,"SupportIncreaseLimitPlayer"),(16,"SupportDurabilityPlayer"))])
    values=[mechanic(row,"tempest_bell")[1] for row in rows]
    assert [v["bell_active_limit"] for v in values]==[1,2,3,4,4,3]
    assert [v["bell_hits_to_destroy"] for v in values]==[10,10,10,10,10,12]
    assert [v["bell_duration_seconds"] for v in values]==[6,6,6,6,3,6]
    for value in values:
        assert value["tempest_bell_combo_required"]==4
        assert value["tempest_bell_combo_decay_seconds"]==8
        assert value["tempest_bell_shockwave_interval_seconds"]==.3
        assert value["tempest_bell_shockwave_rate_limit_per_second"]==pytest.approx(10/3)
    assert not [i for i in rows[0]["coverage"] if i.get("skill_id")=="TempestBellPlayer" and i["code"]=="unsupported_skill_stat"]


def test_wind_dancer_period_is_not_duration_or_cooldown_and_stages_change_evasion(run_martial):
    cases=[]
    for level,custom,count in ((1,"",0),(1,"",3),(20,"",3),
                             (1,"100% increased Skill Effect Duration",3),
                             (1,"50% increased Cooldown Recovery Rate",3)):
        root=ET.fromstring(synthetic("WindDancerPlayer",level=level,custom=custom))
        ET.SubElement(root.find("./Config/ConfigSet"),"Input",{"name":"windDancerStacks","number":str(count)})
        cases.append({"xml":ET.tostring(root).decode()})
    rows=run_martial(cases)
    values=[mechanic(row,"wind_dancer")[1] for row in rows]
    assert [v["wind_dancer_stage_interval_seconds"] for v in values]==[1.5,1.5,1.12,1.5,1.5]
    assert rows[1]["evasion"]==pytest.approx(rows[0]["evasion"]*1.3,abs=1)
    assert values[1]["wind_dancer_full_refill_seconds"]==4.5
    assert values[2]["wind_dancer_full_refill_seconds"]==pytest.approx(3.36)


def test_refutation_spent_ward_quality_threshold_and_paused_cooldown(run_martial):
    cases=[]
    for enabled,spent,quality in ((False,0,0),(True,0,0),(True,9,0),(True,10,0),(True,100,0),(True,100,20)):
        root=ET.fromstring(synthetic("RefutationPlayer",quality=quality,main=1))
        config=root.find("./Config/ConfigSet")
        ET.SubElement(config,"Input",{"name":"conditionRefutationActive","boolean":str(enabled).lower()})
        ET.SubElement(config,"Input",{"name":"refutationWardSpent","number":str(spent)})
        cases.append({"xml":ET.tostring(root).decode()})
    rows=run_martial(cases)
    base=rows[0]["stun_threshold"]
    assert [row["stun_threshold"]/base for row in rows]==pytest.approx([1,.5,.5,.525,.75,1.05])
    assert [row["block"] for row in rows]==[0,100,100,100,100,100]
    assert [row["spell_block"] for row in rows]==[0,100,100,100,100,100]
    values=mechanic(rows[1],"refutation")[1]
    assert values["refutation_buff_duration_seconds"]==pytest.approx(4.026)
    assert values["refutation_cycle_seconds"]==pytest.approx(15.939)
    assert values["refutation_maximum_uptime_percent"]==pytest.approx(4.026/15.939*100)
    assert values["refutation_light_stun_immunity"]==1
    assert mechanic(rows[1],"refutation")[0]["required_inputs"]==["incoming_hit_sequence"]
    assert not [i for i in rows[1]["coverage"] if i.get("skill_id")=="RefutationPlayer" and i["code"]=="unsupported_skill_stat"]


def test_tempest_shockwave_prior_hits_ailments_knockback_are_separate(run_martial):
    cases=[]
    for hits,types,knockback in ((0,[],0),(5,[],0),(10,[],0),(0,["Cold"],0),(0,["Fire","Cold","Lightning"],0),(0,[],.1)):
        root=ET.fromstring(synthetic("TempestBellPlayer",quality=20,set_index=3))
        config=root.find("./Config/ConfigSet")
        ET.SubElement(config,"Input",{"name":"tempestBellPriorHits","number":str(hits)})
        ET.SubElement(config,"Input",{"name":"tempestBellKnockbackMetres","number":str(knockback)})
        for element in ("Fire","Cold","Lightning"):
            ET.SubElement(config,"Input",{"name":"conditionTempestBell"+element+"Ailment","boolean":str(element in types).lower()})
        cases.append({"xml":ET.tostring(root).decode()})
    rows=run_martial(cases)
    values=[mechanic(row,"tempest_bell_shockwave")[1] for row in rows]
    assert values[1]["tempest_bell_damage_more_percent"]==15
    assert rows[1]["average"]>rows[0]["average"]
    assert values[2]["tempest_bell_prior_hits_applied"]==0
    assert rows[2]["average"]==rows[0]["average"]
    assert "bell_hit_events" in mechanic(rows[2],"tempest_bell_shockwave")[0]["required_inputs"]
    assert values[3]["tempest_bell_cold_gain_percent"]==30
    assert rows[4]["average"]>rows[3]["average"]>rows[0]["average"]
    assert values[5]["tempest_bell_knockback_area_more_percent"]==30
    assert values[5]["tempest_bell_shockwave_area_radius"]>values[0]["tempest_bell_shockwave_area_radius"]
    assert rows[5]["average"]==rows[0]["average"]
    assert not [i for i in rows[0]["coverage"] if i.get("skill_id")=="TempestBellPlayer" and i["code"]=="unsupported_skill_stat"]


def test_refutation_respects_cannot_block_and_inactive_skill(run_martial):
    cases=[]
    for enabled,custom in ((True,"Cannot Block"),(False,"")):
        root=ET.fromstring(synthetic("RefutationPlayer",enabled=enabled,custom=custom,main=1))
        config=root.find("./Config/ConfigSet")
        ET.SubElement(config,"Input",{"name":"conditionRefutationActive","boolean":"true"})
        ET.SubElement(config,"Input",{"name":"refutationWardSpent","number":"100"})
        cases.append({"xml":ET.tostring(root).decode()})
    cannot,disabled=run_martial(cases)
    assert cannot["block"]==cannot["spell_block"]==0
    assert disabled["block"]==disabled["spell_block"]==0
    assert not any(row["mechanic"]=="refutation" for row in disabled["mechanics"])


def test_actual_gemling_quality_node_changes_shroud_and_bell_limits(run_martial):
    cases=[{"xml":synthetic(skill,quality=20,recent=False),"nodes":nodes}
           for skill,nodes in (("GhostDancePlayer",[]),("GhostDancePlayer",[14429]),
                               ("TempestBellPlayer",[]),("TempestBellPlayer",[14429]))]
    normal_ghost,quality_ghost,normal_bell,quality_bell=run_martial(cases)
    assert mechanic(normal_ghost,"ghost_dance")[1]["ghost_shroud_maximum"]==3
    assert mechanic(quality_ghost,"ghost_dance")[1]["ghost_shroud_maximum"]==4
    assert mechanic(normal_bell,"tempest_bell")[1]["bell_hits_to_destroy"]==10
    assert mechanic(quality_bell,"tempest_bell")[1]["bell_hits_to_destroy"]==20
