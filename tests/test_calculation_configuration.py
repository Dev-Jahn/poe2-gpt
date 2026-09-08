"""Public assumptions retain uncertainty and cross the private boundary intact."""
import json
import time
from typing import get_args

import httpx
import pytest
from pydantic import ValidationError

from poe2_companion.calculation_config import CalculationConfiguration
from poe2_companion.combat_models import CombatScenarioResult, ChargeProjection
from poe2_companion.engine import EngineClient, bounded_engine_dto
from poe2_companion.engine_models import (EngineRequest, CompareRequest, EngineTradeRequest,
    EngineSnapshot, EngineCalculation, SelectedSkill, EquippedItem, EngineSlot)
from poe2_companion.engine_protocol import WorkerResult
from poe2_companion.builds import STAT_NAMES
from poe2_companion.trade import TradeClient, TradeSearchRequest, parse_listing
from test_engine_real import BID, MARKER, item


def snapshot(validation='pass', life=100):
    return EngineSnapshot(stats=[{'name':'Life','value':life}],equipped=[],issues=[],issue_count=0,
        validation=validation,active_weapon_set=1,main_skill_group=0)


@pytest.mark.parametrize('data',[
    {'pob_code':MARKER}, {'spirit_vessel_skill_id':'../private'},
    {'captured_beast_mods':[{'skill_group':1,'mod_ids':['PlayerMonsterA','PlayerMonsterA'],'complete':True}]},
    {'captured_beast_mods':[{'skill_group':1,'mod_ids':[],'complete':True}]*2},
    {'hollow_form_channel_uses_per_second':1}, {'refutation_active':True},
    {'tempest_bell_ailment_types':['fire','fire']}, {'impale_magnitude':float('inf')},
    {'mountain_teachings':31}, {'leech_resistance_percent':101},
])
def test_configuration_is_closed_and_coherent(data):
    with pytest.raises(ValidationError) as err:
        CalculationConfiguration.model_validate(data)
    assert MARKER not in str(err.value)


@pytest.mark.parametrize('compare',[False,True])
async def test_configuration_false_zero_and_combat_schedule_reach_worker(compare):
    seen=[]
    config={'ghost_shroud_lost_recently':False,'impale_magnitude':0,'wind_dancer_stages':0}
    combat={'horizon_seconds':2,'gain_roll_model':'independent_nonrecursive_per_event','events':[]}
    def respond(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200,json=WorkerResult(baseline=snapshot(),results=[snapshot()] if compare else []).model_dump())
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.MockTransport(respond),base_url='http://worker'))
    try:
        cls=CompareRequest if compare else EngineRequest
        request=cls(build_id=BID,configuration=config,combat_scenario=combat,
            **({'replacements':[{'slot':'helmet','saved_item_id':0}]} if compare else {}))
        result=await client.calculate(request)
        assert seen[0]['configuration']==config
        assert seen[0]['combat_scenario']['events']==[]
        assert result.scope=='explicit_configuration_active_weapon_set'
        assert set(result.configuration_fields)==set(config)
        assert (result.result is not None)==compare
    finally:
        await client.close()


async def test_unknown_baseline_cannot_turn_into_verified_trade_upgrade():
    seen=[]
    def respond(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200,json=WorkerResult(baseline=snapshot('indeterminate'),
            results=[snapshot(life=1000) for _ in seen[-1]['scenarios']]).model_dump())
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.MockTransport(respond),base_url='http://worker'))
    trade=TradeClient(user_agent='synthetic-test')
    sid='ts_'+'2'*32
    raw=item();ref='a'*64
    row=parse_listing({'id':ref,'item':raw,'listing':{'price':{'amount':1,'currency':'divine'}}},int(time.time()))
    trade.searches[sid]={'request':TradeSearchRequest(category='accessory.ring'),'created':int(time.time()),
        'ids':[ref],'rows':{ref:row},'engine_items':{ref:raw}}
    try:
        result=await client.recommend(EngineTradeRequest(build_id=BID,search_ids=[sid],
            budget={'amount':1,'currency':'divine'},weights=[{'stat':'Life','weight':1}],
            configuration={'onslaught_active':False},
            combat_scenario={'horizon_seconds':2,'gain_roll_model':'independent_nonrecursive_per_event','events':[]}),trade,None)
        assert not result.feasible and not result.changes and result.score_gain==0
        assert result.indeterminate_combinations==3
        assert result.calculation.baseline.validation=='indeterminate'
        assert seen[0]['configuration']=={'onslaught_active':False}
        assert seen[0]['combat_scenario']['horizon_seconds']==2
        assert seen[0]['combat_scenario']['events']==[]
        assert result.calculation.configuration_fields==['onslaught_active']
    finally:
        await client.close();await trade.close()


def test_dense_scenarios_bound_output_without_claiming_missing_results():
    fields=ChargeProjection.model_fields
    charges=[ChargeProjection(**{**{name:1e10 for name in fields if name not in
        {'charge_type','maximum','probability_nonzero_at_end'}},'charge_type':kind,'maximum':20,
        'probability_nonzero_at_end':.123456789012345}) for kind in ('power','frenzy','endurance')]
    scenario=CombatScenarioResult(status='calculated',horizon_seconds=120,
        gain_roll_model='independent_nonrecursive_per_base_charge',assumptions=[],charges=charges)
    s=snapshot('indeterminate')
    from poe2_companion.builds import PlayerStat
    s.stats=[PlayerStat(name=name,value=1e15) for name in sorted(STAT_NAMES)]
    s.equipped=[EquippedItem(slot=slot,saved_item_id=1000000,level_required=100) for slot in get_args(EngineSlot)]
    s.selected_skill=SelectedSkill(skill_id='A'*120,name='B'*120,gem_name='C'*120,actor='minion',
        name_ko='가'*160,name_source_ko='https://poe2db.tw/kr/'+'a'*200)
    s.combat_scenario=scenario;s.combat_scenario_status='calculated'
    value=EngineCalculation(build_id=BID,calculated_at_epoch=1,baseline=s,result=s,deltas=s.stats)
    result=bounded_engine_dto(value)
    assert len(result.model_dump_json().encode())<=8192
    assert any(v.combat_scenario_truncated for v in (result.baseline,result.result))
    for row in (result.baseline,result.result):
        assert row.validation=='indeterminate' and row.combat_scenario_status=='calculated'
        assert row.stats==s.stats
    assert value.baseline.combat_scenario is not None
