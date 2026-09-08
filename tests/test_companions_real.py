"""Exact Offering life and Companion-limit tests using the real Lua engine.

All inputs are synthetic. No downloaded or user-owned build enters these tests.
"""
import json
import os
from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET

import pytest

FIXTURE = Path(__file__).parent / 'fixtures/engine_synthetic.xml'
MODULE = Path(__file__).parents[1] / 'src/poe2_companion/lua/companions.lua'


@pytest.fixture
def calculate_companions(tmp_path):
    engine = os.environ.get('POE2_TEST_ENGINE_DIR')
    if not engine:
        pytest.skip('Set POE2_TEST_ENGINE_DIR for real Lua integration')
    engine = Path(engine)
    script = tmp_path / 'companion_probe.lua'
    script.write_text('''print = function() end
local json = require('dkjson')
local input = assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
assert(not __mainObject__.promptMsg, __mainObject__.promptMsg)
local module = dofile(input.module)
module.register()
loadBuildFromXML(input.xml, '')
for _, id in ipairs(input.tree_nodes or {}) do
 local node = assert(build.spec.nodes[id])
 node.alloc = true; node.isGrantedPassive = nil; node.isFreeAllocate = nil
 build.spec.allocNodes[id] = node
end
if #(input.tree_nodes or {}) > 0 then
 build.buildFlag = true; runCallback('OnFrame')
end
assert(not __mainObject__.promptMsg)
local env, output = build.calcsTab.mainEnv, build.calcsTab.mainOutput
local mechanics, issues = module.inspect(build, env, output)
local mirrors = 0
local companionSkills = {}
local calcs = require('Modules.CalcBase')
for _, skill in ipairs(env.player.activeSkillList) do
 if skill.skillTypes[SkillType.CreatesCompanion] then
  local mirrored = calcs.companionIsGrantMirror(env, skill)
  if mirrored then mirrors = mirrors + 1 end
  companionSkills[#companionSkills + 1] = {id=skill.activeEffect.grantedEffect.id,
   base_level=skill.activeEffect.srcInstance.level, level=skill.activeEffect.level,
   generated=skill.socketGroup.source ~= nil, mirrored=mirrored}
 end
end
local parsed = {}
for _, text in ipairs(input.parse or {}) do
 local mods, extra = modLib.parseMod(text)
 parsed[#parsed + 1] = mods ~= nil and not extra
end
io.write(json.encode({mechanics=mechanics, issues=issues, parsed=parsed,
life=output.Life, dps=output.CombinedDPS, spirit=output.SpiritUnreserved,
offering_life=env.player.companionOfferingLifeList,
minion_life=output.Minion and output.Minion.Life,
minion_speed=output.Minion and output.Minion.MovementSpeedMod,
companion_life=env.modDB:Sum('BASE', nil, 'TotalCompanionLife'), wolf_limit=output.WolfLimit,
grant_mirrors=mirrors, companion_skills=companionSkills}))
''')

    def calculate(root, parse=(), *, tree_nodes=()):
        env = dict(os.environ)
        env['LUA_PATH'] = str(engine / 'runtime/lua/?.lua') + ';' + str(engine / 'runtime/lua/?/init.lua') + ';;'
        result = subprocess.run([os.environ.get('POE2_TEST_LUAJIT', 'luajit'), str(script)],
                                cwd=engine / 'src', env=env, capture_output=True,
                                input=json.dumps({'xml': ET.tostring(root, encoding='unicode'), 'module': str(MODULE), 'parse': list(parse), 'tree_nodes': list(tree_nodes)}),
                                text=True, timeout=30)
        assert result.returncode == 0, result.stderr[-2000:]
        return json.loads(result.stdout)
    return calculate


def synthetic():
    root = ET.fromstring(FIXTURE.read_bytes())
    root.find('Build').set('mainSocketGroup', '1')
    return root


def skill(root, name, skill_id, *, level=1, quality=0, enabled=True):
    group = ET.SubElement(root.find('./Skills/SkillSet'), 'Skill', {'enabled': str(enabled).lower(), 'mainActiveSkill': '1', 'includeInFullDPS': 'false'})
    return ET.SubElement(group, 'Gem', {'nameSpec': name, 'skillId': skill_id, 'level': str(level), 'quality': str(quality), 'enabled': 'true'})


def modifiers(root, lines):
    # Synthetic ring applies genuine parsed modifiers without custom-config bypass.
    item = root.find("./Items/Item[@id='1']")
    if item is None:
        item = ET.SubElement(root.find('Items'), 'Item', {'id': '1'})
    item.text = 'Rarity: Rare\nSynthetic Companion Test\nIron Ring\nItem Level: 80\n' + '\n'.join(lines)
    itemset = root.find('./Items/ItemSet')
    slot = next((s for s in itemset.findall('Slot') if s.get('name') == 'Ring 1'), None)
    if slot is None:
        slot = ET.SubElement(itemset, 'Slot', {'name': 'Ring 1'})
    slot.set('itemId', item.get('id'))


def equip(root, name, item_id):
    itemset = root.find('./Items/ItemSet')
    slot = next((s for s in itemset.findall('Slot') if s.get('name') == name), None)
    if slot is None:
        slot = ET.SubElement(itemset, 'Slot', {'name': name})
    slot.set('itemId', str(item_id))


def rows(result):
    return {r['mechanic']: r for r in result['mechanics']}


@pytest.mark.parametrize('name,skill_id', [('Pain Offering', 'PainOfferingPlayer'), ('Bone Offering', 'BoneOfferingPlayer'), ('Soul Offering', 'SoulOfferingPlayer')])
def test_real_offering_life_is_scoped_and_additive(calculate_companions, name, skill_id):
    root = synthetic()
    skill(root, name, skill_id)
    baseline = calculate_companions(root)
    modifiers(root, ['Offerings have 16% increased Maximum Life'])
    offering = calculate_companions(root, ['Offerings have 16% increased Maximum Life'])
    modifiers(root, ['Offerings have 16% increased Maximum Life', 'Minions have 20% increased maximum Life'])
    combined = calculate_companions(root)
    base_life = baseline['offering_life'][0]['life']
    assert offering['parsed'] == [True]
    assert offering['offering_life'][0]['life'] == pytest.approx(round(base_life * 1.16), abs=1)
    assert combined['offering_life'][0]['life'] == pytest.approx(round(base_life * 1.36), abs=1)
    assert offering['life'] == baseline['life']  # player Life never receives Offering-only Life
    assert rows(offering)['offering_life']['status'] == 'calculated'


def test_real_offering_life_never_buff_regular_minion(calculate_companions):
    root = synthetic()
    skill(root, 'Wild Protector', 'WildProtectorPlayer')
    skill(root, 'Pain Offering', 'PainOfferingPlayer')
    baseline = calculate_companions(root)
    modifiers(root, ['Offerings have 100% increased Maximum Life'])
    changed = calculate_companions(root)
    assert changed['minion_life'] == baseline['minion_life']
    assert changed['offering_life'][0]['life'] == baseline['offering_life'][0]['life'] * 2


def test_real_companion_limits_bear_exemption_and_unlimited(calculate_companions):
    root = synthetic()
    skill(root, 'Wild Protector', 'WildProtectorPlayer')
    skill(root, 'Wolf Pack', 'WolfPackPlayer', quality=20)
    baseline = calculate_companions(root)
    assert baseline['issues'] == []
    assert dict((m['name'], m['value']) for m in rows(baseline)['companion_composition']['metrics'])['exempt_companion_types'] == 1
    skill(root, 'Azmerian Wolf', 'SummonAzmerianWolfPlayer')
    over_limit = calculate_companions(root)
    assert {'code': 'companion_limit_exceeded'} in over_limit['issues']
    modifiers(root, ['You can have two Companions of different types'])
    assert calculate_companions(root)['issues'] == []
    skill(root, 'Mist Raven', 'SummonMistRavenPlayer')
    modifiers(root, ['You can have any number of Companions of different types'])
    unlimited = calculate_companions(root)
    assert unlimited['issues'] == []
    assert any(m == {'name': 'unlimited_companion_types', 'value': 1} for m in rows(unlimited)['companion_composition']['metrics'])


def test_real_disabled_companions_and_different_offering_levels(calculate_companions):
    root = synthetic()
    skill(root, 'Wild Protector', 'WildProtectorPlayer')
    skill(root, 'Wolf Pack', 'WolfPackPlayer')
    skill(root, 'Azmerian Wolf', 'SummonAzmerianWolfPlayer', enabled=False)
    skill(root, 'Pain Offering', 'PainOfferingPlayer', level=1)
    skill(root, 'Pain Offering', 'PainOfferingPlayer', level=10)
    result = calculate_companions(root)
    assert result['issues'] == []
    values = {m['name']: m['value'] for m in rows(result)['offering_life']['metrics']}
    assert values['pain_offering_life_minimum'] < values['pain_offering_life_maximum']


def test_real_natural_order_is_inactive_without_tamed_beast(calculate_companions):
    root = synthetic()
    skill(root, 'Wild Protector', 'WildProtectorPlayer')
    lines = ['Tame Beast can capture Unique Beasts', 'Can have up to one Unique Tamed Beast summoned',
             'Unique Tamed Beasts have 30% increased movement speed',
             'Unique Tamed Beasts are Possessed by random Azmeri Spirits, changing every 20 seconds']
    modifiers(root, lines)
    result = calculate_companions(root, lines)
    assert all(result['parsed'])
    assert result['issues'] == []
    assert rows(result)['natural_order']['status'] == 'inactive'


def test_real_pack_life_pool_scales_with_quality(calculate_companions):
    root = synthetic()
    gem = skill(root, 'Wolf Pack', 'WolfPackPlayer')
    modifiers(root, ["5% of Damage from Hits is taken from your Damageable Companion's Life before you"])
    baseline = calculate_companions(root)
    gem.set('quality', '20')
    quality = calculate_companions(root)
    assert baseline['wolf_limit'] == 3
    assert quality['wolf_limit'] == 4
    assert baseline['companion_life'] == baseline['minion_life'] * 3
    assert quality['companion_life'] == quality['minion_life'] * 4
    assert baseline['issues'] == quality['issues'] == []


def test_real_unique_beast_identity_and_missing_rare_mods(calculate_companions):
    root = synthetic()
    unique_id = 'Metadata/Monsters/Quadrilla/QuadrillaBossMinion2'
    rare_id = 'Metadata/Monsters/Quadrilla/Quadrilla'
    ET.SubElement(root.find('Build'), 'BeastCompanion', {'id': unique_id})
    ET.SubElement(root.find('Build'), 'BeastCompanion', {'id': rare_id})
    gem = skill(root, 'Companion: {0}', 'SummonBeastPlayer')
    gem.set('skillMinion', unique_id)
    baseline = calculate_companions(root)
    assert {'code': 'unique_companion_not_allowed'} in baseline['issues']
    lines = ['Tame Beast can capture Unique Beasts', 'Can have up to one Unique Tamed Beast summoned',
             'Unique Tamed Beasts have 30% increased movement speed',
             'Unique Tamed Beasts are Possessed by random Azmeri Spirits, changing every 20 seconds']
    modifiers(root, lines)
    allowed = calculate_companions(root)
    assert {'code': 'unique_companion_not_allowed'} not in allowed['issues']
    assert {'code': 'unsupported_companion_mechanic'} in allowed['issues']
    assert rows(allowed)['natural_order']['status'] == 'requires_configuration'
    assert allowed['minion_speed'] > baseline['minion_speed']
    gem.set('skillMinion', rare_id)
    rare = calculate_companions(root)
    assert rows(rare)['natural_order']['status'] == 'inactive'
    assert rows(rare)['tamed_beast_modifiers']['status'] == 'requires_configuration'
    assert {'code': 'missing_companion_data'} in rare['issues']


def test_real_bonded_gold_requires_bonded_activation(calculate_companions):
    root = synthetic()
    body = ET.SubElement(root.find('Items'), 'Item', {'id': '2'})
    body.text = 'Rarity: Rare\nSynthetic Body\nRusted Cuirass\nItem Level: 80\nSockets: S\nRune: Rabbit Idol'
    equip(root, 'Body Armour', 2)
    inactive = calculate_companions(root)
    body.text = body.text.replace('Sockets: S', 'Sockets: S S') + '\nRune: Fox Idol'
    active = calculate_companions(root)
    assert 'economy_effects' not in rows(inactive)
    assert 'economy_effects' in rows(active)
    assert rows(active)['economy_effects']['metrics'] == [{'name': 'gold_quantity_increase', 'value': 10}]
    assert active['life'] == inactive['life']


def test_real_item_grant_mirror_is_not_a_second_companion(calculate_companions):
    root = synthetic()
    skill(root, 'Azmerian Wolf', 'SummonAzmerianWolfPlayer', level=14)
    group = root.findall('./Skills/SkillSet/Skill')[-1]
    ET.SubElement(group, 'Gem', {'nameSpec': 'Minion Mastery', 'skillId': 'SupportMinionMasteryPlayer', 'level': '1', 'quality': '0', 'enabled': 'true'})
    weapon = ET.SubElement(root.find('Items'), 'Item', {'id': '2'})
    weapon.text = "Rarity: Unique\nSylvan's Effigy\nStoic Sceptre\nItem Level: 80\nImplicits: 2\nGrants Skill: Level 14 Discipline\nGrants Skill: Level 14 Azmerian Wolf\n"
    equip(root, 'Weapon 2', 2)
    result = calculate_companions(root)
    assert result['issues'] == []
    values = {m['name']: m['value'] for m in rows(result)['companion_composition']['metrics']}
    assert values['active_companion_types'] == 1
    assert result['grant_mirrors'] == 1


def test_real_tree_grant_mirror_scales_and_contributes_life_once(calculate_companions):
    root = synthetic()
    skill(root, 'Wild Protector', 'WildProtectorPlayer', level=20)
    group = root.findall('./Skills/SkillSet/Skill')[-1]
    ET.SubElement(group, 'Gem', {'nameSpec': 'Minion Mastery', 'skillId': 'SupportMinionMasteryPlayer', 'level': '1', 'quality': '0', 'enabled': 'true'})
    modifiers(root, ['+7 to Level of all Minion Skills',
                     "5% of Damage from Hits is taken from your Damageable Companion's Life before you"])
    result = calculate_companions(root, tree_nodes=[62743])
    bears = [row for row in result['companion_skills'] if row['id'] == 'WildProtectorPlayer']
    assert len(bears) == 2
    assert {row['base_level'] for row in bears} == {20}
    explicit = next(row for row in bears if not row['generated'])
    generated = next(row for row in bears if row['generated'])
    assert explicit['level'] == 28  # seven global levels plus linked Minion Mastery
    assert generated['level'] == 27
    assert generated['mirrored'] is True
    assert result['issues'] == []
    values = {m['name']: m['value'] for m in rows(result)['companion_composition']['metrics']}
    assert values['exempt_companion_types'] == 1
    assert result['companion_life'] == result['minion_life']


def test_real_distinct_explicit_groups_still_fail_duplicate_companion_type(calculate_companions):
    root = synthetic()
    skill(root, 'Wolf Pack', 'WolfPackPlayer')
    skill(root, 'Wolf Pack', 'WolfPackPlayer')
    modifiers(root, ['You can have any number of Companions of different types'])
    result = calculate_companions(root)
    assert {'code': 'duplicate_companion_type'} in result['issues']
    assert result['grant_mirrors'] == 0


def test_real_three_grant_mirrors_preserve_six_distinct_companion_types(calculate_companions):
    # Synthetic acceptance case for simultaneous tree, sceptre and body grants.
    # Counts default to one on generated groups, as in a recalculated import.
    root = synthetic()
    for name, skill_id, level in [('Wild Protector', 'WildProtectorPlayer', 20),
                                  ('Azmerian Wolf', 'SummonAzmerianWolfPlayer', 19),
                                  ('Spirit Vessel', 'SpiritVesselPlayer', 19),
                                  ('Tame Beast', 'TameBeastPlayer', 20),
                                  ('Wolf Pack', 'WolfPackPlayer', 20)]:
        skill(root, name, skill_id, level=level)
        root.findall('./Skills/SkillSet/Skill')[-1].set('count', '1')
    bear_group = root.findall('./Skills/SkillSet/Skill')[0]
    ET.SubElement(bear_group, 'Gem', {'nameSpec': 'Loyalty', 'skillId': 'SupportLoyaltyPlayer', 'level': '1', 'quality': '0', 'enabled': 'true'})
    for beast_id in ['Metadata/Monsters/Quadrilla/Quadrilla',
                     'Metadata/Monsters/GoreCharger/GoreCharger',
                     'Metadata/Monsters/Quadrilla/QuadrillaBossMinion2']:
        ET.SubElement(root.find('Build'), 'BeastCompanion', {'id': beast_id})
        gem = skill(root, 'Companion: {0}', 'SummonBeastPlayer', level=20)
        gem.set('skillMinion', beast_id)
    weapon = ET.SubElement(root.find('Items'), 'Item', {'id': '2'})
    weapon.text = "Rarity: Unique\nSylvan's Effigy\nStoic Sceptre\nItem Level: 80\nImplicits: 2\nGrants Skill: Level 19 Discipline\nGrants Skill: Level 19 Azmerian Wolf\nYou can have any number of Companions of different types"
    equip(root, 'Weapon 2', 2)
    body = ET.SubElement(root.find('Items'), 'Item', {'id': '3'})
    body.text = 'Rarity: Rare\nSynthetic Vessel Body\nRusted Cuirass\nItem Level: 80\nGrants Skill: Level 19 Spirit Vessel'
    equip(root, 'Body Armour', 3)
    modifiers(root, ['+500 to all Attributes', '+7 to Level of all Minion Skills',
                     'Tame Beast can capture Unique Beasts', 'Can have up to one Unique Tamed Beast summoned'])
    result = calculate_companions(root, tree_nodes=[62743])
    composition = rows(result)['companion_composition']
    values = {m['name']: m['value'] for m in composition['metrics']}
    assert composition['status'] == 'calculated'
    assert values == {'active_companion_types': 6, 'exempt_companion_types': 1,
                      'unique_tamed_beasts': 1, 'unlimited_companion_types': 1}
    assert result['grant_mirrors'] == 3
    bears = [row for row in result['companion_skills'] if row['id'] == 'WildProtectorPlayer']
    assert len(bears) == 2
    assert {row['base_level'] for row in bears} == {20}
    assert {row['level'] for row in bears} == {27}
    assert {'code': 'duplicate_companion_type'} not in result['issues']


def test_real_bone_offering_matches_public_level_68_life(calculate_companions):
    # https://poe2db.tw/us/Offering_Spike lists level-68 Bone spike Minion Life 2426.
    root = synthetic()
    skill(root, 'Bone Offering', 'BoneOfferingPlayer', level=34)
    result = calculate_companions(root)
    assert result['offering_life'][0]['level'] == 68
    # PoB floors the base pool, whereas PoE2DB rounds its displayed Life.
    assert result['offering_life'][0]['life'] == pytest.approx(2426, abs=1)


def test_real_inactive_weapon_group_has_no_offering_or_companion(calculate_companions):
    root = synthetic()
    skill(root, 'Spark', 'SparkPlayer')
    for name, skill_id in [('Pain Offering', 'PainOfferingPlayer'), ('Azmerian Wolf', 'SummonAzmerianWolfPlayer')]:
        gem = skill(root, name, skill_id)
        group = next(g for g in root.findall('./Skills/SkillSet/Skill') if gem in list(g))
        group.set('set1', 'false')
        group.set('set2', 'true')
    result = calculate_companions(root)
    assert 'offering_life' not in rows(result)
    assert 'companion_composition' not in rows(result)
