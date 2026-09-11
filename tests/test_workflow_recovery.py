"""Independent arithmetic oracles for deficit, interruptions and expiry."""
from poe2_companion.recovery import RecoveryRequest,integrate,analyze
from poe2_companion.engine_models import EngineSnapshot

CID='calc_'+'1'*32


def request(**values):
    data={'calculation_id':CID,'scenario':'custom','duration_seconds':3.,
        'resources':[{'resource':'energy_shield','maximum':100.,'initial':100.,
            'regeneration_per_second':0.,'recharge_per_second':50.,'recharge_delay_seconds':2.}]}
    data.update(values)
    return RecoveryRequest.model_validate(data)


def test_hits_reset_recharge_and_recovery_never_exceeds_deficit():
    one=request(incoming_hits=[{'at':0.,'resource':'energy_shield','post_mitigation_damage':80.}])
    result=integrate(one,True).outcomes[0]
    assert result.minimum==20 and result.final==70 and result.effective_recovery==50
    repeated=request(scenario='ritual',incoming_hits=[{'at':float(t),'resource':'energy_shield','post_mitigation_damage':30.} for t in range(3)])
    result=integrate(repeated,True).outcomes[0]
    assert result.final==10 and result.recharge_active_seconds==0
    full=integrate(request(),True).outcomes[0]
    assert full.final==100 and full.effective_recovery==0 and full.wasted_recovery==150


def test_full_mana_unknown_expiry_has_materially_different_affordability():
    query=request(resources=[{'resource':'mana','maximum':100.,'initial':100.,'regeneration_per_second':0.}],
        attacks=[{'at':1.,'mana_cost':100.},{'at':2.,'mana_cost':50.}],
        flows=[{'kind':'leech','resource':'mana','producer':'player','recipient':'player',
            'source_skill_instance_id':'skill:s1:g1:n1','starts_at':0.,'ends_at':3.,'potential_per_second':50.}])
    assert integrate(query,True).affordable_attacks==1
    assert integrate(query,False).affordable_attacks==2
    snapshot=EngineSnapshot(stats=[],equipped=[],issues=[],issue_count=0,validation='pass',active_weapon_set=1,main_skill_group=1,
        subject={'status':'matched','scenario_digest':'a'*64,
            'requested':{'skill_instance_id':'skill:s1:g1:n1','actor_ref':'player','weapon_set_id':1},
            'evaluated':{'skill_instance_id':'skill:s1:g1:n1',
            'skill_id':'FireballPlayer','actor_ref':'player','component_ref':'FireballPlayer','weapon_set_id':1}})
    result=analyze(query,snapshot)
    assert len(result.cases)==2 and 'mana_leech_expiry_unknown' in result.uncertainty
    wrong=query.model_copy(deep=True);wrong.flows[0].source_skill_instance_id='skill:s1:g2:n1'
    assert analyze(wrong,snapshot).status=='subject_mismatch'


def test_removing_both_buffer_and_recovery_increases_loss():
    hits=[{'at':float(t),'resource':'energy_shield','post_mitigation_damage':30.} for t in range(3)]
    original=request(resources=[{'resource':'energy_shield','maximum':100.,'initial':100.,'regeneration_per_second':20.}],incoming_hits=hits)
    changed=request(resources=[{'resource':'energy_shield','maximum':50.,'initial':50.,'regeneration_per_second':0.}],incoming_hits=hits)
    assert integrate(original,True).outcomes[0].damage_exceeding_available_resource==0
    assert integrate(changed,True).outcomes[0].damage_exceeding_available_resource==40
