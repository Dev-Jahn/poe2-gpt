"""Synthetic numerical tests for saved per-skill weapon context handling."""
import copy
import json
import os
from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET

import pytest

FIXTURE = Path(__file__).parent / 'fixtures/engine_synthetic.xml'
MODULE = Path(__file__).parents[1] / 'src/poe2_companion/lua/weapon_context.lua'


def synthetic(*, global_set=1, selectors=None):
    root = ET.fromstring(FIXTURE.read_bytes())
    items = root.find('Items')
    itemset = items.find('ItemSet')
    itemset.set('useSecondWeaponSet', str(global_set == 2).lower())
    for number, slot, increase in [(1, 'Weapon 1', 0), (2, 'Weapon 1 Swap', 100)]:
        item = ET.SubElement(items, 'Item', {'id': str(number)})
        item.text = f'Rarity: Rare\nSynthetic Weapon\nWrapped Quarterstaff\nItem Level: 80\n{increase}% increased Physical Damage'
        next(s for s in itemset.findall('Slot') if s.get('name') == slot).set('itemId', str(number))
    group = ET.SubElement(root.find('./Skills/SkillSet'), 'Skill', {
        'enabled': 'true', 'mainActiveSkill': '1', **(selectors or {}),
    })
    ET.SubElement(group, 'Gem', {'nameSpec': 'Quarterstaff Strike', 'skillId': 'MeleeQuarterstaffPlayer',
                               'level': '1', 'quality': '0', 'enabled': 'true'})
    return root


def other_group(root, *, enabled=True, set1='true', set2='false', slot=None):
    group = ET.SubElement(root.find('./Skills/SkillSet'), 'Skill', {
        'enabled': str(enabled).lower(), 'set1': set1, 'set2': set2, 'mainActiveSkill': '1',
    })
    if slot:
        group.set('slot', slot)
    ET.SubElement(group, 'Gem', {'nameSpec': 'Leap Slam', 'skillId': 'LeapSlamPlayer',
                               'level': '1', 'quality': '0', 'enabled': 'true'})
    return group


def calculate(tmp_path, cases):
    source = os.environ.get('POE2_TEST_ENGINE_DIR')
    if not source:
        pytest.skip('Set POE2_TEST_ENGINE_DIR for real Lua integration')
    source = Path(source)
    script = tmp_path / 'weapon-context.lua'
    script.write_text('''print=function() end
local json=require('dkjson')
local input=assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
local context=dofile(input.module)
local results={}
for _, xml in ipairs(input.cases) do
 if GlobalCache and GlobalCache.cachedData then wipeGlobalCache() end
 loadBuildFromXML(xml,'')
 assert(not __mainObject__.promptMsg)
 local group=build.skillsTab.socketGroupList[build.mainSocketGroup]
 local before=build.calcsTab.mainOutput.CombinedDPS
 local main=build.mainSocketGroup
 local changed=context.activate(build)
 if changed then build.buildFlag=true;runCallback('OnFrame') end
 local output=build.calcsTab.mainOutput
 local active=build.calcsTab.mainEnv.player.mainSkill
 results[#results+1]={changed=changed, before=before, dps=output.CombinedDPS,
  active_weapon_set=build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1,
  issues=context.inspect(build), selectors={group.set1,group.set2},
  main_unchanged=main==build.mainSocketGroup,
  active_scope=context.isActive(build,active)}
end
io.write(json.encode(results))
''')
    env = dict(os.environ)
    env['LUA_PATH'] = f'{source}/runtime/lua/?.lua;{source}/runtime/lua/?/init.lua;;'
    snapshots = [ET.tostring(case, encoding='unicode') for case in cases]
    result = subprocess.run(
        [os.environ.get('POE2_TEST_LUAJIT', 'luajit'), str(script)],
        cwd=source / 'src', env=env, capture_output=True, text=True, timeout=80,
        input=json.dumps({'module': str(MODULE), 'cases': snapshots}),
    )
    assert result.returncode == 0, result.stderr
    assert snapshots == [ET.tostring(case, encoding='unicode') for case in cases]
    return json.loads(result.stdout)


def test_exclusive_main_weapon_context_matches_reference_and_replacement_scope(tmp_path):
    legacy = synthetic()
    reference = synthetic(global_set=2)
    selected = synthetic(selectors={'set1': 'false', 'set2': 'true'})
    ignored_replacement = copy.deepcopy(selected)
    ignored_replacement.find('./Items/Item[@id="1"]').text += '\nAdds 100 to 200 Physical Damage'
    used_replacement = copy.deepcopy(selected)
    used_replacement.find('./Items/Item[@id="2"]').text += '\nAdds 100 to 200 Physical Damage'
    old, ref, resolved, ignored, used = calculate(tmp_path, [legacy, reference, selected, ignored_replacement, used_replacement])
    assert resolved['selectors'] == [False, True]
    assert old['active_weapon_set'] == 1 and not old['changed']
    assert resolved['changed'] and resolved['active_weapon_set'] == 2 and resolved['main_unchanged']
    assert resolved['dps'] == pytest.approx(ref['dps'])
    assert resolved['dps'] > old['dps']
    assert ignored['dps'] == pytest.approx(resolved['dps'])
    assert used['dps'] > resolved['dps']
    assert all(not row['issues'] and row['active_scope'] for row in [old, ref, resolved, ignored, used])


def test_mixed_contexts_are_diagnosed_without_enabling_or_discarding_groups(tmp_path):
    mixed = synthetic(selectors={'set1': 'false', 'set2': 'true'})
    other_group(mixed)
    disabled = copy.deepcopy(mixed)
    disabled.find('./Skills/SkillSet').findall('Skill')[1].set('enabled', 'false')
    both = copy.deepcopy(mixed)
    both.find('./Skills/SkillSet').findall('Skill')[1].set('set2', 'true')
    invalid = synthetic(selectors={'set1': 'invalid', 'set2': 'true'})
    neither = synthetic(selectors={'set1': 'false', 'set2': 'false'})
    legacy_conflict = synthetic(selectors={'set1': 'false', 'set2': 'true'})
    group = other_group(legacy_conflict, slot='Weapon 1')
    del group.attrib['set1']
    del group.attrib['set2']
    both_with_legacy_slot = synthetic(selectors={'set1': 'true', 'set2': 'true', 'slot': 'Weapon 1 Swap'})
    legacy_main = synthetic(selectors={'slot': 'Weapon 1 Swap'})
    rows = calculate(tmp_path, [mixed, disabled, both, invalid, neither, legacy_conflict, both_with_legacy_slot, legacy_main])
    for index in [0, 3, 4, 5, 6]:
        assert not rows[index]['changed'] and rows[index]['active_weapon_set'] == 1
        assert rows[index]['issues'] == [{'code': 'unsupported_weapon_context', 'skill_id': 'MeleeQuarterstaffPlayer'}]
    for index in [1, 2, 7]:
        assert rows[index]['changed'] and rows[index]['active_weapon_set'] == 2
        assert not rows[index]['issues']
