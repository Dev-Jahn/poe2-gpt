"""Source-integrated and analytical hypothetical charge/recoup regression cases."""
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest
from pydantic import ValidationError

from poe2_companion.combat_models import CombatScenario, CombatScenarioResult
from test_stonefist_real import synthetic

ROOT = Path(__file__).parents[1]
MODULE = ROOT / 'src/poe2_companion/lua/charge_scenarios.lua'
STONEFIST = ROOT / 'src/poe2_companion/lua/stonefist.lua'


def scenario(events=(), *, initial=0, remaining=15, horizon=20, phase=None, rolls='independent_nonrecursive_per_event'):
    data = dict(horizon_seconds=horizon, gain_roll_model=rolls,
                initial_charges={'power': {'count': initial, 'remaining_seconds': remaining if initial else 0}},
                events=list(events))
    if phase is not None:
        data['regulation_first_tick_seconds'] = phase
    return CombatScenario.model_validate(data).model_dump(mode='json', exclude_none=True)


def gain(at, amount=1, kind='power'):
    return dict(kind='external_charge_gain', at_seconds=at, charge_type=kind, amount=amount)


def flicker(at, duration=1, group=1):
    return dict(kind='flicker_use', at_seconds=at, duration_seconds=duration, skill_group=group)


def parameters(**updates):
    result = dict(charges={kind: dict(maximum=6, minimum=0, duration=15, extra=0, ally_grant=0)
                           for kind in ('power', 'frenzy', 'endurance')},
                  skills={1: dict(kind='flicker', retention=.35, power_gain_lockout=True,
                                  strikes_per_charge=2, virtual_charges=1, double_effect=.2)},
                  recoup_duration=8, life_recovery=1, deflected_recoup=.15)
    result.update(updates)
    return result


def projection(row, kind='power'):
    return next(c for c in row['charges'] if c['charge_type'] == kind)


@pytest.fixture
def run_machine(tmp_path):
    source = os.environ.get('POE2_TEST_ENGINE_DIR')
    if not source:
        pytest.skip('Set POE2_TEST_ENGINE_DIR to run real PoE2 LuaJIT integration')
    script = tmp_path / 'machine.lua'
    script.write_text("local json=require('dkjson');local input=json.decode(io.stdin:read('*a'));local m=dofile(input.module);local r={};for _,c in ipairs(input.cases) do local skills={};for k,v in pairs(c.parameters.skills or {}) do skills[tonumber(k)]=v end;c.parameters.skills=skills;r[#r+1]=m.run(c.parameters,c.scenario) end;io.write(json.encode(r))")
    def run(cases):
        env = {**os.environ, 'LUA_PATH': str(Path(source) / 'runtime/lua/?.lua') + ';;'}
        result = subprocess.run([os.environ.get('POE2_TEST_LUAJIT', 'luajit'), str(script)],
                                input=json.dumps(dict(module=str(MODULE), cases=cases)),
                                text=True, capture_output=True, env=env, timeout=20)
        assert result.returncode == 0, result.stderr[-1500:]
        rows = json.loads(result.stdout)
        for row in rows:
            CombatScenarioResult.model_validate(row)
        return rows
    return run


def test_scenario_models_reject_payloads_unsorted_overlap_and_unknown_fields():
    for data in [dict(horizon_seconds=10, gain_roll_model='raw_export'),
                 dict(horizon_seconds=10, gain_roll_model='independent_nonrecursive_per_event', xml='private'),
                 dict(horizon_seconds=10, gain_roll_model='independent_nonrecursive_per_event', events=[gain(5), gain(4)]),
                 dict(horizon_seconds=10, gain_roll_model='independent_nonrecursive_per_event', events=[flicker(0,2), flicker(1)]),
                 dict(horizon_seconds=10, gain_roll_model='independent_nonrecursive_per_event', initial_charges={'power': {'count': 1}}),
                 dict(horizon_seconds=10, gain_roll_model='independent_nonrecursive_per_event', events=[gain(0)]*65)]:
        with pytest.raises(ValidationError):
            CombatScenario.model_validate(data)


def test_exact_retention_power_lockout_and_virtual_charges(run_machine):
    row = run_machine([dict(parameters=parameters(), scenario=scenario(
        [flicker(0,2),gain(1,2),gain(2)], initial=6, horizon=3))])[0]
    charge=projection(row)
    assert row['status']=='calculated'
    assert charge['expected_removed']==pytest.approx(3.9)
    assert charge['expected_generated']==3
    assert charge['expected_blocked']==2
    assert charge['expected_wasted_at_cap']==pytest.approx(.35)
    assert charge['expected_final']==pytest.approx(2.75)
    assert row['flicker']['expected_charges_counted']==7
    assert row['flicker']['expected_strikes']==pytest.approx(17.8)
    assert row['snapshot_dps_unchanged']


def test_expiry_refresh_at_cap_regulation_phase_and_minimum(run_machine):
    p=parameters();p['regulation']=dict(interval=10,retention=0)
    missing, ticks, refreshed = run_machine([
        dict(parameters=p, scenario=scenario(initial=3,horizon=25)),
        dict(parameters=p, scenario=scenario(initial=3,remaining=15,horizon=25,phase=10)),
        dict(parameters=parameters(), scenario=scenario([gain(14,3)], initial=6, horizon=20))])
    assert missing['status']=='unsupported' and missing['issues']==['missing_regulation_phase']
    assert projection(ticks)['expected_removed']==1
    assert projection(ticks)['expected_expired']==2
    assert projection(ticks)['expected_seconds_nonzero']==15
    assert projection(refreshed)['expected_final']==6
    assert projection(refreshed)['expected_wasted_at_cap']==3
    assert projection(refreshed)['expected_seconds_nonzero']==20
    p=parameters();p['charges']['power']['minimum']=2
    row=run_machine([dict(parameters=p,scenario=scenario([flicker(0)],initial=6,horizon=20))])[0]
    assert projection(row)['expected_final']==pytest.approx(2)
    assert projection(row)['expected_removed']==pytest.approx(2.6)
    assert projection(row)['expected_expired']==pytest.approx(1.4)
    assert projection(row)['expected_seconds_nonzero']==20


def test_profusion_marginals_and_explicit_bonus_roll_models(run_machine):
    p=parameters();p['charges']['power']['maximum']=20;p['charges']['power']['extra']=.1
    p['skills'][2]=dict(kind='killing_palm',gains=dict(normal_magic=1,rare=2,unique=3),extra=.3,random_extra=.15)
    event=dict(kind='killing_palm_kill',at_seconds=0,skill_group=2,rarity='rare')
    rows=run_machine([dict(parameters=p,scenario=scenario([event],horizon=1,rolls=roll)) for roll in
                      ('independent_nonrecursive_per_event','independent_nonrecursive_per_base_charge')])
    assert projection(rows[0])['expected_final']==pytest.approx(2.45)
    assert projection(rows[1])['expected_final']==pytest.approx(2.9)
    assert projection(rows[0],'frenzy')['expected_final']==pytest.approx(.05)
    assert projection(rows[1],'endurance')['expected_final']==pytest.approx(.1)
    for row in rows:
        for charge in row['charges']:
            assert charge['expected_final']==pytest.approx(charge['expected_generated']-charge['expected_wasted_at_cap'])


def test_allies_are_separate_grant_attempts_and_recoup_is_postmitigation(run_machine):
    p=parameters();p['charges']['power']['ally_grant']=.08;p['charges']['frenzy']['ally_grant']=.06
    p['skills'][3]=dict(kind='companion',recoup=2)
    p['life_recovery']=1.5;p['deflected_recoup']=.225
    rows=run_machine([dict(parameters=p,scenario=scenario([
        dict(kind='ally_hit',at_seconds=0,allies_in_presence=True),
        dict(kind='incoming_hit',at_seconds=0,damage_taken=1000,deflected=True),
        dict(kind='incoming_hit',at_seconds=1,damage_taken=999999,deflected=False),
        dict(kind='ally_hit',at_seconds=1,allies_in_presence=False),
        dict(kind='companion_redirected_hit',at_seconds=2,skill_group=3,damage_taken=100),
    ],horizon=4))])
    row=rows[0]
    assert projection(row)['expected_final']==0
    assert row['ally_grants'][0]['expected_grants_per_eligible_ally']==pytest.approx(.08)
    assert row['deflected_recoup']['potential_total']==225
    assert row['deflected_recoup']['potential_by_horizon']==112.5
    assert row['deflected_recoup']['potential_per_second_at_horizon']==28.125
    assert row['companion_recoup']['potential_total']==300
    assert row['companion_recoup']['potential_by_horizon']==75


def test_inhibitor_no_virtual_bonus_without_real_charge_and_tied_expiry(run_machine):
    inhibited=parameters();inhibited['skills'][1]['cannot_consume']=True
    rows=run_machine([
        dict(parameters=inhibited,scenario=scenario([flicker(0)],initial=6,horizon=1)),
        dict(parameters=parameters(),scenario=scenario([flicker(0)],horizon=1)),
        dict(parameters=parameters(),scenario=scenario([flicker(15)],initial=6,remaining=15,horizon=16)),
    ])
    for row in rows:
        assert row['flicker']['expected_strikes']==1
        assert row['flicker']['expected_charges_counted']==0
    assert projection(rows[0])['expected_final']==6
    assert projection(rows[2])['expected_expired']==6


def test_bounded_worst_case_schedule_and_lua_guard(run_machine):
    p=parameters()
    for charge in p['charges'].values(): charge.update(maximum=20,extra=.5)
    p['skills'][2]=dict(kind='killing_palm',gains=dict(normal_magic=1,rare=2,unique=20),extra=0,random_extra=.75)
    p['regulation']=dict(interval=.01,retention=1)
    for charge in p['charges'].values(): charge['duration']=120
    events=[dict(kind='killing_palm_kill',at_seconds=i*1.5,skill_group=2,rarity='unique') for i in range(64)]
    dense=run_machine([dict(parameters=p,scenario=scenario(events,horizon=120,phase=0,rolls='independent_nonrecursive_per_base_charge'))])[0]
    assert dense['status']=='unsupported'
    assert dense['issues']==['scenario_budget_exceeded'] and not dense['charges']
    invalid=scenario(horizon=10);invalid['events']=[gain(0)]*65
    row=run_machine([dict(parameters=p,scenario=invalid)])[0]
    assert row['issues']==['invalid_combat_event_schedule'] and not row['charges']


@pytest.fixture
def run_source(tmp_path):
    source=os.environ.get('POE2_TEST_ENGINE_DIR')
    if not source: pytest.skip('Set POE2_TEST_ENGINE_DIR to run real PoE2 LuaJIT integration')
    script=tmp_path/'charge_real.lua'
    script.write_text('''
print=function() end
local json=require('dkjson');local input=json.decode(io.stdin:read('*a'))
dofile('HeadlessWrapper.lua')
local m=dofile(input.module);local result={}
for _,case in ipairs(input.cases) do
 loadBuildFromXML(case.xml,'')
 local weapon=new('Item'):Item('Rarity: RARE\\nSynthetic Weapon\\nWrapped Quarterstaff\\nImplicits: 0\\nAdds 100000 to 100000 Physical Damage')
 build.itemsTab:AddItem(weapon);build.itemsTab.slots['Weapon 1']:SetSelItemId(weapon.id)
 if case.gloves then local item=new('Item'):Item(case.gloves);build.itemsTab:AddItem(item);build.itemsTab.slots.Gloves:SetSelItemId(item.id) end
 for _,id in ipairs(case.nodes or {}) do local node=assert(build.spec.nodes[id]);node.alloc=true;node.isGrantedPassive=nil;node.isFreeAllocate=nil;build.spec.allocNodes[id]=node end
 m.apply_configuration(build,case.configuration);build.configTab.input.enemyArmour=0;build.configTab:BuildModList()
 build.buildFlag=true;runCallback('OnFrame');assert(not __mainObject__.promptMsg)
 local env,out=build.calcsTab.mainEnv,build.calcsTab.mainOutput
 local value=m.simulate(build,env,out,case.scenario)
 local mechanics=m.inspect(build,env,out)
 result[#result+1]={scenario=value,mechanics=mechanics,dps=out.CombinedDPS,native_recoup_total=out.TotalLifeRecoupRecovery,native_recoup_max=out.LifeRecoupRecoveryMax,stun_threshold=out.StunThreshold,damage_more=env.player.mainSkill.skillModList:More(env.player.mainSkill.skillCfg,'Damage'),unknown_mountain=(build.spec.allocNodes[51546] and (build.spec.allocNodes[51546].unknown or build.spec.allocNodes[51546].extra)) and true or false}
end
io.write(json.encode(result))
''')
    def run(cases):
        env={**os.environ,'LUA_PATH':str(Path(source)/'runtime/lua/?.lua')+';'+str(Path(source)/'runtime/lua/?/init.lua')+';;'}
        result=subprocess.run([os.environ.get('POE2_TEST_LUAJIT','luajit'),str(script)],cwd=Path(source)/'src',
                              input=json.dumps(dict(module=str(STONEFIST),cases=cases)),text=True,capture_output=True,env=env,timeout=85)
        assert result.returncode==0,result.stderr[-1800:]
        rows=json.loads(result.stdout)
        for row in rows: CombatScenarioResult.model_validate(row['scenario'])
        return rows
    return run


def test_real_killing_palm_rarity_support_and_disabled_group(run_source):
    cases=[]
    for rarity in ('normal_magic','rare','unique'):
        xml=synthetic(skill='KillingPalmPlayer',support='SupportChargeProfusionPlayerTwo')
        cases.append(dict(xml=xml,nodes=[36643],scenario=scenario([
            dict(kind='killing_palm_kill',at_seconds=0,skill_group=1,rarity=rarity)],horizon=1)))
    rows=run_source(cases)
    for index,row in enumerate(rows,1):
        assert row['scenario']['status']=='calculated'
        # Default maximum3 caps the unique3+bonus roll. The lower rarities fit.
        assert projection(row['scenario'])['expected_final']==pytest.approx([1.45,2.43,3][index-1])
        assert projection(row['scenario'],'frenzy')['expected_final']==pytest.approx(.05)
    root=ET.fromstring(synthetic(skill='FireballPlayer'))
    group=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'false','mainActiveSkill':'1'})
    ET.SubElement(group,'Gem',{'skillId':'KillingPalmPlayer','nameSpec':'Killing Palm','level':'1','quality':'0','enabled':'true'})
    rejected=run_source([dict(xml=ET.tostring(root).decode(),scenario=scenario([
        dict(kind='killing_palm_kill',at_seconds=0,skill_group=2,rarity='normal_magic')],horizon=1))])[0]
    assert rejected['scenario']['issues']==['invalid_scenario_skill']


def test_real_flicker_retention_quality_regulation_and_recoup_speed(run_source):
    xml=synthetic(skill='FlickerStrikePlayer',support='SupportPerpetualChargePlayer')
    root=ET.fromstring(xml)
    group=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
    ET.SubElement(group,'Gem',{'skillId':'ChargeRegulationPlayer','nameSpec':'Charge Regulation','level':'1','quality':'20','enabled':'true'})
    xml=ET.tostring(root).decode()
    gloves='Rarity: RARE\nSynthetic Gloves\nFists of Stone\nImplicits: 0\n50% increased Life Recovery Rate\n15% increased speed of Recoup Effects'
    row=run_source([dict(xml=xml,nodes=[7847,9652],gloves=gloves,scenario=scenario([
        flicker(0),gain(.5),dict(kind='incoming_hit',at_seconds=1,damage_taken=1000,deflected=True)],initial=3,horizon=14,phase=12.4))])[0]
    assert row['scenario']['status']=='calculated'
    charge=projection(row['scenario'])
    assert charge['expected_blocked']==1
    assert charge['expected_removed']==pytest.approx(1.95+.35*.9)
    assert row['scenario']['deflected_recoup']['duration_seconds']==pytest.approx(8/1.15)
    assert row['scenario']['deflected_recoup']['potential_total']==225
    assert row['scenario']['deflected_recoup']['potential_by_horizon']==225


def test_real_armour_break_charge_gain_is_support_and_skill_scoped(run_source):
    cases=[]
    for support in ('SupportArmourBreakPlayer','SupportArmourBreakPlayerTwo','SupportArmourBreakPlayerThree'):
        cases.append(dict(xml=synthetic(skill='KillingPalmPlayer',support=support),scenario=scenario([
            dict(kind='armour_fully_broken',at_seconds=0,skill_group=1)],horizon=1)))
    absent,tier2,tier3=run_source(cases)
    assert absent['scenario']['issues']==['invalid_scenario_skill']
    assert projection(tier2['scenario'],'endurance')['expected_final']==pytest.approx(.15)
    assert projection(tier3['scenario'],'endurance')['expected_final']==pytest.approx(.20)
    assert projection(tier3['scenario'])['expected_final']==0
    incompatible=run_source([dict(xml=synthetic(skill='ChargeRegulationPlayer',support='SupportArmourBreakPlayerThree'),
                                   scenario=scenario([dict(kind='armour_fully_broken',at_seconds=0,skill_group=1)],horizon=1,phase=10))])[0]
    assert incompatible['scenario']['issues']==['invalid_scenario_skill']


def test_real_recoup_speed_reduces_duration_preserving_total_and_snapshot_dps(run_source):
    base='Rarity: RARE\nSynthetic Gloves\nFists of Stone\nImplicits: 0\n50% increased Life Recovery Rate\n20% of Damage taken Recouped as Life'
    event=dict(kind='incoming_hit',at_seconds=0,damage_taken=1000,deflected=True)
    rows=run_source([dict(xml=synthetic(skill='FireballPlayer'),nodes=[9652],gloves=base+speed,
                         scenario=scenario([event],horizon=4)) for speed in ('','\n100% increased speed of Recoup Effects')])
    normal,fast=rows
    assert normal['dps']==fast['dps']
    assert normal['scenario']['deflected_recoup']['potential_total']==fast['scenario']['deflected_recoup']['potential_total']==225
    assert normal['scenario']['deflected_recoup']['potential_by_horizon']==112.5
    assert fast['scenario']['deflected_recoup']['potential_by_horizon']==225
    assert normal['native_recoup_total']==pytest.approx(fast['native_recoup_total'])
    assert fast['native_recoup_max']==pytest.approx(normal['native_recoup_max']*2)


def test_mountain_teachings_surpassing_expiry_and_pre_taken_threshold(run_machine):
    p=parameters();p['mountain']=dict(maximum=30,gain_chance=1,maximum_life=1000,duration=20)
    p['skills'][1]['mountain_attack']=True
    schedule=scenario([
        dict(kind='enemy_immobilised',at_seconds=0,enemy_power=.5),
        dict(kind='mountain_hit',at_seconds=1,damage_after_mitigation=300,other_damage_taken_multiplier=2,deflected=True),
        dict(kind='enemy_immobilised',at_seconds=2,enemy_power=2.15),
        dict(kind='mountain_hit',at_seconds=3,damage_after_mitigation=300.001,other_damage_taken_multiplier=.1,deflected=False),
        dict(kind='mountain_attack_use',at_seconds=4,skill_group=1),
    ],horizon=25)
    row=run_machine([dict(parameters=p,scenario=schedule)])[0]
    m=row['mountain_teachings']
    assert row['status']=='calculated'
    assert m['expected_generated']==pytest.approx(2.65)
    assert m['expected_removed']==pytest.approx(2.5)
    assert m['expected_expired']==pytest.approx(.15)
    assert m['expected_damage_prevented']==pytest.approx(120)
    assert m['expected_damage_taken']==pytest.approx(480+30.0001)
    assert m['expected_attacks_benefiting']==1
    assert m['expected_final']==0
    assert row['deflected_recoup']['potential_total']==pytest.approx(480*.15)
    # Cap refresh and time-tied expiry are source rules, not averaged rates.
    schedule=scenario([dict(kind='enemy_immobilised',at_seconds=19,enemy_power=20)],horizon=25)
    schedule['initial_mountain_teachings']=dict(count=30,remaining_seconds=20)
    row=run_machine([dict(parameters=p,scenario=schedule)])[0]
    assert row['mountain_teachings']['expected_wasted_at_cap']==20
    assert row['mountain_teachings']['expected_final']==30


def test_real_mountain_snapshot_native_damage_stun_and_spell_exclusion(run_source):
    cases=[]
    for skill in ('KillingPalmPlayer','FireballPlayer'):
        for stacks in (0,1,30):
            cases.append(dict(xml=synthetic(skill=skill),nodes=[51546],configuration={'mountain_teachings':stacks},scenario=scenario(horizon=1)))
    rows=run_source(cases)
    off,on,full,spell_off,spell_on,spell_full=rows
    assert not any(row['unknown_mountain'] for row in rows)
    assert on['damage_more']==pytest.approx(off['damage_more']*1.15)
    assert on['dps']==pytest.approx(off['dps']*1.15,rel=.001)
    assert full['dps']==pytest.approx(on['dps'])
    assert on['stun_threshold']==pytest.approx(off['stun_threshold']*1.5,abs=1)
    assert spell_off['dps']==spell_on['dps']==spell_full['dps']
    assert spell_on['stun_threshold']==pytest.approx(spell_off['stun_threshold']*1.5,abs=1)


def test_real_mountain_hollow_form_copies_receive_bonus_once(run_source):
    from test_martial_mechanics_real import synthetic as martial_synthetic
    xml=martial_synthetic('MetaHollowFormPlayer',clone='StormWavePlayer')
    rows=run_source([dict(xml=xml,nodes=[51546],configuration={'mountain_teachings':stacks},scenario=scenario(horizon=1)) for stacks in (0,1)])
    assert rows[0]['dps']>0
    assert rows[1]['damage_more']==pytest.approx(rows[0]['damage_more']*1.15)
    assert rows[1]['dps']==pytest.approx(rows[0]['dps']*1.15,rel=.001)


def test_real_romira_schedule_uses_eligible_companion_support_only(run_source):
    event=dict(kind='companion_redirected_hit',at_seconds=0,skill_group=1,damage_taken=100)
    xml=synthetic(skill='WildProtectorPlayer',support='SupportRomirasRequitalPlayer')
    disabled=ET.fromstring(xml)
    disabled.find('./Skills/SkillSet/Skill/Gem[@skillId="SupportRomirasRequitalPlayer"]').set('enabled','false')
    enabled,rejected=run_source([dict(xml=body,scenario=scenario([event],horizon=4))
                                for body in (xml,ET.tostring(disabled).decode())])
    assert enabled['scenario']['status']=='calculated'
    assert enabled['scenario']['companion_recoup']['potential_total']==200
    assert enabled['scenario']['companion_recoup']['potential_by_horizon']==100
    assert enabled['scenario']['deflected_recoup']['potential_total']==0
    assert rejected['scenario']['issues']==['invalid_scenario_skill']


def test_real_flicker_alternate_quality_and_inhibitor_are_scoped(run_source):
    cases=[]
    for alt,support in ((False,'SupportPerpetualChargePlayer'),(True,'SupportPerpetualChargePlayer'),(True,'SupportChargeInhibitionPlayer')):
        xml=synthetic(skill='FlickerStrikePlayer',quality=20,support=support)
        # Alternate quality requires Advanced Thaumaturgy; it is not a config toggle.
        cases.append(dict(xml=xml,nodes=[7847]+([14429] if alt else []),scenario=scenario([flicker(0)],initial=3,horizon=1)))
    normal,alternate,inhibited=run_source(cases)
    assert projection(normal['scenario'])['expected_removed']==pytest.approx(1.95)
    assert projection(alternate['scenario'])['expected_removed']==pytest.approx(1.35)
    assert projection(inhibited['scenario'])['expected_removed']==0
    assert inhibited['scenario']['flicker']['expected_strikes']==1
