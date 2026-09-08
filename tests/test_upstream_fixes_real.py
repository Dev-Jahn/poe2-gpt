"""Numerical and round-trip regressions using synthetic public game objects."""
import json
import os
from pathlib import Path
import subprocess

import pytest

FIXTURE = Path(__file__).parent / "fixtures/engine_synthetic.xml"


def run_lua(tmp_path, body):
    source = os.environ.get("POE2_TEST_ENGINE_DIR")
    if not source:
        pytest.skip("Set POE2_TEST_ENGINE_DIR for real Lua integration")
    source = Path(source)
    script = tmp_path / "upstream-fixes.lua"
    script.write_text('''print=function() end
local json=require('dkjson')
local input=assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
loadBuildFromXML(input.xml,'')
assert(not __mainObject__.promptMsg)
''' + body)
    env = dict(os.environ)
    env["LUA_PATH"] = f"{source}/runtime/lua/?.lua;{source}/runtime/lua/?/init.lua;;"
    result = subprocess.run(
        [os.environ.get("POE2_TEST_LUAJIT", "luajit"), str(script)],
        cwd=source / "src", env=env, capture_output=True, text=True, timeout=100,
        input=json.dumps({"xml": FIXTURE.read_text()}),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_enemy_verb_conditions_use_canonical_actor_state_and_clear_old_cache(tmp_path):
    rows = run_lua(tmp_path, '''
local rows={}
for _, case in ipairs({{"Curse","Cursed"}, {"Mark","Marked"}, {"Electrocute","Electrocuted"}}) do
 local mods, extra=modLib.parseMod("Enemies you "..case[1].." have -11% to Chaos Resistance")
 assert(mods and not extra)
 local db=new("ModDB"):ModDB()
 for _, mod in ipairs(mods) do
  assert(mod.name=="EnemyModifier" and mod.value.mod)
  db:AddMod(mod.value.mod)
 end
 local off=db:Sum("BASE",nil,"ChaosResist")
 db.conditions[case[1]]=true
 local verb=db:Sum("BASE",nil,"ChaosResist")
 db.conditions[case[1]]=nil
 db.conditions[case[2]]=true
 local on=db:Sum("BASE",nil,"ChaosResist")
 db.conditions[case[2]]=nil
 rows[#rows+1]={off=off,verb=verb,on=on,reset=db:Sum("BASE",nil,"ChaosResist")}
end
io.write(json.encode(rows))
''')
    assert rows == [{"off": 0, "verb": 0, "on": -11, "reset": 0}] * 3


def test_socket_and_rune_lines_survive_repeated_item_round_trips_once(tmp_path):
    rows = run_lua(tmp_path, '''
local rows={}
for _, input in ipairs({
 {sockets="S S",runes="Rune: Iron Rune\\nRune: Iron Rune",expected=2},
 {sockets="J J J",runes="",expected=3},
}) do
 local item=new("Item"):Item("Rarity: Rare\\nSynthetic Sockets\\nRazor Quarterstaff\\n--------\\nItem Level: 81\\n--------\\nSockets: "..input.sockets.."\\n"..input.runes)
 local counts={}
 for round=1,4 do
  local raw=item:BuildRaw()
  local socketLines,runeLines=0,0
  for line in raw:gmatch("[^\\n]+") do
   if line:match("^Sockets:") then socketLines=socketLines+1 end
   if line:match("^Rune:") then runeLines=runeLines+1 end
  end
  counts[#counts+1]={sockets=#item.sockets,jewels=item.jewelSocketCount,
   socket_lines=socketLines,rune_lines=runeLines,runes=#item.runes}
  item=new("Item"):Item(raw)
 end
 rows[#rows+1]=counts
end
io.write(json.encode(rows))
''')
    assert rows[0] == [{"sockets": 2, "jewels": 0, "socket_lines": 1,
                        "rune_lines": 2, "runes": 2}] * 4
    assert rows[1] == [{"sockets": 0, "jewels": 3, "socket_lines": 1,
                        "rune_lines": 0, "runes": 0}] * 4


def test_baryanic_radius_changes_real_passive_bonus_and_preserves_unique_jewels(tmp_path):
    row = run_lua(tmp_path, '''
build.spec:SelectClass(build.spec.tree.classNameMap.Sorceress)
for id, ascend in pairs(build.spec.curClass.classes) do
 if ascend.name=="Disciple of Varashta" then build.spec:SelectAscendClass(id) end
end
local spec=build.spec
local socket, outside
local ids={}
for id, node in pairs(spec.nodes) do
 if node.isJewelSocket and node.name=="Jewel Socket" and node.nodesInRadius and node.nodesInRadius[13] then ids[#ids+1]=id end
end
table.sort(ids)
for _, id in ipairs(ids) do
 local node=spec.nodes[id]
 local candidates={}
 for nid,n in pairs(node.nodesInRadius[13]) do
  if not node.nodesInRadius[1][nid] and n.type=="Normal" and not n.isAttribute then candidates[#candidates+1]=nid end
 end
 table.sort(candidates)
 if #candidates>0 then socket=node;outside=spec.nodes[candidates[1]];break end
end
assert(socket and outside)
spec:AllocNode(socket)
spec:AllocNode(outside)
local function item(rarity,base)
 local obj=new("Item"):Item("Rarity: "..rarity.."\\nSynthetic Radius\\n"..base.."\\n--------\\nRadius: Small\\n--------\\nSmall Passive Skills in Radius also grant +7 to Strength")
 build.itemsTab:AddItem(obj,true)
 spec.jewels[socket.id]=obj.id
 build.itemsTab.sockets[socket.id]:SetSelItemId(obj.id)
 return obj
end
local function output()
 build.buildFlag=true
 runCallback("OnFrame")
 local env=build.calcsTab.mainEnv
 local count=0
 for nid,n in pairs(socket.nodesInRadius[13]) do
  if not socket.nodesInRadius[1][nid] and n.type=="Normal" and not n.isAttribute and env.allocNodes[nid] then count=count+1 end
 end
 local includes=false
 for _,rad in ipairs(env.radiusJewelList) do
  if rad.nodeId==socket.id and rad.nodes[outside.id] then includes=true end
 end
 return {strength=env.modDB:Sum("BASE",nil,"Str"),display_strength=env.player.output.Str,
  count=count,includes=includes}
end
local rare=item("RARE","Time-Lost Ruby")
local before=output()
local function simulated(mode)
 local calcs=build.calcsTab.calcs
 local overrides={}
 overrides[mode]={[spec.nodes[36891]]=true}
 local env=calcs.initEnv(build,"CALCULATOR",overrides)
 calcs.perform(env)
 return env.modDB:Sum("BASE",nil,"Str")
end
local addOverride=simulated("addNodes")
assert(not spec.allocNodes[36891])
spec:AllocNode(spec.nodes[36891])
local after=output()
local removeOverride=simulated("removeNodes")
assert(spec.allocNodes[36891])
local ratios={}
for index=1,4 do
 rare.jewelRadiusIndex=index
 local mapped=data.companionJewelRadiusIndex(rare,true)
 ratios[#ratios+1]=data.jewelRadius[mapped].outer/data.jewelRadius[index].outer
end
rare.jewelRadiusIndex=1
local unique=item("UNIQUE","Time-Lost Ruby")
local uniqueOutput=output()
local normal=item("RARE","Ruby")
local normalOutput=output()
item("RARE","Time-Lost Ruby")
local restored=output()
spec:DeallocNode(spec.nodes[36891])
local removed=output()
io.write(json.encode({before=before,after=after,unique=uniqueOutput,normal=normalOutput,
 restored=restored,removed=removed,ratios=ratios,
 add_override=addOverride,remove_override=removeOverride,
 unique_index=data.companionJewelRadiusIndex(unique,true),
 normal_index=data.companionJewelRadiusIndex(normal,true)}))
''')
    assert row["ratios"] == pytest.approx([1.4] * 4)
    assert row["after"]["count"] > 0
    assert not row["before"]["includes"] and row["after"]["includes"]
    assert row["after"]["strength"] - row["before"]["strength"] == 7 * row["after"]["count"]
    assert row["after"]["display_strength"] > row["before"]["display_strength"]
    assert row["add_override"] == row["after"]["strength"]
    assert row["remove_override"] == row["before"]["strength"]
    assert row["unique_index"] == row["normal_index"] == 1
    for key in ("unique", "normal", "removed"):
        assert not row[key]["includes"]
        assert row[key]["strength"] == row["before"]["strength"]
    assert row["restored"]["strength"] == row["after"]["strength"]
