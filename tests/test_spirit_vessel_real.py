"""Real Lua tests of verified Spirit Vessel Life, using synthetic builds only."""
import json
import os
from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET

import pytest

FIXTURE = Path(__file__).parent / 'fixtures/engine_synthetic.xml'


@pytest.fixture
def calculate_vessel(tmp_path):
    location = os.environ.get('POE2_TEST_ENGINE_DIR')
    if not location:
        pytest.skip('Set POE2_TEST_ENGINE_DIR for real Lua integration')
    engine = Path(location)
    script = tmp_path / 'spirit_vessel_probe.lua'
    script.write_text('''print = function() end
local json = require('dkjson')
local input = assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
assert(not __mainObject__.promptMsg, __mainObject__.promptMsg)
loadBuildFromXML(input.xml, '')
assert(not __mainObject__.promptMsg)
local env, output = build.calcsTab.mainEnv, build.calcsTab.mainOutput
local base = {}
for _, vessel in ipairs(env.player.companionSpiritVesselLifeList or {}) do
 base[#base + 1] = math.floor(env.data.monsterAllyLifeTable[vessel.level] * 2.1)
end
io.write(json.encode({vessels=env.player.companionSpiritVesselLifeList, base=base,
life=output.Life, dps=output.CombinedDPS, minion_dps=output.Minion and output.Minion.CombinedDPS,
companion_life=output.TotalCompanionLife, main_skill=env.player.mainSkill.activeEffect.grantedEffect.id}))
''')

    def calculate(root):
        env = dict(os.environ)
        env['LUA_PATH'] = str(engine / 'runtime/lua/?.lua') + ';' + str(engine / 'runtime/lua/?/init.lua') + ';;'
        result = subprocess.run([os.environ.get('POE2_TEST_LUAJIT', 'luajit'), str(script)],
                                cwd=engine / 'src', env=env, capture_output=True,
                                input=json.dumps({'xml': ET.tostring(root, encoding='unicode')}),
                                text=True, timeout=90)
        assert result.returncode == 0, result.stderr[-2000:]
        return json.loads(result.stdout)
    return calculate


def synthetic():
    root = ET.fromstring(FIXTURE.read_bytes())
    group = ET.SubElement(root.find('./Skills/SkillSet'), 'Skill', {
        'enabled': 'true', 'mainActiveSkill': '1', 'includeInFullDPS': 'false'})
    gem(group, 'Spark', 'SparkPlayer')
    return root


def gem(group, name, skill_id, *, level=1, quality=0, enabled=True):
    return ET.SubElement(group, 'Gem', {'nameSpec': name, 'skillId': skill_id,
        'level': str(level), 'quality': str(quality), 'enabled': str(enabled).lower()})


def vessel(root, *, level=1, quality=0, enabled=True):
    group = ET.SubElement(root.find('./Skills/SkillSet'), 'Skill', {
        'enabled': str(enabled).lower(), 'mainActiveSkill': '1', 'includeInFullDPS': 'false'})
    gem(group, 'Spirit Vessel', 'SpiritVesselPlayer', level=level, quality=quality)
    return group


def modifiers(root, lines):
    item = ET.SubElement(root.find('Items'), 'Item', {'id': '2'})
    item.text = 'Rarity: Rare\nSynthetic Spirit Vessel Test\nIron Ring\nItem Level: 80\n' + '\n'.join(lines)
    itemset = root.find('./Items/ItemSet')
    slot = next((s for s in itemset.findall('Slot') if s.get('name') == 'Ring 1'), None)
    if slot is None:
        slot = ET.SubElement(itemset, 'Slot', {'name': 'Ring 1'})
    slot.set('itemId', '2')


@pytest.mark.parametrize('level', [1, 20, 40])
def test_real_vessel_exact_base_life_and_level_without_attack(calculate_vessel, level):
    root = synthetic()
    baseline = calculate_vessel(root)
    vessel(root, level=level)
    result = calculate_vessel(root)
    row = result['vessels'][0]
    assert row['level'] == 2 * level
    assert row['life'] == result['base'][0]
    assert row['minion_id'] == 'Metadata/Monsters/Companions/SpiritVessel'
    assert result['main_skill'] == baseline['main_skill']
    assert result['life'] == baseline['life']
    assert result['dps'] == baseline['dps']
    assert 'minion_dps' not in result


def test_real_vessel_quality_and_minion_life_are_applied(calculate_vessel):
    root = synthetic()
    vessel(root, level=20, quality=20)
    modifiers(root, ['Minions have 30% increased maximum Life', 'Offerings have 100% increased Maximum Life'])
    result = calculate_vessel(root)
    assert result['vessels'][0]['life'] == pytest.approx(result['base'][0] * 1.3 * 1.2, abs=1)


def test_real_vessel_life_contributes_to_companion_redirect_pool(calculate_vessel):
    root = synthetic()
    vessel(root, level=20)
    modifiers(root, ["15% of Damage from Hits is taken from your damageable Companion's Life before you"])
    result = calculate_vessel(root)
    assert result['companion_life'] == result['vessels'][0]['life']


def test_real_vessel_distinct_eligible_socketed_skill_bonus(calculate_vessel):
    root = synthetic()
    group = vessel(root, level=20)
    gem(group, 'Furious Slam', 'FuriousSlamPlayer')
    gem(group, 'Furious Slam', 'FuriousSlamPlayer')
    gem(group, 'Oil Barrage', 'OilBarragePlayer')
    gem(group, 'Spark', 'SparkPlayer')
    result = calculate_vessel(root)
    assert result['vessels'][0]['socketed_skill_count'] == 2
    assert result['vessels'][0]['damage_more_percent'] == 40


def test_real_disabled_vessel_does_not_enter_life_pool(calculate_vessel):
    root = synthetic()
    vessel(root, enabled=False)
    result = calculate_vessel(root)
    assert not result['vessels']


def test_real_undamageable_vessel_has_no_redirect_pool(calculate_vessel):
    root = synthetic()
    group = vessel(root, level=20)
    gem(group, "Brutus' Brain", 'SupportBrutusBrainPlayer')
    modifiers(root, ["15% of Damage from Hits is taken from your damageable Companion's Life before you"])
    result = calculate_vessel(root)
    assert result['vessels'][0]['damageable'] is False
    assert result['companion_life'] == 0


def test_real_vessel_in_inactive_weapon_set_has_no_life_pool(calculate_vessel):
    root = synthetic()
    group = vessel(root, level=20)
    group.set('set1', 'false')
    group.set('set2', 'true')
    modifiers(root, ["15% of Damage from Hits is taken from your damageable Companion's Life before you"])
    result = calculate_vessel(root)
    assert not result['vessels']
    assert result.get('companion_life', 0) == 0
