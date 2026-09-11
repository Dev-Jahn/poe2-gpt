"""Proposals, executions, retries and history labels must not corrupt balances."""
import time
from types import SimpleNamespace
import pytest
from poe2_companion.currency_portfolio import (PortfolioCreate, PortfolioEventRequest, ValuePortfolio,
    PortfolioPageRequest, create, record, get, page, value_portfolio, ReviewPurchaseQuote, review_quote)
from poe2_companion.workflow_store import DecisionStore, WorkflowError
from poe2_companion.purchases import compare
from test_scout import client, fixture
from test_workflow_purchases import document, request as comparison_request, cost


async def test_proposal_does_not_spend_and_execution_retry_is_idempotent(client,tmp_path):
    scout,_,_ = client
    ids = {r['ApiId']:r['ItemId'] for r in fixture('currency')['Items']}
    store = DecisionStore('member',tmp_path/'state',tmp_path/'keys'/'key')
    now = int(time.time())
    created = await create(PortfolioCreate(league='Forbidden Rites',observed_at_epoch=now,persist_portfolio=True,
        holdings=[{'category':'currency','item_id':ids['divine'],'quantity':34.0},
            {'category':'currency','item_id':ids['chaos'],'quantity':0.0}]),store,'alice',scout)
    common = dict(portfolio_id=created.portfolio_id,transfers=[{'category':'currency','item_id':ids['divine'],
        'quantity':20.0,'direction':'debit'}],observed_at_epoch=now)
    proposal = await record(PortfolioEventRequest(**common,expected_revision=1,event_id='1'*32,
        kind='proposed',evidence='user_proposed'),store,'alice',scout)
    assert next(h.quantity for h in proposal.holdings if h.item_id == ids['divine']) == 34
    assert proposal.unexecuted_proposal_count == 1 and not proposal.proposals_automatically_deducted
    spend = PortfolioEventRequest(**common,expected_revision=2,event_id='2'*32,proposal_event_id='1'*32,
        kind='spent',evidence='user_reported_completed')
    spent = await record(spend,store,'alice',scout)
    assert next(h.quantity for h in spent.holdings if h.item_id == ids['divine']) == 14
    assert spent.unexecuted_proposal_count == 0
    again = await record(spend,store,'alice',scout)
    assert again.revision == spent.revision and again.holdings == spent.holdings and again.duplicate_event
    forged_retry = spend.model_copy(deep=True)
    forged_retry.transfers[0].quantity = 1.0
    with pytest.raises(WorkflowError,match='event_id_conflict'):
        await record(forged_retry,store,'alice',scout)
    second_execution = spend.model_copy(update={'event_id':'3'*32,'expected_revision':3})
    with pytest.raises(WorkflowError,match='already_executed'):
        await record(second_execution,store,'alice',scout)
    store.close()
    store = DecisionStore('member',tmp_path/'state',tmp_path/'keys'/'key')
    value = get(store,'alice',created.portfolio_id)
    assert value.revision == 3 and len(value.events) == 2
    with pytest.raises(WorkflowError,match='unavailable'): get(store,'bob',created.portfolio_id)
    valued = await value_portfolio(ValuePortfolio(portfolio_id=created.portfolio_id,expected_revision=3),store,'alice',scout)
    assert valued.valuation_matches_current_revision and valued.holdings == spent.holdings
    quote = get(store,'alice',created.portfolio_id).valuation
    assert quote.estimated_total == pytest.approx(14)
    assert quote.source_updated_at is None
    assert next(i for i in quote.items if i.item_id == ids['chaos']).estimated_total == 0
    part = page(PortfolioPageRequest(portfolio_id=created.portfolio_id,section='valuation'),store,'alice')
    assert part.history_bucket_is_current_observation_time is False
    assert part.valuation_is_executable_exchange_quote is False
    store.close()


async def test_repricing_over_budget_requires_new_confirmation_without_spending():
    store = DecisionStore('member')
    doc = document(1,2,False,100)
    store.save('alice',doc)
    workflow = SimpleNamespace(store=store,trade=None)
    old = await compare(comparison_request([{'key':'primary','experiment_ids':[doc.experiment_id],'costs':[cost(20)]}]),workflow,'alice',None)
    new = await compare(comparison_request([{'key':'primary','experiment_ids':[doc.experiment_id],'costs':[cost(40)]}]),workflow,'alice',None)
    review = review_quote(ReviewPurchaseQuote(previous_comparison_id=old.comparison_id,current_comparison_id=new.comparison_id),store,'alice')
    assert review.candidates[0].difference == 20
    assert review.candidates[0].requires_renewed_budget_confirmation
    assert review.candidates[0].current_budget_status == 'over_budget'
    assert review.holdings_modified is False and not review.existing_approval_applied_automatically
