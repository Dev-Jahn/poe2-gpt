"""Observed exchange quotes and gear opportunity costs remain game proposals."""
from datetime import datetime,timezone
import time
from types import SimpleNamespace
import pytest
from poe2_companion.currency_portfolio import PortfolioCreate,create,get
from poe2_companion.economy_analysis import AllocationRequest,AllocationPageRequest,plan,page
from poe2_companion.workflow_store import DecisionStore,WorkflowError
from poe2_companion.purchases import compare
from test_workflow_purchases import document,request as comparison_request,cost
from test_scout import client,fixture


async def test_exchange_spread_historical_buckets_and_equipment_opportunity(client):
    scout,backend,_=client;store=DecisionStore('m');now=int(time.time())
    ids={i['ApiId']:i['ItemId'] for i in fixture('currency')['Items']}
    pf=await create(PortfolioCreate(league='Forbidden Rites',observed_at_epoch=now,
        holdings=[{'category':'currency','item_id':ids['divine'],'quantity':34.}]),store,'alice',scout)
    doc=document(1,2,False,100);store.save('alice',doc)
    comparison=await compare(comparison_request([{'key':'gear','experiment_ids':[doc.experiment_id],'costs':[cost(20.)]}]),
        SimpleNamespace(store=store,trade=None),'alice',None)
    epoch=lambda hour:int(datetime(2026,9,6,hour,tzinfo=timezone.utc).timestamp())
    request=AllocationRequest(portfolio_id=pf.portfolio_id,expected_revision=1,target_category='currency',target_item_id=ids['chaos'],
        intended_spend=20.,reserve_amount=2.,exchange_fee=1.,history_start_epoch=epoch(6),history_end_epoch=epoch(12),
        exchange_observation={'buy_price_per_unit':2.,'sell_price_per_unit':1.5,'available_buy_units':100,'available_sell_units':100,
            'observed_at_epoch':now,'evidence':'user_observed_exchange_quotes'},purchase_comparison_id=comparison.comparison_id,
        future_price_cases=[{'key':'half','sell_price_per_unit':1.,'evidence':'user_supplied_hypothetical_price'}])
    result=await plan(request,store,'alice',scout)
    assert result.purchase_units==10 and result.allocated_cost_including_fee==21
    assert result.immediate_round_trip_loss==6 and result.exchange_spread_percent_of_ask==25
    assert result.maximum_allocation_loss==21 and result.future_cases[0].net_gain_or_loss==-11
    opportunity=result.equipment_opportunities[0]
    assert opportunity.affordable_before_allocation and not opportunity.affordable_after_allocation
    assert result.holding_value_remaining==13 and result.budget_status=='within_estimated_holdings_and_reserve'
    assert result.current_price_observed_at is None and len(result.history_buckets)==7
    historical=next(b for b in result.history_buckets if b.bucket_at_epoch==epoch(9))
    assert historical.price==pytest.approx(3.003085/83.71681)
    assert not result.history_prices_used_for_forecast_or_fx and not result.holdings_modified
    assert get(store,'alice',pf.portfolio_id).holdings[0].quantity==34
    assert get(store,'alice',pf.portfolio_id).revision==1
    assert page(AllocationPageRequest(allocation_id=result.allocation_id),store,'alice').artifact_digest==result.artifact_digest
    assert sum('ByCategory' in req.url.path for req in backend.calls)==1
    with pytest.raises(WorkflowError):page(AllocationPageRequest(allocation_id=result.allocation_id),store,'bob')
    request.exchange_observation.observed_at_epoch=now-301
    stale=await plan(request,store,'alice',scout)
    assert stale.liquidity=='quote_stale_or_missing' and stale.immediate_round_trip_loss is None
    assert not stale.exchange_execution_guaranteed
