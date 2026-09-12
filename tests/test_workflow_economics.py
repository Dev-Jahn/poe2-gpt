"""Independent arithmetic and retained market evidence for tickets 021/023."""
import time
import httpx
import pytest
from pydantic import ValidationError
from poe2_companion.map_analysis import (MapRequest,analyze,RunObservationRequest,record,profit,ProfitRequest)
from poe2_companion.value_analysis import (CraftRequest,crafting,SaleRequest,sale,RewardRequest,rewards)
from poe2_companion.workflow_store import DecisionStore,WorkflowError
from poe2_companion.trade import TradeClient,TradeSearchRequest
from test_trade import TradeBackend,listing
from test_scout import client,fixture
from test_equipment import NOW
from test_workflow_recovery import request as recovery_request


def test_same_tier_map_has_different_recovery_risk_and_no_ritual_no_hit_preset():
    normal=analyze(MapRequest(tier=15,encounter='mapping',game_patch='0.5.5'))
    reduced=analyze(MapRequest(tier=15,encounter='mapping',game_patch='0.5.5',modifiers=[{
        'rule_id':'map:less_life_es_recovery','magnitude_percent':35.,'evidence':'user_transcribed_item'}]))
    assert normal.tier==reduced.tier and not normal.safe_from_tier_alone
    assert not normal.interactions and reduced.interactions[0].status=='source_semantics_matched'
    assert not reduced.interactions[0].native_roll_table_reused and not reduced.map_rule_patch_certified
    assert 'compare_deficit_limited_recovery_under_hits' in reduced.required_actions
    with pytest.raises(ValidationError,match='ritual_requires_repeated_hit'):
        MapRequest(tier=15,encounter='ritual',game_patch='0.5.5',recovery_scenario=recovery_request(scenario='no_hit'))
    unknown=analyze(MapRequest(tier=15,encounter='ritual',game_patch='0.5.5',unknown_modifier_text=['unverified reflection text']))
    assert unknown.unknown_modifier_count==1 and not unknown.safe_to_run_certified
    assert 'use_explicit_repeated_hits_not_no_hit_recharge' in unknown.required_actions


def test_run_profit_is_observed_net_and_unsold_asks_remain_hypothetical():
    store=DecisionStore('m');ids=[]
    for proceeds,seconds,deaths in [(5.,600.,0),(1.,1200.,2)]:
        result=record(RunObservationRequest(league='Forbidden Rites',encounter_key='ritual:t15',scenario_digest='a'*64,
            observed_at_epoch=int(time.time()),duration_seconds=seconds,deaths=deaths,entry_and_consumable_cost=2.,
            realized_loot_proceeds=proceeds,unsold_loot_ask_low=10.,unsold_loot_ask_high=20.,evidence='user_observed_completed_run'),store,'alice')
        ids.append(result.run_id)
    result=profit(ProfitRequest(run_ids=ids),store,'alice')
    assert result.sample_count==2 and result.observed_cost==4 and result.observed_realized_net==2
    assert result.realized_net_per_hour==4 and result.deaths==2
    assert (result.observed_run_net_min,result.observed_run_net_max)==(-1,3)
    assert (result.hypothetical_net_with_unsold_asks_low,result.hypothetical_net_with_unsold_asks_high)==(22,42)
    assert result.sample_size_warning=='few_runs' and not result.future_drop_rate_estimated
    with pytest.raises(WorkflowError): profit(ProfitRequest(run_ids=ids),store,'bob')
    with pytest.raises(ValidationError): ProfitRequest(run_ids=ids*2)


def test_unknown_crafting_odds_produce_threshold_and_maximum_loss_only():
    request=CraftRequest(base_opportunity_value=4.,currency_and_omen_cost=1.,success_net_sale_value=12.,
        failure_salvage_value=2.,attempts=3,available_risk_budget=8.)
    value=crafting(request)
    assert value.break_even_success_probability==pytest.approx(.3)
    assert value.maximum_failure_loss_for_attempts==9 and value.maximum_loss_exceeds_risk_budget
    assert value.conditional_expected_profit_per_attempt is None and value.probability_all_attempts_fail_under_iid_hypothesis is None
    assert not value.game_expected_value_verified and not value.mod_pool_and_weights_verified
    hypothetical=crafting(request.model_copy(update={'success_probability_hypothesis':.5,'probability_evidence':'user_supplied_hypothesis'}))
    assert hypothetical.conditional_expected_profit_per_attempt==2
    assert hypothetical.conditional_variance_per_attempt==25
    assert hypothetical.probability_all_attempts_fail_under_iid_hypothesis==.125
    assert not hypothetical.game_expected_value_verified


async def test_sale_compares_retained_identity_rolls_and_asks_without_sale_guarantee(client):
    scout,_,_=client
    backend=TradeBackend([listing(1,life=90,amount=10),listing(2,life=110,amount=30),listing(3,life=100,amount=20)])
    trade=TradeClient('test',transport=httpx.MockTransport(backend),interval=0,clock=lambda:NOW)
    try:
        found=await trade.search(TradeSearchRequest(category='accessory.ring'))
        before=len(backend.requests)
        result=await sale(SaleRequest(league='Forbidden Rites',reference_currency='exalted',subject={
            'base_type':'Gold Ring','rarity':'rare','corrupted':False,'evidence':'user_transcribed_item',
            'item_stats':[{'metric':'flat_life','value':100.}]},comparables=[{'search_id':found.search_id,'listing_ref':f'{i:064x}'} for i in range(1,4)]),trade,scout)
        assert len(backend.requests)==before
        assert (result.asking_price_low,result.asking_price_median,result.asking_price_high)==(10,20,30)
        assert [r.item_stat_deltas[0].value for r in result.comparables]==[-10,10,0]
        assert all('item_level_not_fully_known' in r.differences for r in result.comparables)
        assert not result.fast_sale_price_guaranteed and all(not r.completed_sale for r in result.comparables)
    finally: await trade.close()


async def test_reward_identity_is_exact_and_proposed_pool_stays_partial(client):
    scout,_,_=client
    ids={r['ApiId']:r['ItemId'] for r in fixture('currency')['Items']}
    request=RewardRequest(league='Forbidden Rites',choices=[{'category':'currency','item_id':ids['divine']}],
        choice_source='user_proposed_drop_pool',game_patch='0.5.5')
    proposed=await rewards(request,scout)
    assert proposed.highest_estimated_choice_index is None and not proposed.game_drop_pool_verified
    assert proposed.result_scope=='supplied_options_only_partial_pool'
    observed=await rewards(request.model_copy(update={'choice_source':'user_observed_reward_menu'}),scout)
    assert observed.highest_estimated_choice_index==0 and not observed.actual_sale_value_guaranteed


@pytest.mark.parametrize('evidence,status',[
    ('user_transcribed_item','source_semantics_matched'),
    ('user_supplied_hypothesis','hypothetical_source_semantics_matched'),
])
def test_map_analysis_retains_evidence_even_when_source_is_unverified(evidence,status):
    modifier={'rule_id':'map:less_life_es_recovery','magnitude_percent':35.,'evidence':evidence}
    query=MapRequest(tier=15,encounter='mapping',game_patch='0.5.5',modifiers=[modifier])
    result=analyze(query)
    assert result.interactions[0].evidence==evidence and result.interactions[0].status==status
    query.modifiers[0].source='tablet'
    unverified=analyze(query)
    assert unverified.interactions[0].evidence==evidence
    assert unverified.interactions[0].status=='source_or_roll_unverified'
    if evidence=='user_supplied_hypothesis':
        assert 'confirm_hypothetical_modifier_on_actual_item' in result.required_actions


@pytest.mark.parametrize('field,value,difference',[
    ('ilvl',79,'different_item_level'),('ilvl',None,'item_level_not_fully_known'),
    ('socketedItems',[{'baseType':'unknown'}],'different_rune_count'),
    ('socketedItems',None,'rune_state_not_fully_known'),
])
async def test_sale_excludes_different_or_unknown_supplied_identity_fields(client,field,value,difference):
    scout,_,_=client
    backend=TradeBackend([listing(1,amount=10),listing(2,amount=100)])
    trade=TradeClient('test',transport=httpx.MockTransport(backend),interval=0,clock=lambda:NOW)
    try:
        found=await trade.search(TradeSearchRequest(category='accessory.ring'))
        retained=trade.retained(found.search_id)
        retained['engine_items']={f'{1:064x}':{'ilvl':80,'socketedItems':[]},
            f'{2:064x}':{'ilvl':80,'socketedItems':[],field:value}}
        query=SaleRequest(league='Forbidden Rites',reference_currency='exalted',subject={
            'base_type':'Gold Ring','rarity':'rare','corrupted':False,'item_level':80,'rune_count':0,
            'evidence':'user_transcribed_item'},comparables=[{'search_id':found.search_id,'listing_ref':f'{i:064x}'} for i in (1,2)])
        result=await sale(query,trade,scout)
        assert result.matched_asking_count==1
        assert (result.asking_price_low,result.asking_price_median,result.asking_price_high)==(10,10,10)
        assert not result.comparables[1].identity_matches and difference in result.comparables[1].differences
    finally:await trade.close()
