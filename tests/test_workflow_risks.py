from poe2_companion.engine_models import EngineSnapshot
from poe2_companion.risk_analysis import RiskRequest,analyze


def snapshot():
    return EngineSnapshot(stats=[{'name':'CritChance','value':0.},{'name':'EnergyShield','value':1000.}],
        equipped=[],issues=[{'code':'missing_combat_assumption'}],issue_count=1,validation='indeterminate',
        active_weapon_set=1,main_skill_group=1,
        metric_coverage=[{'stat':'EnergyShield','status':'pass','reason':'unconditional_resource_dependency_verified'}],
        mechanics=[{'mechanic':'hit_effects','status':'calculated','metrics':[{'name':'cannot_inflict_blind','value':1.}]}],
        subject={'status':'matched','scenario_digest':'a'*64,
            'requested':{'skill_instance_id':'skill:s1:g1:n1','actor_ref':'player','weapon_set_id':1},
            'evaluated':{'skill_instance_id':'skill:s1:g1:n1','skill_id':'FireballPlayer',
                'actor_ref':'player','weapon_set_id':1,'component_ref':'FireballPlayer'}})


def test_critical_proxy_and_blind_rules_are_scoped_not_global():
    request=RiskRequest(calculation_id='calc_'+'1'*32,intended_rules=['critical_event_requires_nonzero_chance',
        'player_kill_requires_player_credit','self_blind_requires_infliction'],kill_credit_actor='hollow_image',blind_source='self')
    result=analyze(request,snapshot())
    assert [f.status for f in result.findings]==['blocked','blocked','blocked']
    assert next(m for m in result.metrics if m.name=='EnergyShield').coverage=='certified_for_snapshot'
    assert result.effect_graph[0].event_owner=='hollow_image'
    assert not result.certified and result.global_confidence_score is None
    request.blind_source='other_actor'
    assert analyze(request,snapshot()).findings[-1].reason=='external_blind_is_separate'


def test_converted_supply_cannot_feed_original_charge_consumer():
    request=RiskRequest(calculation_id='calc_'+'1'*32,intended_rules=['charge_consumer_requires_matching_supply'],
        consumed_charge_type='power',required_charge_events_per_second=1.,charge_supplies=[{
            'producer':'player','recipient':'player','generated_type':'power','converted_type':'endurance','events_per_second':10.}])
    result=analyze(request,snapshot())
    assert result.findings[0].reason=='charge_supply_missing'
    assert result.effect_graph[0].resource_after=='endurance'
    assert result.findings[0].evidence_scope=='supplied_event_hypothesis'


def test_native_self_conflicts_are_reported_without_manually_requesting_rules():
    result=analyze(RiskRequest(calculation_id='calc_'+'1'*32),snapshot())
    assert {f.rule_id for f in result.findings}=={'critical_event_requires_nonzero_chance','self_blind_requires_infliction'}
    assert all(f.triggered_by=='native_snapshot_condition' for f in result.findings)
    blind=next(f for f in result.findings if f.rule_id=='self_blind_requires_infliction')
    assert blind.reason=='blind_source_unknown' and blind.status=='conditional'
    assert next(m for m in result.metrics if m.name=='EnergyShield').coverage=='certified_for_snapshot'


def test_guaranteed_target_exception_is_a_separate_unproven_scenario():
    query=RiskRequest(calculation_id='calc_'+'1'*32,intended_rules=['critical_event_requires_nonzero_chance'],
        automatic_checks=False,guaranteed_critical_target_exception=True)
    result=analyze(query,snapshot())
    assert result.findings[0].status=='conditional'
    assert result.findings[0].reason=='guaranteed_target_exception_requires_native_scenario'
    assert not result.certified


def test_full_effect_graph_is_losslessly_paged_under_ordinary_json_limit():
    from poe2_companion.builds import tool_json_bytes
    query=RiskRequest(calculation_id='calc_'+'1'*32,intended_rules=['critical_event_requires_nonzero_chance',
        'player_kill_requires_player_credit','self_blind_requires_infliction','charge_consumer_requires_matching_supply'],
        kill_credit_actor='spirit_vessel',blind_source='self',effect_limit=16,
        charge_supplies=[{'producer':'spirit_vessel','recipient':'spirit_vessel','generated_type':'endurance','converted_type':'power','events_per_second':9999.9999999}]*16)
    edges=[]
    while True:
        result=analyze(query,snapshot());assert tool_json_bytes(result)<=8192
        edges+=result.effect_graph
        if result.next_effect_offset is None:break
        assert result.next_effect_offset>query.effect_offset;query.effect_offset=result.next_effect_offset
    assert len(edges)==result.effect_graph_total==17
