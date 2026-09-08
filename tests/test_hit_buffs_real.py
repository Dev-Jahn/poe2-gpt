"""Source-backed hit/kill buff regressions with entirely synthetic builds."""
import json
import os
from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET

import pytest

FIXTURE = Path(__file__).parent / 'fixtures/engine_synthetic.xml'
MODULE = Path(__file__).parents[1] / 'src/poe2_companion/lua/hit_buffs.lua'


def synthetic(groups, *, config=None, weapon_lines=()):
    root = ET.fromstring(FIXTURE.read_bytes())
    root.find('Build').set('mainSocketGroup', '1')
    skills = root.find('./Skills/SkillSet')
    for gems in groups:
        group = ET.SubElement(skills, 'Skill', {'enabled': 'true', 'mainActiveSkill': '1'})
        for entry in gems:
            skill_id, enabled = entry if isinstance(entry, tuple) else (entry, True)
            ET.SubElement(group, 'Gem', {'skillId': skill_id, 'nameSpec': skill_id, 'level': '1', 'quality': '0', 'enabled': str(enabled).lower()})
    for key, value in (config or {}).items():
        kind = 'boolean' if isinstance(value, bool) else 'number' if isinstance(value, (int, float)) else 'string'
        ET.SubElement(root.find('./Config/ConfigSet'), 'Input', {'name': key, kind: str(value).lower() if kind == 'boolean' else str(value)})
    item = ET.SubElement(root.find('Items'), 'Item', {'id': '1'})
    item.text = 'Rarity: Rare\nSynthetic Hit Test\nWrapped Quarterstaff\nItem Level: 80\nAdds 100 to 100 Physical Damage\n' + '\n'.join(weapon_lines)
    root.find("./Items/ItemSet/Slot[@name='Weapon 1']").set('itemId', '1')
    return ET.tostring(root, encoding='unicode')


@pytest.fixture
def run_hits(tmp_path):
    location = os.environ.get('POE2_TEST_ENGINE_DIR')
    if not location:
        pytest.skip('Set POE2_TEST_ENGINE_DIR for native integration')
    engine = Path(location)
    script = tmp_path / 'hit_probe.lua'
    script.write_text('''print=function() end
local json=require('dkjson')
local input=assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
local module=dofile(input.module)
local result={}
for _,xml in ipairs(input.cases) do
 loadBuildFromXML(xml,'')
 assert(not __mainObject__.promptMsg, __mainObject__.promptMsg)
 local env,out=build.calcsTab.mainEnv,build.calcsTab.mainOutput
 local mechanics,issues=module.inspect(build,env,out)
 local player=env.player
 local active=player.mainSkill
 local mod=active.skillModList
 local cfg=active.skillCfg
 result[#result+1]={mechanics=mechanics,issues=issues,dps=out.CombinedDPS,speed=out.Speed,
  move=out.MovementSpeedMod,cull=out.CullPercent or 0,crit=out.CritChance,
  crit_multi=out.CritMultiplier,lightning=out.LightningAverage or 0,
  extra_lightning=mod:Sum('BASE',cfg,'DamageGainAsLightning'),
  shock_increase=mod:Sum('INC',cfg,'EnemyShockChance'),shock=out.ShockChance,
  maim=out.MaimChance or 0,blind=out.BlindChance or 0,
  enemy_evasion=calcLib.val(env.enemy.modDB,'Evasion'),
  enemy_maimed=env.enemy.modDB:Flag(nil,'Condition:Maimed') or false,
  enemy_blinded=env.enemy.modDB:Flag(nil,'Condition:Blinded') or false,
  minion_dps=out.Minion and out.Minion.CombinedDPS,
  minion_maim=out.Minion and out.Minion.MaimChance,
  onslaught=env.modDB:Flag(nil,'Onslaught') or false,
 }
end
io.write(json.encode(result))
''')

    def run(cases):
        env = dict(os.environ)
        env['LUA_PATH'] = str(engine / 'runtime/lua/?.lua') + ';' + str(engine / 'runtime/lua/?/init.lua') + ';;'
        result = subprocess.run([os.environ.get('POE2_TEST_LUAJIT', 'luajit'), str(script)], cwd=engine / 'src', env=env, capture_output=True, text=True, timeout=120, input=json.dumps({'module': str(MODULE), 'cases': cases}))
        assert result.returncode == 0, result.stderr[-2500:]
        return json.loads(result.stdout)
    return run


def row(result, key):
    return next(r for r in result['mechanics'] if r['mechanic'] == key)


def metrics(result, key):
    return {m['name']: m['value'] for m in row(result, key)['metrics']}


def test_thrill_global_attack_buff_requires_compatible_enabled_source(run_hits):
    groups = [['KillingPalmPlayer'], ['KillingPalmPlayer', 'SupportThrillOfTheKillPlayerTwo']]
    plain, active, disabled, incompatible, spell = run_hits([
        synthetic(groups),
        synthetic(groups, config={'companionThrillOfTheKillActive': True}),
        synthetic([groups[0], ['KillingPalmPlayer', ('SupportThrillOfTheKillPlayerTwo', False)]], config={'companionThrillOfTheKillActive': True}),
        synthetic([groups[0], ['WildProtectorPlayer', 'SupportThrillOfTheKillPlayerTwo']], config={'companionThrillOfTheKillActive': True}),
        synthetic([['SparkPlayer'], groups[1]], config={'companionThrillOfTheKillActive': True}),
    ])
    assert plain['dps'] > 0
    assert plain['extra_lightning'] == 0
    assert active['extra_lightning'] == 25
    assert active['shock_increase'] == 40
    assert active['dps'] > plain['dps']
    assert metrics(active, 'thrill_of_the_kill')['thrill_base_duration_seconds'] == 8
    assert row(plain, 'thrill_of_the_kill')['status'] == 'requires_configuration'
    assert plain['issues'] == [{'code': 'missing_combat_assumption'}]
    assert active['issues'] == []
    assert disabled['dps'] == pytest.approx(plain['dps'])
    assert incompatible['dps'] == pytest.approx(plain['dps'])
    assert spell['extra_lightning'] == 0


def test_cull_threshold_buff_applies_to_other_culling_skill_without_granting_cull(run_hits):
    groups = [['KillingPalmPlayer'], ['KillingPalmPlayer', 'SupportCullingStrikePlayerTwo']]
    settings = {'enemyIsBoss': 'Boss'}
    base, active, disabled, no_cull = run_hits([
        synthetic(groups, config=settings),
        synthetic(groups, config={**settings, 'companionCullingStrikeRecentCull': True}),
        synthetic([groups[0], ['KillingPalmPlayer', ('SupportCullingStrikePlayerTwo', False)]], config={**settings, 'companionCullingStrikeRecentCull': True}),
        synthetic([['SparkPlayer'], groups[1]], config={**settings, 'companionCullingStrikeRecentCull': True}),
    ])
    assert base['cull'] > 0
    assert active['cull'] == pytest.approx(base['cull'] * 1.2)
    assert disabled['cull'] == base['cull']
    assert no_cull['cull'] == 0
    assert metrics(active, 'culling_strike_buff')['culling_buff_base_duration_seconds'] == 20


def test_blindside_forbids_own_blind_but_keeps_external_blind_benefits(run_hits):
    lines = ['100% chance to Blind enemies on hit']
    groups = [['KillingPalmPlayer', 'SupportBlindsidePlayer']]
    base, forbidden, external = run_hits([
        synthetic([['KillingPalmPlayer']], weapon_lines=lines),
        synthetic(groups, weapon_lines=lines),
        synthetic(groups, weapon_lines=lines, config={'conditionEnemyBlinded': True}),
    ])
    assert base['blind'] == 100
    assert forbidden['blind'] == external['blind'] == 0
    assert forbidden['enemy_blinded'] is False
    assert external['enemy_blinded'] is True
    assert external['crit'] == pytest.approx(forbidden['crit'] * 1.15, rel=.01)
    assert external['crit_multi'] > forbidden['crit_multi']


def test_maim_capability_does_not_assume_enemy_debuff_or_minion_uptime(run_hits):
    groups = [['KillingPalmPlayer', 'SupportMaimPlayer']]
    base, maimed, minion = run_hits([
        synthetic(groups),
        synthetic(groups, config={'conditionEnemyMaimed': True}),
        synthetic([['SummonAzmerianWolfPlayer']]),
    ])
    assert base['maim'] == 100
    assert base['enemy_maimed'] is False
    assert maimed['enemy_maimed'] is True
    assert maimed['enemy_evasion'] == pytest.approx(base['enemy_evasion'] * .85, abs=1)
    assert minion['minion_maim'] == 100
    assert minion['enemy_maimed'] is False


def test_behead_reports_two_random_modifiers_and_duration_without_invented_damage(run_hits):
    base, supported = run_hits([
        synthetic([['KillingPalmPlayer']]),
        synthetic([['KillingPalmPlayer', 'SupportBeheadPlayerTwo']]),
    ])
    assert base['dps'] == supported['dps']
    assert row(supported, 'behead')['status'] == 'partial'
    assert supported['issues'] == [{'code': 'missing_combat_assumption'}]
    assert metrics(supported, 'behead') == {'behead_modifiers_per_rare_kill': 2, 'behead_base_duration_seconds': 20}


def test_onslaught_random_acquisition_never_becomes_automatic_uptime(run_hits):
    lines = ['25% chance to gain Onslaught on Killing Hits with this Weapon']
    groups = [['KillingPalmPlayer']]
    base, recent, active, guaranteed = run_hits([
        synthetic(groups, weapon_lines=lines),
        synthetic(groups, weapon_lines=lines, config={'conditionKilledRecently': True}),
        synthetic(groups, weapon_lines=lines, config={'buffOnslaught': True}),
        synthetic(groups, weapon_lines=['You gain Onslaught for 4 seconds on Kill'], config={'conditionKilledRecently': True}),
    ])
    assert base['onslaught'] is False
    assert recent['dps'] == base['dps']
    assert guaranteed['onslaught'] is False
    assert active['onslaught'] is True
    assert active['speed'] == pytest.approx(base['speed'] * 1.2)
    assert active['move'] == pytest.approx(base['move'] + .1)
    assert metrics(base, 'onslaught')['onslaught_highest_source_chance_percent'] == 25
    assert metrics(base, 'onslaught')['onslaught_longest_source_base_duration_seconds'] == 4


def test_explicit_inactive_buffs_do_not_require_an_assumption(run_hits):
    result, = run_hits([synthetic(
        [['KillingPalmPlayer', 'SupportThrillOfTheKillPlayerTwo', 'SupportCullingStrikePlayerTwo']],
        config={'companionThrillOfTheKillActive': False, 'companionCullingStrikeRecentCull': False, 'buffOnslaught': False},
        weapon_lines=['25% chance to gain Onslaught on Killing Hits with this Weapon'],
    )])
    assert result['issues'] == []
    for mechanic in ('thrill_of_the_kill', 'culling_strike_buff', 'onslaught'):
        assert row(result, mechanic)['status'] == 'inactive'
        assert row(result, mechanic)['required_inputs'] == []
