"""Native differential tests using synthetic characters, never account exports."""
import json
import math
import os
from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET

import pytest

FIXTURE = Path(__file__).parent / 'fixtures/engine_synthetic.xml'


@pytest.fixture
def calculate(tmp_path):
    location = os.environ.get('POE2_TEST_ENGINE_DIR')
    if not location:
        pytest.skip('Set POE2_TEST_ENGINE_DIR for real Lua integration')
    engine = Path(location)
    script = tmp_path / 'curse_probe.lua'
    script.write_text('''print=function() end
local json=require('dkjson')
local input=assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
loadBuildFromXML(input.xml,'')
assert(not __mainObject__.promptMsg,tostring(__mainObject__.promptMsg))
local module=dofile(input.module)
module.apply_configuration(build,input.config)
wipeGlobalCache()
build.buildFlag=true
runCallback('OnFrame')
assert(not __mainObject__.promptMsg,tostring(__mainObject__.promptMsg))
local env,out=build.calcsTab.mainEnv,build.calcsTab.mainOutput
local projection=module.inspect(build,env,out,input.config)
local curses,skills={},{}
for _,curse in ipairs(env.curseSlots or {}) do curses[#curses+1]={mark=curse.isMark or false} end
for _,skill in ipairs(env.player.activeSkillList) do skills[#skills+1]={id=skill.activeEffect.grantedEffect.id,level=skill.activeEffect.level,
 aura=skill.skillTypes[SkillType.Aura],disabled=skill.disableReason~=nil, radius=skill.skillData.radius,
 target_limit=skill.skillData.curseTargetLevelLimit,mark_count=skill.skillData.markTargetsPerType,
 trigger=skill.skillData.chargedMarkTriggerOnActivation,chance=skill.skillData.chargedMarkTriggerChance} end
io.write(json.encode({projection=projection,curses=curses,skills=skills,dps=out.TotalDPS,
 main_skill=env.player.mainSkill.activeEffect.grantedEffect.id,
 life=out.Life,speed=out.Speed,fire_resist=out.FireResist,armour=out.Armour,
 crit=out.CritChance,poison=out.PoisonDPS,shock=env.enemyDB:Flag(nil,'Condition:Shocked'),
 armour_break=out.ArmourBreakPerHit,average=out.AverageHit,chill=out.ChillChanceOnHit,
 lightning_base_min=out.LightningMinBase,lightning_base_max=out.LightningMaxBase,
 lightning_hit_min=out.LightningStoredHitMin,lightning_hit_max=out.LightningStoredHitMax,
 fire_hit_min=out.FireStoredHitMin,fire_hit_max=out.FireStoredHitMax,
 cold_hit_min=out.ColdStoredHitMin,cold_hit_max=out.ColdStoredHitMax,
 movement=out.MovementSpeedMod,enemy_speed=env.enemyDB:Sum('INC',nil,'TemporalChainsActionSpeed'),
 rite=env.companionRitePossession,available=calcs.companionRiteAvailability(env),
 charm_limit=env.modDB:Sum('BASE',nil,'CharmLimit'),
 damage_taken=env.modDB:Sum('INC',nil,'DamageTaken'),minion=out.Minion and out.Minion.TotalDPS}))
'''.replace('calcs.companionRiteAvailability(env)', "require('Modules.CalcBase').companionRiteAvailability(env)"))

    def run(root, **config):
        env = dict(os.environ)
        env['LUA_PATH'] = str(engine / 'runtime/lua/?.lua') + ';' + str(engine / 'runtime/lua/?/init.lua') + ';;'
        result = subprocess.run([os.environ.get('POE2_TEST_LUAJIT', 'luajit'), str(script)], cwd=engine / 'src',
            env=env, capture_output=True, text=True, timeout=90,
            input=json.dumps({'xml': ET.tostring(root, encoding='unicode'), 'config': config,
                             'module': str(Path(__file__).parents[1] / 'src/poe2_companion/lua/curse_mechanics.lua')}))
        assert result.returncode == 0, result.stderr[-1500:]
        return json.loads(result.stdout)
    return run


def synthetic(enemy=84):
    root = ET.fromstring(FIXTURE.read_bytes())
    group(root, 'Spark', 'SparkPlayer', 20)
    ET.SubElement(root.find('Config'), 'Input', {'name': 'enemyLevel', 'number': str(enemy)})
    return root


def gem(parent, name, skill, level=1, enabled=True):
    return ET.SubElement(parent, 'Gem', {'nameSpec': name, 'skillId': skill, 'level': str(level),
                                       'quality': '0', 'enabled': str(enabled).lower()})


def group(root, name, skill, level=1):
    result = ET.SubElement(root.find('./Skills/SkillSet'), 'Skill', {'enabled': 'true', 'mainActiveSkill': '1'})
    gem(result, name, skill, level)
    return result


def item(root, number, slot, text):
    ET.SubElement(root.find('Items'), 'Item', {'id': str(number)}).text = text
    slots = root.find('./Items/ItemSet')
    node = next((s for s in slots.findall('Slot') if s.get('name') == slot), None)
    if node is None:
        node = ET.SubElement(slots, 'Slot', {'name': slot})
    node.set('itemId', str(number))
    node.set('active', 'false')


def rite(root, spirit='Bear', *, slot='Charm 1', duration=15, limit=True):
    if limit:
        item(root, 2, 'Belt', 'Rarity: Rare\nSynthetic Belt\nLinen Belt\nItem Level: 80\n+1 Charm Slot')
    item(root, 3, slot, 'Rarity: Unique\nRite of Passage\nGolden Charm\nItem Level: 80\n'
         f'Possessed by Spirit Of The {spirit} for {duration} seconds on use')


def metrics(result, mechanic):
    row = next(r for r in result['projection'] if r['mechanic'] == mechanic)
    return {m['name']: m['value'] for m in row['metrics']}


@pytest.mark.parametrize('level,enemy,applied', [(1,20,True),(1,21,False),(17,78,True),(17,79,False),(18,84,True)])
def test_curse_exact_target_level_gate(calculate, level, enemy, applied):
    root = synthetic(enemy)
    group(root, 'Temporal Chains', 'TemporalChainsPlayer', level)
    result = calculate(root)
    assert bool(result['curses']) == applied
    assert (result['enemy_speed'] < 0) == applied
    assert metrics(result, 'curse_application')['curse_target_level_allowed'] == int(applied)


def test_blasphemy_native_half_effect_and_same_level_gate(calculate):
    root = synthetic(20)
    curses = group(root, 'Temporal Chains', 'TemporalChainsPlayer')
    baseline = calculate(root)
    gem(curses, 'Blasphemy', 'BlasphemyPlayer')
    result = calculate(root)
    assert result['enemy_speed'] == baseline['enemy_speed'] / 2
    assert metrics(result, 'curse_application')['curse_applies_as_aura'] == 1
    for node in root.findall('./Config/Input'):
        if node.get('name') == 'enemyLevel': node.set('number', '21')
    assert calculate(root)['enemy_speed'] == 0


def test_overlevel_curse_cannot_claim_other_gems_applied_effect(calculate):
    root = synthetic(21)
    group(root, 'Temporal Chains', 'TemporalChainsPlayer', 1)
    group(root, 'Temporal Chains', 'TemporalChainsPlayer', 20)
    result = calculate(root)
    curse_rows = [r for r in result['projection'] if r['mechanic'] == 'curse_application']
    assert len(curse_rows) == 2
    for row in curse_rows:
        values = {m['name']: m['value'] for m in row['metrics']}
        assert values['curse_applied'] == values['curse_target_level_allowed']
    assert result['enemy_speed'] < 0


def test_native_same_mark_does_not_stack_or_use_curse_slot(calculate):
    root = synthetic(20)
    group(root, "Sniper's Mark", 'SnipersMarkPlayer', 20)
    once = calculate(root)
    group(root, "Sniper's Mark", 'SnipersMarkPlayer', 20)
    group(root, 'Temporal Chains', 'TemporalChainsPlayer')
    result = calculate(root)
    assert sum(c['mark'] for c in result['curses']) == 1
    assert sum(not c['mark'] for c in result['curses']) == 1
    assert once['dps'] == result['dps']
    assert all(s.get('mark_count') == 1 for s in result['skills'] if s['id'] == 'SnipersMarkPlayer')


@pytest.mark.parametrize('level,radius', [(1,1.4),(15,2.1),(20,2.3)])
def test_charged_mark_requires_explicit_ground_and_inherits_level(calculate, level, radius):
    root = synthetic()
    mark = group(root, "Sniper's Mark", 'SnipersMarkPlayer', level)
    gem(mark, 'Charged Mark', 'SupportChargedMarkPlayer')
    baseline = calculate(root)
    result = calculate(root, charged_mark_ground_active=True)
    assert result['dps'] / baseline['dps'] == pytest.approx(1.2)
    values = metrics(result, 'charged_mark')
    assert values['charged_mark_triggered_skill_level'] == level
    assert values['charged_mark_ground_radius_metres'] == radius
    assert values['charged_mark_ground_duration_seconds'] == pytest.approx(math.ceil(6/.033)*.033)
    assert values['charged_mark_trigger_chance_percent'] == 100
    assert values['charged_mark_ground_active'] == 1
    assert metrics(calculate(root, charged_mark_ground_active=False), 'charged_mark')['charged_mark_ground_active'] == 0


def test_charged_mark_disabled_or_incompatible_support_does_not_add_shock(calculate):
    root = synthetic()
    baseline = calculate(root)
    mark = group(root, "Sniper's Mark", 'SnipersMarkPlayer', 20)
    gem(mark, 'Charged Mark', 'SupportChargedMarkPlayer', enabled=False)
    mark_only = calculate(root, charged_mark_ground_active=False)
    assert calculate(root, charged_mark_ground_active=True)['dps'] == mark_only['dps']
    mark.set('enabled', 'false')
    root.find('./Skills/SkillSet/Skill/Gem').set('enabled', 'true')
    assert calculate(root, charged_mark_ground_active=True)['dps'] == baseline['dps']
    gem(root.find('./Skills/SkillSet/Skill'), 'Charged Mark', 'SupportChargedMarkPlayer')
    assert calculate(root, charged_mark_ground_active=True)['dps'] == baseline['dps']


def test_charged_mark_ground_has_no_hit_even_with_added_spell_damage(calculate):
    root = synthetic()
    mark = group(root, "Sniper's Mark", 'SnipersMarkPlayer', 20)
    gem(mark, 'Charged Mark', 'SupportChargedMarkPlayer')
    mark.set('mainActiveSkill', '2')
    root.find('Build').set('mainSocketGroup', '2')
    item(root, 4, 'Ring 1', 'Rarity: Rare\nSynthetic Ring\nIron Ring\nItem Level: 80\nAdds 100 to 100 Lightning Damage to Spells')
    result = calculate(root, charged_mark_ground_active=True)
    assert result['main_skill'] == 'TriggeredChargedMarkPlayer'
    assert result['dps'] == 0


def test_charged_mark_native_radius_duration_and_magnitude_scaling(calculate):
    root = synthetic()
    mark = group(root, "Sniper's Mark", 'SnipersMarkPlayer', 20)
    gem(mark, 'Charged Mark', 'SupportChargedMarkPlayer')
    item(root, 4, 'Ring 1', 'Rarity: Rare\nSynthetic Ring\nIron Ring\nItem Level: 80\n'
         '20% increased Area of Effect\n50% increased Skill Effect Duration\n50% increased Magnitude of Shock you inflict')
    baseline = calculate(root, charged_mark_ground_active=False)
    result = calculate(root, charged_mark_ground_active=True)
    assert result['dps'] / baseline['dps'] == pytest.approx(1.3)
    values = metrics(result, 'charged_mark')
    assert values['charged_mark_ground_radius_metres'] == 2.5
    assert values['charged_mark_ground_duration_seconds'] == pytest.approx(math.ceil(9/.033)*.033)


def test_rite_requires_equipped_matching_charm_and_explicit_possession(calculate):
    root = synthetic()
    baseline = calculate(root)
    assert calculate(root, rite_of_passage_spirit='bear')['life'] == baseline['life']
    rite(root)
    idle = calculate(root)
    assert idle['life'] == baseline['life']
    mismatch = calculate(root, rite_of_passage_spirit='cat')
    assert mismatch['life'] == baseline['life']
    mismatch_row = next(r for r in mismatch['projection'] if r['mechanic'] == 'rite_of_passage')
    assert mismatch_row['status'] == 'requires_configuration'
    assert mismatch_row['required_inputs'] == ['rite_of_passage_spirit']
    active = calculate(root, rite_of_passage_spirit='bear')
    assert active['life'] / baseline['life'] == pytest.approx(1.25/1.05, abs=.002)
    assert active['damage_taken'] == -20
    assert metrics(active, 'rite_of_passage')['rite_of_passage_base_possession_duration_seconds'] == 15
    inactive = calculate(root, rite_of_passage_spirit='none')
    assert inactive['life'] == baseline['life']
    inactive_row = next(r for r in inactive['projection'] if r['mechanic'] == 'rite_of_passage')
    assert inactive_row['status'] == 'inactive'
    assert inactive_row['required_inputs'] == []


def test_rite_charm_limit_is_enforced(calculate):
    root = synthetic()
    rite(root, slot='Charm 2')
    assert not calculate(root, rite_of_passage_spirit='bear').get('rite')


@pytest.mark.parametrize('spirit,speed', [('Cat',1.3),('Stag',1.3),('Wolf',1.1)])
def test_rite_player_speed_values_are_not_haunted_monster_values(calculate, spirit, speed):
    root = synthetic()
    baseline = calculate(root)
    rite(root, spirit)
    result = calculate(root, rite_of_passage_spirit=spirit.lower())
    assert result['speed'] / baseline['speed'] == pytest.approx(speed)
    if spirit == 'Stag': assert result['fire_resist'] - baseline['fire_resist'] == 30


def test_rite_serpent_all_damage_contributes_to_real_poison(calculate):
    root = synthetic()
    baseline = calculate(root)
    rite(root, 'Serpent')
    result = calculate(root, rite_of_passage_spirit='serpent')
    assert result.get('poison', 0) > baseline.get('poison', 0)
    assert result['dps'] > baseline['dps']


def test_rite_player_possession_does_not_become_minion_damage(calculate):
    root = synthetic()
    group(root, 'Skeletal Sniper', 'SummonSkeletalSnipersPlayer', 20)
    root.find('Build').set('mainSocketGroup', '2')
    baseline = calculate(root)
    rite(root, 'Owl')
    result = calculate(root, rite_of_passage_spirit='owl')
    assert baseline['minion'] > 0
    assert result['minion'] == baseline['minion']


def test_rite_wolf_breaks_ten_percent_of_actual_hit_without_assuming_broken_armour(calculate):
    root = synthetic()
    rite(root, 'Wolf')
    baseline = calculate(root)
    result = calculate(root, rite_of_passage_spirit='wolf')
    assert result['armour_break'] == pytest.approx(result['average'] * .1)
    assert result['average'] == baseline['average']


@pytest.mark.parametrize('spirit,damage_multiplier,extra_type', [
    ('Boar', 1, 'fire'), ('Owl', 1.8, 'cold'), ('Primate', 1.8, None),
])
def test_rite_native_elemental_gain_and_damage_bonuses(calculate, spirit, damage_multiplier, extra_type):
    root = synthetic(20)
    baseline = calculate(root)
    rite(root, spirit)
    result = calculate(root, rite_of_passage_spirit=spirit.lower())
    # PoB rounds each damage endpoint before averaging or applying mitigation.
    # An exact unrounded DPS ratio would reject the correct native calculation.
    expected_total = 0
    baseline_total = 0
    for endpoint in ('min', 'max'):
        base = baseline[f'lightning_base_{endpoint}']
        lightning = math.floor(base * damage_multiplier + .5)
        assert result[f'lightning_hit_{endpoint}'] == lightning
        expected_total += lightning
        baseline_total += baseline[f'lightning_hit_{endpoint}']
        for element in ('fire', 'cold'):
            extra = math.floor(base * damage_multiplier * .2 + .5) if element == extra_type else 0
            assert result.get(f'{element}_hit_{endpoint}', 0) == extra
            expected_total += extra
    assert result['dps'] / baseline['dps'] == pytest.approx(expected_total / baseline_total)
    if spirit == 'Primate': assert result['chill'] > 0


def test_rite_ox_armour_and_damage_reduction(calculate):
    root = synthetic()
    item(root, 4, 'Ring 1', 'Rarity: Rare\nSynthetic Ring\nIron Ring\nItem Level: 80\n+1000 to Armour')
    baseline = calculate(root)
    rite(root, 'Ox')
    result = calculate(root, rite_of_passage_spirit='ox')
    assert result['armour']/baseline['armour'] == pytest.approx(1.6)
    assert result['damage_taken'] == -20
