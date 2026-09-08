"""Real engine checks for granted skill levels, using synthetic inputs only."""
import json
import os
from pathlib import Path
import subprocess

import pytest


FIXTURE = Path(__file__).parent / "fixtures/engine_synthetic.xml"


@pytest.fixture
def granted_levels(tmp_path):
    source = os.environ.get("POE2_TEST_ENGINE_DIR")
    if not source:
        pytest.skip("Set POE2_TEST_ENGINE_DIR to run real PoE2 LuaJIT integration")
    script = tmp_path / "granted.lua"
    script.write_text('''
print=function() end
local json=require('dkjson')
local input=assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
local results={}
for _,case in ipairs(input.cases) do
 loadBuildFromXML(input.xml,'')
 build.characterLevel=case.character_level or 94
 build.characterLevelAutoMode=false
 for _,row in ipairs(case.items or {}) do
  local item=new('Item'):Item(row.raw)
  build.itemsTab:AddItem(item)
  -- AddItem auto-equips in an empty default slot. This fixture explicitly
  -- selects one slot and must not duplicate the same sceptre into both hands.
  for _,slot in pairs(build.itemsTab.orderedSlots) do
   if slot.selItemId==item.id and slot.slotName~=row.slot then slot:SetSelItemId(0) end
  end
  build.itemsTab.slots[row.slot]:SetSelItemId(item.id)
 end
 if case.gem then build.skillsTab:PasteSocketGroup(case.gem) end
 if case.gem_slot then
  local group=build.skillsTab.socketGroupList[1]
  group.slot=case.gem_slot
  build.skillsTab:ProcessSocketGroup(group)
 end
 if case.support then
  local group=build.skillsTab.socketGroupList[1]
  group.gemList[#group.gemList+1]={skillId=case.support,level=1,quality=0,enabled=true}
  build.skillsTab:ProcessSocketGroup(group)
 end
 if case.tree then
  local node=assert(build.spec.nodes[62743])
  node.alloc=true;node.isGrantedPassive=nil;node.isFreeAllocate=nil
  build.spec.allocNodes[node.id]=node
 end
 build.buildFlag=true;runCallback('OnFrame')
 assert(not __mainObject__.promptMsg)
 local steps={}
 local function snapshot()
  local env,out=build.calcsTab.mainEnv,build.calcsTab.mainOutput
  local groups={}
  local requirements={}
  for _,row in ipairs(env.requirementsTableGems) do
   if row.sourceGem then requirements[#requirements+1]=row.sourceGem.skillId end
  end
  for _,group in ipairs(build.skillsTab.socketGroupList) do
   local gem=group.gemList[1]
   if gem and gem.skillId then
    local effects={}
    for _,skill in ipairs(env.player.activeSkillList) do
     if skill.socketGroup==group then effects[#effects+1]=skill.activeEffect.level end
    end
    groups[#groups+1]={skill_id=gem.skillId,level=gem.level,source_level=gem.sourceLevel,
     from_item=gem.fromItem or false,from_tree=gem.fromNode or false,
     generated=group.source ~= nil,
     unresolved=gem.companionGrantLevelUnresolved or false,
     req_level=gem.reqLevel,req_str=gem.reqStr,req_dex=gem.reqDex,req_int=gem.reqInt,
     effect_levels=effects,gems=#group.gemList,enabled=group.enabled}
   end
  end
  steps[#steps+1]={groups=groups,str=out.Str,dex=out.Dex,int=out.Int,
   req_str=out.ReqStr,req_dex=out.ReqDex,req_int=out.ReqInt,
   gem_requirement_count=#env.requirementsTableGems,gem_requirements=requirements}
 end
 snapshot()
 if case.remove_slot then
  build.itemsTab.slots[case.remove_slot]:SetSelItemId(0)
  build.buildFlag=true;runCallback('OnFrame');snapshot()
 end
 if case.new_character_level then
  build.characterLevel=case.new_character_level
  build.buildFlag=true;runCallback('OnFrame');snapshot()
 end
 if case.repeat_calculation then
  build.buildFlag=true;runCallback('OnFrame');snapshot()
 end
 results[#results+1]=steps
end
io.write(json.encode(results))
''')

    def run(cases):
        env = {**os.environ, "LUA_PATH": str(Path(source) / "runtime/lua/?.lua") + ";" + str(Path(source) / "runtime/lua/?/init.lua") + ";;"}
        result = subprocess.run(
            [os.environ.get("POE2_TEST_LUAJIT", "luajit"), str(script)],
            cwd=Path(source) / "src", input=json.dumps({"xml": FIXTURE.read_text(), "cases": cases}),
            text=True, capture_output=True, env=env, timeout=85,
        )
        assert result.returncode == 0, result.stderr[-3000:]
        return json.loads(result.stdout)
    return run


DISCIPLINE = {"slot": "Weapon 2", "raw": "Rarity: RARE\nSynthetic Grant\nStoic Sceptre\nItem Level: 80\nImplicits: 1\nGrants Skill: Level 19 Discipline"}
ATTRIBUTES = {"slot": "Ring 1", "raw": "Rarity: RARE\nSynthetic Attributes\nIron Ring\n+83 to Strength\n+100 to Intelligence"}
HIGH_ATTRIBUTES = {"slot": "Ring 1", "raw": "Rarity: RARE\nSynthetic Attributes\nIron Ring\n+500 to all Attributes"}
VERTEX = {"slot": "Helmet", "raw": "Rarity: UNIQUE\nThe Vertex\nTribal Mask\nEquipment has no Attribute Requirements"}


def group(step, *, from_item=False, from_tree=False):
    return next(row for row in step["groups"] if row["from_item"] == from_item and row["from_tree"] == from_tree)


def test_item_grant_uses_attribute_limited_level_and_recalculates(granted_levels):
    steps, = granted_levels([{"items": [DISCIPLINE, ATTRIBUTES], "remove_slot": "Ring 1", "repeat_calculation": True}])
    initial, lower, repeated = steps
    assert (initial["str"], initial["int"]) == (98, 107)
    skill = group(initial, from_item=True)
    assert (skill["source_level"], skill["level"]) == (19, 18)
    assert skill["effect_levels"] == [18]
    lower_skill = group(lower, from_item=True)
    assert lower_skill["source_level"] == 19
    assert lower_skill["level"] < 18
    assert lower_skill["effect_levels"] == [lower_skill["level"]]
    assert group(repeated, from_item=True) == lower_skill
    assert lower_skill["skill_id"] not in lower["gem_requirements"]


def test_item_grant_cap_and_character_level_are_both_respected(granted_levels):
    steps, = granted_levels([{"items": [DISCIPLINE, HIGH_ATTRIBUTES], "new_character_level": 30}])
    assert group(steps[0], from_item=True)["level"] == 19
    scaled = group(steps[1], from_item=True)
    assert scaled["level"] < 19
    assert scaled["req_level"] <= 30
    assert scaled["effect_levels"] == [scaled["level"]]


def test_tree_grant_scales_by_character_level_without_attribute_gating(granted_levels):
    steps, = granted_levels([{"tree": True, "character_level": 94, "new_character_level": 30}])
    high = group(steps[0], from_tree=True)
    low = group(steps[1], from_tree=True)
    assert high["level"] == 20
    assert high["effect_levels"] == [20]
    assert low["level"] < 20
    assert low["req_level"] <= 30
    assert high["skill_id"] not in steps[0]["gem_requirements"]
    assert low["skill_id"] not in steps[1]["gem_requirements"]


def test_vertex_equipment_exemption_does_not_remove_gem_requirements(granted_levels):
    baseline, vertex = granted_levels([
        {"items": [DISCIPLINE], "gem": "Fireball 20/0  1"},
        {"items": [DISCIPLINE, VERTEX], "gem": "Fireball 20/0  1"},
    ])
    normal, exempt = baseline[0], vertex[0]
    assert group(normal)["level"] == group(exempt)["level"] == 20
    assert group(exempt, from_item=True)["level"] == group(normal, from_item=True)["level"]
    assert exempt["gem_requirement_count"] > 0
    assert exempt["req_int"] > exempt["int"]


def test_supported_imported_item_only_mirror_uses_current_source_level(granted_levels):
    steps, = granted_levels([{
        "items": [DISCIPLINE, ATTRIBUTES], "gem": "Discipline 19/0  1",
        "support": "SupportClarityPlayer", "remove_slot": "Ring 1",
    }])
    for step in steps:
        grants = [row for row in step["groups"] if row["skill_id"] == "DisciplinePlayer"]
        assert len(grants) == 2
        assert len({row["level"] for row in grants}) == 1
        assert all(row["source_level"] == 19 and row["from_item"] for row in grants)
        explicit = next(row for row in grants if not row["generated"])
        assert explicit["gems"] == 2
        assert explicit["effect_levels"] == [explicit["level"]]
        assert "DisciplinePlayer" not in step["gem_requirements"]


def test_imported_grant_without_an_active_source_is_explicitly_unresolved(granted_levels):
    missing, inactive = granted_levels([
        {"gem": "Discipline 19/0  1"},
        {"items": [{**DISCIPLINE, "slot": "Weapon 2 Swap"}], "gem": "Discipline 19/0  1"},
    ])
    for steps in (missing, inactive):
        explicit = next(row for row in steps[0]["groups"] if row["skill_id"] == "DisciplinePlayer" and not row["generated"])
        assert explicit["level"] == 19
        assert explicit["unresolved"] is True
        assert explicit["from_item"] is False


def test_tree_grant_mirror_with_legacy_equipment_slot_resolves(granted_levels):
    steps, = granted_levels([{
        "tree": True, "character_level": 94, "gem": "Wild Protector 20/0  1",
        "gem_slot": "Weapon 1",
    }])
    grants = [row for row in steps[0]["groups"] if row["skill_id"] == "WildProtectorPlayer"]
    assert len(grants) == 2
    assert all(row["level"] == 20 and row["from_tree"] for row in grants)
    assert all(row["unresolved"] is False for row in grants)
    assert "WildProtectorPlayer" not in steps[0]["gem_requirements"]
