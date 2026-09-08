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
assert(not __mainObject__.promptMsg, tostring(__mainObject__.promptMsg))
local vesselModule = dofile(input.projection)
if input.select then
 local selected = vesselModule.configure(build, input.select)
 if not selected then io.write(json.encode({selection_failed=true})); return end
 wipeGlobalCache()
 build.buildFlag = true
 runCallback('OnFrame')
 assert(not __mainObject__.promptMsg, tostring(__mainObject__.promptMsg))
end
local env, output = build.calcsTab.mainEnv, build.calcsTab.mainOutput
local projection = vesselModule.inspect(build, env)
local base = {}
local copied = {}
for _, owner in ipairs(env.player.activeSkillList) do
 if owner.activeEffect.grantedEffect.id == 'SpiritVesselPlayer' and owner.minion then
  for _, skill in ipairs(owner.minion.activeSkillList) do
   copied[#copied + 1] = {id=skill.activeEffect.grantedEffect.id, level=skill.activeEffect.level,
    quality=skill.activeEffect.quality, minion=skill.actor.type, disabled=skill.disableReason ~= nil}
  end
 end
end
for _, vessel in ipairs(env.player.companionSpiritVesselLifeList or {}) do
 base[#base + 1] = math.floor(env.data.monsterAllyLifeTable[vessel.level] * 2.1)
end
io.write(json.encode({vessels=env.player.companionSpiritVesselLifeList, base=base, copied=copied, projection=projection,
life=output.Life, dps=output.CombinedDPS, minion_dps=output.Minion and output.Minion.CombinedDPS,
minion=output.Minion and {dps=output.Minion.TotalDPS, average=output.Minion.AverageDamage,
 projectile_speed=output.Minion.ProjectileSpeedMod,
 speed=output.Minion.Speed, life=output.Minion.Life, armour=output.Minion.Armour,
 fire_resist=output.Minion.FireResist, hit_chance=output.Minion.HitChance},
minion_skill=env.minion and env.minion.mainSkill.activeEffect.grantedEffect.id,
companion_life=output.TotalCompanionLife, main_skill=env.player.mainSkill.activeEffect.grantedEffect.id}))
''')

    def calculate(root, select=None):
        env = dict(os.environ)
        env['LUA_PATH'] = str(engine / 'runtime/lua/?.lua') + ';' + str(engine / 'runtime/lua/?/init.lua') + ';;'
        result = subprocess.run([os.environ.get('POE2_TEST_LUAJIT', 'luajit'), str(script)],
                                cwd=engine / 'src', env=env, capture_output=True,
                                input=json.dumps({'xml': ET.tostring(root, encoding='unicode'), 'select': select,
                                    'projection': str(Path(__file__).parents[1] / 'src/poe2_companion/lua/spirit_vessel.lua')}),
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


def vessel_attack(*, skill_id='FuriousSlamPlayer', skill_name='Furious Slam', skill_level=20):
    root = synthetic()
    root.find('Build').set('mainSocketGroup', '2')
    # Zero enemy Armour isolates damage multipliers from nonlinear mitigation.
    ET.SubElement(root.find('./Config/ConfigSet'), 'Input', {'name': 'enemyArmour', 'number': '0'})
    group = vessel(root, level=20)
    gem(group, skill_name, skill_id, level=skill_level)
    return root, group


def test_real_vessel_copies_socketed_attack_into_minion_actor(calculate_vessel):
    root, _ = vessel_attack()
    result = calculate_vessel(root)
    assert result['minion_dps'] > 0
    assert result['copied'] == [{'id': 'FuriousSlamPlayer', 'level': 20, 'quality': 0,
                                'minion': 'Metadata/Monsters/Companions/SpiritVessel', 'disabled': False}]
    assert result['minion']['life'] == result['vessels'][0]['life']
    assert result['minion']['armour'] > 0
    assert result['minion']['hit_chance'] == 100


def test_real_vessel_minion_damage_and_attack_speed_do_not_modify_player(calculate_vessel):
    root, _ = vessel_attack()
    baseline = calculate_vessel(root)
    modifiers(root, ['Minions deal 100% increased Damage', 'Minions have 25% increased Attack Speed'])
    result = calculate_vessel(root)
    # The native hit pipeline rounds integer damage before critical weighting.
    assert result['minion']['average'] == pytest.approx(baseline['minion']['average'] * 2, abs=3)
    assert result['minion']['speed'] == pytest.approx(baseline['minion']['speed'] * 1.5 / 1.25)
    assert result['dps'] == baseline['dps']
    assert result['life'] == baseline['life']


def test_real_vessel_ignores_player_damage_and_attack_speed(calculate_vessel):
    root, _ = vessel_attack()
    baseline = calculate_vessel(root)
    modifiers(root, ['100% increased Attack Damage', '50% increased Attack Speed', 'Adds 100 to 100 Physical Damage to Attacks'])
    result = calculate_vessel(root)
    assert result['minion_dps'] == baseline['minion_dps']


def test_real_vessel_copied_level_and_distinct_bonus_are_applied_once(calculate_vessel):
    root, group = vessel_attack(skill_level=1)
    baseline = calculate_vessel(root)
    group.findall('Gem')[1].set('level', '20')
    upgraded = calculate_vessel(root)
    assert upgraded['minion']['average'] == pytest.approx(baseline['minion']['average'] * 2.54 / .7, abs=3)
    gem(group, 'Furious Slam', 'FuriousSlamPlayer', level=20)
    assert calculate_vessel(root)['minion_dps'] == upgraded['minion_dps']
    gem(group, 'Oil Barrage', 'OilBarragePlayer', level=20)
    second = calculate_vessel(root)
    assert len(second['copied']) == 2
    assert second['minion']['average'] == pytest.approx(upgraded['minion']['average'] * 1.4 / 1.2, abs=3)


def test_real_vessel_native_life_redirect_is_not_double_counted(calculate_vessel):
    root, _ = vessel_attack()
    modifiers(root, ["15% of Damage from Hits is taken from your damageable Companion's Life before you"])
    result = calculate_vessel(root)
    assert result['companion_life'] == result['vessels'][0]['life']
    assert result['companion_life'] == result['minion']['life']


def test_real_vessel_copies_only_enabled_compatible_attacks(calculate_vessel):
    root, group = vessel_attack()
    baseline = calculate_vessel(root)
    gem(group, 'Oil Barrage', 'OilBarragePlayer', enabled=False)
    gem(group, 'Spark', 'SparkPlayer', level=20)
    gem(group, 'Fist of War I', 'FistOfWarSupportPlayer')
    result = calculate_vessel(root)
    assert result['copied'] == baseline['copied']
    assert result['minion_dps'] == baseline['minion_dps']


def test_real_vessel_minion_support_and_resistance_apply(calculate_vessel):
    root, group = vessel_attack()
    baseline = calculate_vessel(root)
    gem(group, 'Brutality I', 'SupportBrutalityPlayer')
    modifiers(root, ['Minions have +20% to all Elemental Resistances'])
    result = calculate_vessel(root)
    assert result['minion']['average'] > baseline['minion']['average']
    assert result['minion']['fire_resist'] == baseline['minion']['fire_resist'] + 20


def test_real_vessel_saved_copied_skill_selection(calculate_vessel):
    root, group = vessel_attack()
    gem(group, 'Oil Barrage', 'OilBarragePlayer', level=10)
    group.findall('Gem')[0].set('skillMinionSkill', '2')
    result = calculate_vessel(root)
    assert len(result['copied']) == 2
    assert result['minion_dps'] > 0
    assert result['minion_skill'] == 'OilBarragePlayer'
    assert result['projection'][0]['skill_id'] == 'OilBarragePlayer'
    assert result['projection'][0]['status'] == 'partial'
    assert result['projection'][0]['required_inputs'] == ['companion_skill_rotation']


def test_real_vessel_projection_uses_cached_actor_when_another_skill_is_main(calculate_vessel):
    root, _ = vessel_attack()
    baseline = calculate_vessel(root)
    root.find('Build').set('mainSocketGroup', '1')
    result = calculate_vessel(root)
    assert 'minion' not in result
    assert result['projection'] == baseline['projection']


@pytest.mark.parametrize('selected', ['OilBarragePlayer', 'WyvernDevourPlayer'])
def test_real_vessel_guest_copied_wyvern_skills_and_supports(calculate_vessel, selected):
    root, group = vessel_attack(skill_id='OilBarragePlayer', skill_name='Oil Barrage', skill_level=15)
    group.findall('Gem')[0].set('level', '26')
    gem(group, 'Devour', 'WyvernDevourPlayer', level=15)
    baseline = calculate_vessel(root, select=selected)
    gem(group, 'Rapid Attacks II', 'SupportRapidAttacksPlayerTwo')
    gem(group, 'Loyalty', 'SupportLoyaltyPlayer')
    result = calculate_vessel(root, select=selected)
    assert result['minion_skill'] == selected
    assert result['vessels'][0]['level'] == 52
    assert {r['id']: r['level'] for r in result['copied']} == {'OilBarragePlayer': 15, 'WyvernDevourPlayer': 15}
    assert result['minion']['speed'] == pytest.approx(baseline['minion']['speed'] * 1.5 / 1.25)
    assert result['minion']['life'] == pytest.approx(baseline['minion']['life'] * .7, abs=1)
    assert result['minion']['average'] == baseline['minion']['average']
    assert result['minion_dps'] > 0
    assert result['vessels'][0]['damage_more_percent'] == 40


def test_real_vessel_selector_rejects_unavailable_or_noncopy_skill(calculate_vessel):
    root, _ = vessel_attack()
    assert calculate_vessel(root, select='OilBarragePlayer') == {'selection_failed': True}
    assert calculate_vessel(root, select='SparkPlayer') == {'selection_failed': True}


def test_real_vessel_projectile_support_uses_copied_skill_types(calculate_vessel):
    root, group = vessel_attack(skill_id='OilBarragePlayer', skill_name='Oil Barrage', skill_level=15)
    baseline = calculate_vessel(root)
    gem(group, 'Projectile Deceleration I', 'SupportProjectileDecelerationPlayer')
    result = calculate_vessel(root)
    assert result['minion']['projectile_speed'] == pytest.approx(baseline['minion']['projectile_speed'] * .75)
