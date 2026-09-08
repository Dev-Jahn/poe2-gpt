"""Synthetic headless checks for skill coverage and the reviewed Verglas fix."""
import json
import os
from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET

import pytest

MODULE = Path(__file__).parents[1] / 'src/poe2_companion/lua/skill_coverage.lua'


def run_lua(tmp_path, body):
    source = os.environ.get('POE2_TEST_ENGINE_DIR')
    if not source:
        pytest.skip('Set POE2_TEST_ENGINE_DIR to run real PoE2 LuaJIT integration')
    source = Path(source)
    script = tmp_path / 'coverage-test.lua'
    script.write_text(
        "print=function() end\ndofile('HeadlessWrapper.lua')\n"
        f"local coverage=dofile({json.dumps(str(MODULE))})\n"
        "local function refresh() build.buildFlag=true;runCallback('OnFrame') end\n"
        + body
    )
    env = dict(os.environ)
    env['LUA_PATH'] = f'{source}/runtime/lua/?.lua;{source}/runtime/lua/?/init.lua;;'
    result = subprocess.run(
        [os.environ.get('POE2_TEST_LUAJIT', 'luajit'), str(script)],
        cwd=source / 'src', env=env, capture_output=True, text=True, timeout=80,
    )
    # The script only creates public synthetic inputs. No user build or text
    # fields are loaded; assertion failure output cannot contain private PoB.
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_skill_coverage_tracks_applied_supports_and_ignores_idle_metadata(tmp_path):
    result = run_lua(tmp_path, r'''
build.itemsTab:CreateDisplayItemFromRaw("New Item\nRazor Quarterstaff\nQuality: 0")
build.itemsTab:AddDisplayItem()
build.skillsTab:PasteSocketGroup("Quarterstaff Strike 20/0  1\nVerglas 1/0  1")
refresh()
local effect = build.data.skills.SupportVerglasPlayer
local stat = 'support_crystalshatter_buff_damage_%_gained_as_extra_cold_per_2000_crystal_life'
local function matching()
 local issues={}
 for _, issue in ipairs(coverage.inspect(build)) do
  if issue.skill_id==effect.id and issue.skill_stat_id==stat then issues[#issues+1]=issue end
 end
 return issues
end
assert(#matching()==0) -- reviewed mapping installed
local map=effect.statSets[1].statMap[stat]
effect.statSets[1].statMap[stat]=nil
assert(#matching()==1) -- a canonical gem can contain an unsupported effect
local supported=matching()
build.skillsTab.socketGroupList[1].gemList[2].enabled=false
refresh()
assert(#matching()==0)
build.skillsTab.socketGroupList[1].gemList[2].enabled=true
build.skillsTab.socketGroupList[1].enabled=false
build.skillsTab:PasteSocketGroup("Leap Slam 20/0  1")
build.mainSocketGroup=2
refresh()
assert(#matching()==0) -- an idle group must not poison validation
build.skillsTab:PasteSocketGroup("Tame Beast 1/0  1\nVerglas 1/0  1")
refresh()
assert(#matching()==0) -- an incompatible support was not applied
for _, issue in ipairs(coverage.inspect(build)) do
 assert(issue.skill_stat_id~='skill_can_see_monster_categories')
end
effect.statSets[1].statMap[stat]=map

-- Falling Thunder quality targets its projectile set, not the selected slam.
build.skillsTab:PasteSocketGroup("Falling Thunder 20/20  1")
local falling=build.data.skills.FallingThunderPlayer
local projectileStat='lightning_strike_damage_+%_final_per_power_charge'
local projectileMap=falling.statSets[2].statMap[projectileStat]
falling.statSets[2].statMap[projectileStat]=nil
local gem=build.skillsTab.socketGroupList[4].gemList[1]
gem.statSet={FallingThunderPlayer=1}
refresh()
local function fallingMissing()
 for _, issue in ipairs(coverage.inspect(build)) do
  if issue.skill_id==falling.id and issue.skill_stat_id==projectileStat then return true end
 end
 return false
end
assert(not fallingMissing())
gem.statSet.FallingThunderPlayer=2
refresh()
assert(fallingMissing())
falling.statSets[2].statMap[projectileStat]=projectileMap
io.write(require('dkjson').encode({reported=supported[1], idle_excluded=true, selected_stat_set_only=true}))
''')
    assert result['reported'] == {
        'code': 'unsupported_skill_stat',
        'skill_id': 'SupportVerglasPlayer',
        'skill_stat_id': 'support_crystalshatter_buff_damage_%_gained_as_extra_cold_per_2000_crystal_life',
    }
    assert result['idle_excluded']
    assert result['selected_stat_set_only']


def test_verglas_condition_scope_breakpoints_and_cross_skill_cache(tmp_path):
    result = run_lua(tmp_path, r'''
build.itemsTab:CreateDisplayItemFromRaw("New Item\nRazor Quarterstaff\nQuality: 0")
build.itemsTab:AddDisplayItem()
build.skillsTab:PasteSocketGroup("Quarterstaff Strike 20/0  1\nVerglas 1/0  1")
build.skillsTab:PasteSocketGroup("Leap Slam 20/0  1")
build.skillsTab:PasteSocketGroup("Frost Wall 20/20  1")
build.skillsTab.socketGroupList[1].includeInFullDPS=true
refresh()
local function groupSkill(index)
 for _, skill in ipairs(build.calcsTab.mainEnv.player.activeSkillList) do
  if skill.socketGroup==build.skillsTab.socketGroupList[index] then return skill end
 end
end
local function gain(index)
 local skill=assert(groupSkill(index))
 return skill.skillModList:Sum('BASE',skill.skillCfg,'DamageGainAsCold')
end
local baseline=build.calcsTab.mainOutput.FullDPS
assert(baseline>0 and gain(1)==0)
build.configTab.input.conditionDestroyedIceCrystalPast6Seconds=true
build.configTab:BuildModList();refresh()
local crystal=assert(groupSkill(3))
local life=crystal.skillModList:Sum('BASE',crystal.skillCfg,'IceCrystalLifeBase') * calcLib.mod(crystal.skillModList,crystal.skillCfg,'IceCrystalLife')
assert(life>0 and build.calcsTab.mainEnv.player.destroyedIceCrystalLife==life)
assert(gain(1)==math.floor(life/2000) and gain(2)==0)
local automatic=build.calcsTab.mainOutput.FullDPS
assert(automatic>baseline)
local values={}
for _, override in ipairs({1999,2000,3999,4000,271990}) do
 build.configTab.input.multiplierDestroyedIceCrystalLife=override
 build.configTab:BuildModList();refresh()
 assert(gain(1)==math.floor(override/2000) and gain(2)==0)
 values[#values+1]=gain(1)
end
build.configTab.input.multiplierDestroyedIceCrystalLife=nil
build.configTab:BuildModList();refresh()
assert(math.abs(build.calcsTab.mainOutput.FullDPS-automatic)<automatic*0.001)
local calcFunc, baseOutput=LoadModule('Modules/Calcs').getMiscCalculator(build)
build.skillsTab:PasteSocketGroup("Frost Wall 20/20  1\nGlacier 1/0  1")
local ambiguous=calcFunc(nil,true,{fullDPSOnly=true})
assert(math.abs(ambiguous.FullDPS-baseline)<baseline*0.001)
refresh()
assert(build.calcsTab.mainEnv.player.destroyedIceCrystalLifeAmbiguous)
assert(gain(1)==0)
local function missingAssumption()
 for _, issue in ipairs(coverage.inspect(build)) do
  if issue.code=='missing_combat_assumption' and issue.skill_id=='SupportVerglasPlayer' then return true end
 end
 return false
end
assert(missingAssumption())
-- An explicit saved source resolves ambiguity without assuming the larger one.
build.configTab.input.multiplierDestroyedIceCrystalLife=3999
build.configTab:BuildModList();refresh()
assert(gain(1)==1 and not missingAssumption())
build.configTab.input.multiplierDestroyedIceCrystalLife=nil
build.configTab:BuildModList()
build.skillsTab.socketGroupList[3].enabled=false
refresh()
assert(not missingAssumption() and build.calcsTab.mainOutput.FullDPS>automatic)
-- Changing a different skill's crystal Life invalidates the Full DPS cache.
calcFunc, baseOutput=LoadModule('Modules/Calcs').getMiscCalculator(build)
build.skillsTab.socketGroupList[4].gemList[2].enabled=false
local smaller=calcFunc(nil,true,{fullDPSOnly=true})
assert(smaller.FullDPS<baseOutput.FullDPS and math.abs(smaller.FullDPS-automatic)<automatic*0.001)
build.skillsTab.socketGroupList[3].enabled=true
refresh()
assert(not build.calcsTab.mainEnv.player.destroyedIceCrystalLifeAmbiguous and not missingAssumption())
assert(gain(1)==math.floor(life/2000)) -- equal-Life sources agree
build.skillsTab.socketGroupList[3].enabled=false
build.skillsTab.socketGroupList[4].enabled=false
refresh()
assert(gain(1)==0 and missingAssumption()) -- no source is not a proven zero buff
build.configTab.input.conditionDestroyedIceCrystalPast6Seconds=false
build.configTab:BuildModList();refresh()
assert(gain(1)==0 and not missingAssumption() and math.abs(build.calcsTab.mainOutput.FullDPS-baseline)<baseline*0.001)
io.write(require('dkjson').encode({breakpoints=values, default_off=true, supported_skill_only=true, cache_invalidated=true, ambiguous_sources_excluded=true}))
''')
    assert result['breakpoints'] == [0, 1, 1, 2, 135]
    assert result['default_off'] and result['supported_skill_only'] and result['cache_invalidated']
    assert result['ambiguous_sources_excluded']


async def test_granted_source_issue_is_public_indeterminate_and_excludes_disabled_groups(tmp_path):
    source = os.environ.get('POE2_TEST_ENGINE_DIR')
    if not source:
        pytest.skip('Set POE2_TEST_ENGINE_DIR for real Lua integration')
    import base64
    import hashlib
    import zlib
    from poe2_companion.engine_worker import PrivateEngine
    from poe2_companion.engine_protocol import WorkerRequest

    root = ET.fromstring((Path(__file__).parent / 'fixtures/engine_synthetic.xml').read_bytes())
    groups = root.find('./Skills/SkillSet')
    for name, skill_id, level in [('Fireball', 'FireballPlayer', '1'), ('Discipline', 'DisciplinePlayer', '19')]:
        group = ET.SubElement(groups, 'Skill', {'enabled': 'true', 'mainActiveSkill': '1'})
        ET.SubElement(group, 'Gem', {'nameSpec': name, 'skillId': skill_id, 'level': level, 'quality': '0', 'enabled': 'true'})
    item = ET.SubElement(root.find('Items'), 'Item', {'id': '1'})
    item.text = 'Rarity: Rare\nSynthetic Attribute Ring\nIron Ring\n+500 to all Attributes'
    next(s for s in root.findall('./Items/ItemSet/Slot') if s.get('name') == 'Ring 1').set('itemId', '1')
    build_id = 'bld_' + '9' * 32
    path = tmp_path / (build_id + '.pob')
    engine = PrivateEngine(tmp_path, Path(source), os.environ.get('POE2_TEST_LUAJIT', 'luajit'))

    def save():
        path.write_bytes(base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))))

    save()
    original = hashlib.sha256(path.read_bytes()).digest()
    active = (await engine.calculate(WorkerRequest(build_id=build_id))).baseline
    assert active.validation == 'indeterminate'
    assert any(issue.code == 'granted_skill_source_unresolved' and issue.skill_id == 'DisciplinePlayer' for issue in active.issues)
    assert not any(issue.code in {'attribute_requirement', 'gem_level_requirement'} for issue in active.issues)
    assert hashlib.sha256(path.read_bytes()).digest() == original
    groups.findall('Skill')[1].set('enabled', 'false')
    save()
    disabled = (await engine.calculate(WorkerRequest(build_id=build_id))).baseline
    assert disabled.validation == 'pass'
    assert not any(issue.code == 'granted_skill_source_unresolved' for issue in disabled.issues)


def test_granted_source_diagnostic_sorts_with_stat_diagnostics_for_same_skill(tmp_path):
    result = run_lua(tmp_path, r'''
build.skillsTab:PasteSocketGroup("Discipline 19/0  1")
refresh()
local instance=build.calcsTab.mainEnv.player.mainSkill.activeEffect
local effect=instance.grantedEffect
assert(effect.id=='DisciplinePlayer' and effect.fromItem)
assert(instance.srcInstance.companionGrantLevelUnresolved)
local set=instance.statSet.statSet
local stats=calcLib.buildSkillInstanceStats(instance,effect,set,false)
local removed,localMap,globalMap
for stat,value in pairs(stats) do
 if value~=0 and #build.data.describeStats({[stat]=value},set.statDescriptionScope)>0 then
  removed=stat;localMap=set.statMap[stat];globalMap=build.data.skillStatMap[stat]
  set.statMap[stat]=nil;build.data.skillStatMap[stat]=nil
  break
 end
end
assert(removed)
local unresolved,unsupported=false,false
for _,issue in ipairs(coverage.inspect(build)) do
 if issue.skill_id==effect.id then
  if issue.code=='granted_skill_source_unresolved' then unresolved=true;assert(issue.skill_stat_id==nil) end
  if issue.code=='unsupported_skill_stat' and issue.skill_stat_id==removed then unsupported=true end
 end
end
set.statMap[removed]=localMap;build.data.skillStatMap[removed]=globalMap
assert(unresolved and unsupported)
io.write(require('dkjson').encode({unresolved=unresolved,unsupported=unsupported}))
''')
    assert result == {'unresolved': True, 'unsupported': True}
