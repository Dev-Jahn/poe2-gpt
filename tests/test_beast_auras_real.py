"""Captured ally auras on genuine synthetic PoB actors, never user exports."""
import json
import os
from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET

import pytest

from test_companions_real import synthetic, skill, captured_beast, beast_modifier, modifiers

MODULE = Path(__file__).parents[1] / 'src/poe2_companion/lua/beast_auras.lua'


@pytest.fixture
def calculate_auras(tmp_path):
    engine = os.environ.get('POE2_TEST_ENGINE_DIR')
    if not engine:
        pytest.skip('Set POE2_TEST_ENGINE_DIR for real Lua integration')
    engine = Path(engine)
    script = tmp_path / 'aura_probe.lua'
    script.write_text('''print=function() end
local json=require('dkjson')
local input=assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
local module=dofile(input.module)
loadBuildFromXML(input.xml,'')
if input.configuration then module.apply_configuration(build,input.configuration) end
if input.config_input then
 for key,value in pairs(input.config_input) do build.configTab.input[key]=value end
end
build.configTab:BuildModList()
-- Synthetic native modifiers isolate prohibition/avoidance branches without
-- adding arbitrary modifier-text fields to the public calculation API.
for _, flag in ipairs(input.fixture_flags or {}) do
 build.configTab.modList:NewMod('MinionModifier','LIST',{mod=modLib.createMod(flag,'FLAG',true,'Synthetic fixture')},'Synthetic fixture')
end
if input.fixture_avoid then
 build.configTab.enemyModList:NewMod('AvoidChill','BASE',input.fixture_avoid,'Synthetic fixture')
end
wipeGlobalCache()
build.buildFlag=true; runCallback('OnFrame')
assert(not __mainObject__.promptMsg,__mainObject__.promptMsg)
local env,out=build.calcsTab.mainEnv,build.calcsTab.mainOutput
local mechanics,issues=module.inspect(build,env,out)
local m=out.Minion or {}
local function sources(db,stat,flags)
 if not db then return 0 end
 return db:Sum('INC',flags and {flags=flags} or nil,stat)
end
io.write(json.encode({mechanics=mechanics,issues=issues,dps=out.CombinedDPS,speed=out.Speed,
 minion_dps=m.CombinedDPS,minion_speed=m.Speed,minion_move=m.MovementSpeedMod,
 player_phys=sources(env.modDB,'PhysicalDamage'),player_attack=sources(env.modDB,'Speed',ModFlag.Attack),
 player_cast=sources(env.modDB,'Speed',ModFlag.Cast),player_move=sources(env.modDB,'MovementSpeed'),
 minion_phys=sources(env.minion and env.minion.modDB,'PhysicalDamage'),
 minion_attack=sources(env.minion and env.minion.modDB,'Speed',ModFlag.Attack),
 minion_cast=sources(env.minion and env.minion.modDB,'Speed',ModFlag.Cast),
 minion_move_stat=sources(env.minion and env.minion.modDB,'MovementSpeed'),
 chill_hit=m.CompanionChillHitCandidate,chill_crit=m.CompanionChillCritCandidate,
 chill_chance=m.CompanionChillHitChance,chill_crit_chance=m.CompanionChillCritChance,chill_min=m.CompanionChillMinimum,
 player_chill=out.CompanionChillMinimum,full_dps=out.FullDPS}))
''')

    def run(root, states=None, config_input=None, *, fixture_flags=(), fixture_avoid=None):
        env=dict(os.environ)
        env['LUA_PATH']=str(engine/'runtime/lua/?.lua')+';'+str(engine/'runtime/lua/?/init.lua')+';;'
        request={'xml':ET.tostring(root,encoding='unicode'),'module':str(MODULE)}
        if states is not None: request['configuration']={'companion_aura_sources':states}
        if config_input is not None: request['config_input']=config_input
        request['fixture_flags']=fixture_flags
        if fixture_avoid is not None: request['fixture_avoid']=fixture_avoid
        result=subprocess.run([os.environ.get('POE2_TEST_LUAJIT','luajit'),str(script)],cwd=engine/'src',env=env,
            input=json.dumps(request),capture_output=True,text=True,timeout=45)
        assert result.returncode == 0, result.stderr[-3000:]
        return json.loads(result.stdout)
    return run


def source(group,*,alive=True,player=False,recipients=()):
    return {'skill_group':group,'source_alive':alive,'player_within_radius':player,
            'minion_recipients':[{'skill_group':g,'within_radius':r} for g,r in recipients]}


def setup(*,selected=1,aura='PlayerMonsterPhysicalDamageAura1'):
    root=synthetic()
    gem=captured_beast(root)
    if aura=='PlayerMonsterIncreasedSpeedAura1':
        beast='Metadata/Monsters/GoreCharger/GoreCharger'
        root.find('./Build/BeastCompanion').set('id',beast)
        gem.set('skillMinion',beast)
    beast_modifier(gem,aura)
    skill(root,'Wild Protector','WildProtectorPlayer',level=20)
    root.find('Build').set('mainSocketGroup',str(selected))
    return root


def aura_row(result):
    return next(r for r in result['mechanics'] if r['mechanic']=='companion_ally_auras')


def metrics(result):
    return {m['name']:m['value'] for m in aura_row(result)['metrics']}


def test_beast_aura_requires_spatial_state_and_preserves_self_modifier(calculate_auras):
    root=setup()
    baseline=calculate_auras(root)
    outside=calculate_auras(root,[source(1,recipients=[(2,False)])])
    own=calculate_auras(root,[source(1,player=True,recipients=[(1,True),(2,False)])])
    assert baseline['minion_phys']==40
    assert own['minion_phys']==baseline['minion_phys']
    assert outside['player_phys']==baseline['player_phys']
    assert own['player_phys']==baseline['player_phys']+40
    assert aura_row(baseline)['status']=='partial'
    assert baseline['issues']==[{'code':'missing_combat_assumption'}]
    assert aura_row(outside)['status']=='calculated'


def test_player_and_selected_minion_recipients_are_independent(calculate_auras):
    root=setup(selected=2)
    base=calculate_auras(root,[source(1,player=False,recipients=[(2,False)])])
    player=calculate_auras(root,[source(1,player=True,recipients=[(2,False)])])
    minion=calculate_auras(root,[source(1,player=False,recipients=[(2,True)])])
    assert player['player_phys']==base['player_phys']+40
    assert player['minion_dps']==base['minion_dps']
    assert minion['player_phys']==base['player_phys']
    assert minion['minion_phys']==base['minion_phys']+40
    assert minion['minion_dps']>base['minion_dps']
    assert metrics(minion)['minion_beast_aura_physical_damage_increase']==40


def test_dead_source_disables_all_emitted_auras(calculate_auras):
    root=setup(selected=2)
    alive=calculate_auras(root,[source(1,player=True,recipients=[(2,True)])])
    dead=calculate_auras(root,[source(1,alive=False,player=True,recipients=[(2,True)])])
    assert alive['player_phys']==dead['player_phys']+40
    assert alive['minion_phys']==dead['minion_phys']+40
    assert metrics(dead)['companion_aura_sources_alive']==0


def test_haste_owner_and_ally_values_are_distinct(calculate_auras):
    owner=setup(aura='PlayerMonsterIncreasedSpeedAura1')
    own=calculate_auras(owner,[source(1,player=True,recipients=[(1,True)])])
    ally=setup(aura='PlayerMonsterIncreasedSpeedAura1',selected=2)
    off=calculate_auras(ally,[source(1,recipients=[(2,False)])])
    on=calculate_auras(ally,[source(1,player=True,recipients=[(2,True)])])
    assert own['minion_attack']>=25
    assert own['minion_move_stat']>=25
    assert on['minion_attack']==off['minion_attack']+20
    assert on['minion_cast']==off['minion_cast']+20
    assert on['minion_move_stat']==off['minion_move_stat']+10
    assert on['player_attack']==off['player_attack']+20
    assert on['player_cast']==off['player_cast']+20
    assert on['player_move']==off['player_move']+10
    assert on['minion_dps']>off['minion_dps']


def test_same_type_auras_do_not_stack(calculate_auras):
    root=setup(selected=2)
    other=captured_beast(root)
    beast_modifier(other,'PlayerMonsterPhysicalDamageAura1')
    one=calculate_auras(root,[source(1,player=True,recipients=[(2,True)]),source(3,alive=False)])
    two=calculate_auras(root,[source(1,player=True,recipients=[(2,True)]),source(3,player=True,recipients=[(2,True)])])
    assert one['player_phys']==two['player_phys']
    assert one['minion_phys']==two['minion_phys']
    assert one['minion_dps']==two['minion_dps']
    assert metrics(two)['companion_aura_sources_alive']==2


def test_disabled_source_cannot_project_buff(calculate_auras):
    root=setup(selected=2)
    active=calculate_auras(root,[source(1,player=True,recipients=[(2,True)])])
    root.find('./Skills/SkillSet/Skill').set('enabled','false')
    disabled=calculate_auras(root)
    assert active['minion_phys']==disabled['minion_phys']+40
    assert not any(r['mechanic']=='companion_ally_auras' for r in disabled['mechanics'])


def test_no_source_or_non_minion_recipient_stays_unresolved(calculate_auras):
    root=setup(selected=2)
    root.find('./Skills/SkillSet/Skill/Gem').remove(root.find('./Skills/SkillSet/Skill/Gem/TamedBeastMod'))
    result=calculate_auras(root,[source(1,player=True,recipients=[(2,True)])])
    assert aura_row(result)['status']=='partial'
    assert metrics(result)['player_beast_aura_physical_damage_increase']==0


def test_all_damage_chill_candidate_is_scoped_and_honours_cannot_chill(calculate_auras):
    root=setup(aura='PlayerMonsterFreezeDamageIncrease1')
    result=calculate_auras(root)
    assert result['chill_min']==10
    assert result['chill_hit']>=10
    assert result.get('player_chill') is None
    chill=next(r for r in result['mechanics'] if r['mechanic']=='companion_chill')
    assert chill['status']=='partial'
    # Native skill-scoped prohibition must override the broad all-damage flags.
    group=root.find('./Skills/SkillSet/Skill')
    ET.SubElement(group,'Gem',{'nameSpec':'Elemental Focus','skillId':'SupportElementalFocusPlayer','level':'1','quality':'0','enabled':'true'})
    blocked=calculate_auras(root)
    assert blocked['chill_hit']==0
    assert blocked['chill_crit']==0


def test_recipient_aura_effect_scales_and_rounds_natively(calculate_auras):
    root=setup(aura='PlayerMonsterIncreasedSpeedAura1',selected=2)
    states=[source(1,player=True,recipients=[(2,True)])]
    base=calculate_auras(root,states)
    modifiers(root,['17% increased effect of Auras on you','31% increased effect of Auras on your Minions'])
    scaled=calculate_auras(root,states)
    assert scaled['player_attack']==base['player_attack']+3  # floor(20*1.17)=23
    assert scaled['player_move']==base['player_move']+1  # floor(10*1.17)=11
    assert scaled['minion_attack']==base['minion_attack']+6  # floor(20*1.31)=26
    assert scaled['minion_move_stat']==base['minion_move_stat']+3


def test_missing_active_minion_recipient_stays_partial(calculate_auras):
    root=setup(selected=2)
    absent=calculate_auras(root,[source(1,player=True)])
    outside=calculate_auras(root,[source(1,player=True,recipients=[(2,False)])])
    assert aura_row(absent)['status']=='partial'
    assert aura_row(outside)['status']=='calculated'
    assert absent['minion_dps']==outside['minion_dps']


def test_chill_prohibition_avoidance_and_noncritical_ailment_mode(calculate_auras):
    root=setup(aura='PlayerMonsterFreezeDamageIncrease1')
    normal=calculate_auras(root,config_input={'enemyLevel':1})
    assert normal['chill_chance']>0
    avoided=calculate_auras(root,config_input={'enemyLevel':1},fixture_avoid=100)
    assert avoided['chill_chance']==0
    assert avoided['chill_crit_chance']==0
    blocked=calculate_auras(root,fixture_flags=['PhysicalCannotChill'])
    assert blocked['chill_hit']==0
    assert blocked['chill_crit']==0
    root.find('./Skills/SkillSet/Skill/Gem').set('level','1')
    ordinary=calculate_auras(root,fixture_flags=['AilmentsAreNeverFromCrit'])
    assert ordinary['chill_hit']>0
    assert ordinary['chill_crit']==ordinary['chill_hit']
