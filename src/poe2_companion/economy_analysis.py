"""Game-currency allocation, historical buckets and equipment opportunity cost."""
from datetime import datetime,timezone
import math
import secrets
import time
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .builds import DTO,bounded_dto
from .currency_portfolio import PortfolioID,CurrencyHolding,get as get_portfolio
from .currency_models import CurrencyQuote
from .equipment import Currency
from .purchase_models import ComparisonID,PurchaseComparison
from .workflow_store import DecisionStore,WorkflowError
from .capabilities import digest,canonical
from .scout import Scout

Amount=Annotated[float,Field(ge=0,le=1e12,allow_inf_nan=False)]
AllocationID=Annotated[str,Field(pattern=r'^allocation_[0-9a-f]{32}$')]


class ExchangeObservation(DTO):
    buy_price_per_unit: Annotated[float,Field(gt=0,le=1e12,allow_inf_nan=False)]
    sell_price_per_unit: Amount
    available_buy_units: Annotated[int,Field(ge=0,le=1000000000000)] | None = None
    available_sell_units: Annotated[int,Field(ge=0,le=1000000000000)] | None = None
    observed_at_epoch: Annotated[int,Field(ge=0,le=100000000000)]
    evidence: Literal['user_observed_exchange_quotes']

    @model_validator(mode='after')
    def uncrossed(self):
        if self.sell_price_per_unit>self.buy_price_per_unit:raise ValueError('crossed_exchange_quotes_require_recheck')
        return self


class FuturePriceCase(DTO):
    key: Annotated[str,Field(pattern=r'^[a-zA-Z0-9_-]{1,32}$')]
    sell_price_per_unit: Amount
    evidence: Literal['user_supplied_hypothetical_price']


class AllocationRequest(DTO):
    portfolio_id: PortfolioID
    expected_revision: Annotated[int,Field(ge=1,le=1000000)]
    target_category: Annotated[str,Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')]
    target_item_id: Annotated[int,Field(ge=1,le=2147483647)]
    reference_currency: Currency = 'divine'
    intended_spend: Amount
    reserve_amount: Amount = 0.
    exchange_fee: Amount = 0.
    history_start_epoch: Annotated[int,Field(ge=0,le=100000000000)]
    history_end_epoch: Annotated[int,Field(ge=0,le=100000000000)]
    exchange_observation: ExchangeObservation | None = None
    future_price_cases: Annotated[list[FuturePriceCase],Field(max_length=5)] = Field(default_factory=list)
    purchase_comparison_id: ComparisonID | None = None
    persist_plan: bool = False

    @model_validator(mode='after')
    def valid_window(self):
        if not 0<self.history_end_epoch-self.history_start_epoch<=7*86400:raise ValueError('history_window_requires_one_week_or_less')
        if len({s.key for s in self.future_price_cases})!=len(self.future_price_cases):raise ValueError('duplicate_price_case')
        return self


class HistoryBucket(DTO):
    bucket_at_epoch: int
    price: float
    source_quantity: int


class EquipmentOpportunity(DTO):
    candidate_key: str
    estimated_package_cost: float | None
    qualified_joint_plan: bool
    affordable_before_allocation: bool | None
    affordable_after_allocation: bool | None
    quote_needs_recheck: bool


class AllocationCase(DTO):
    key: str
    sell_price_per_unit: float
    net_gain_or_loss: float
    probability: None = None


class AllocationResult(DTO):
    allocation_id: AllocationID
    portfolio_id: str
    portfolio_revision: int
    league: str
    reference_currency: Currency
    domain: Literal['in_game_currency_only'] = 'in_game_currency_only'
    target_category: str
    target_item_id: int
    aggregate_unit_price: float | None
    current_price_observed_at: None = None
    history_buckets: Annotated[list[HistoryBucket],Field(max_length=8)]
    history_scope: Literal['available_scout_hourly_buckets_within_requested_same_league_window'] = 'available_scout_hourly_buckets_within_requested_same_league_window'
    history_price_unit: Literal['reference_currency_per_item_using_same_bucket_fx'] = 'reference_currency_per_item_using_same_bucket_fx'
    history_conversion_source: str = 'https://github.com/poe2scout/poe2scout/blob/0e3f718b709dfa0c92eeeea7425b4e63a209b97c/net/Poe2scout.Api/EconomyCache.cs'
    history_prices_used_for_forecast_or_fx: Literal[False] = False
    requested_history_window_fully_covered: bool
    estimated_total_holdings: float | None
    purchase_units: int | None
    allocated_cost_including_fee: float | None
    holding_value_remaining: float | None
    budget_status: Literal['within_estimated_holdings_and_reserve','insufficient_estimated_holdings','unknown']
    entry_basis: Literal['reported_buy_quote','aggregated_estimate','unavailable']
    immediate_round_trip_loss: float | None
    maximum_allocation_loss: float | None
    exchange_spread_percent_of_ask: float | None
    liquidity: Literal['reported_quotes_cover_both_sides','reported_depth_insufficient','depth_unknown','quote_stale_or_missing']
    equipment_opportunities: Annotated[list[EquipmentOpportunity],Field(max_length=6)]
    future_cases: Annotated[list[AllocationCase],Field(max_length=5)]
    forecast_probability_available: Literal[False] = False
    allocation_automatically_executed: Literal[False] = False
    holdings_modified: Literal[False] = False
    exchange_execution_guaranteed: Literal[False] = False
    artifact_digest: str


class AllocationDocument(DTO):
    request: AllocationRequest
    result: AllocationResult
    quote: CurrencyQuote
    history_retrieved_at: str
    created_at_epoch: int
    expires_at_epoch: int


class AllocationPageRequest(DTO):
    allocation_id: AllocationID
    offset: Annotated[int,Field(ge=0,le=1000000)] = 0
    limit: Annotated[int,Field(ge=1,le=1200)] = 1000


class AllocationReference(DTO):
    allocation_id: AllocationID


class AllocationPage(DTO):
    allocation_id: str
    artifact_digest: str
    content: str
    total: int
    next_offset: int | None
    source_portfolio_revision_changed: bool


async def plan(request: AllocationRequest,store: DecisionStore,owner: str,scout: Scout) -> AllocationResult:
    now=int(time.time())
    portfolio=get_portfolio(store,owner,request.portfolio_id)
    if portfolio.revision!=request.expected_revision:raise WorkflowError('portfolio_revision_conflict')
    if request.persist_plan and store.db is None:raise WorkflowError('workflow_persistence_unconfigured')
    if request.history_end_epoch>now+300 or (request.exchange_observation and request.exchange_observation.observed_at_epoch>now+300):
        raise WorkflowError('allocation_observation_in_future')
    holdings={(h.category,h.item_id):h for h in portfolio.holdings}
    target=(request.target_category,request.target_item_id)
    identities=dict(holdings)
    identities.setdefault(target,CurrencyHolding(category=target[0],item_id=target[1],quantity=0.))
    if len(identities)>30:raise WorkflowError('allocation_quote_identity_limit')
    quote=CurrencyQuote.model_validate(await scout.quote([{'category':c,'item_id':i,'quantity':1.} for c,i in identities],
        portfolio.league,request.reference_currency,False))
    units={(i.category,i.item_id):i.unit_price for i in quote.items}
    # The target category read reuses the same validated cache snapshot and
    # exact reference-currency identity as the quotation batch.
    category=await scout.category(request.target_category,portfolio.league,request.reference_currency,False)
    if category['data']['league']!=portfolio.league or category['data']['reference_currency']['id']!=quote.reference_currency.id:
        raise WorkflowError('allocation_history_context_mismatch')
    raw=next((i for i in category['data']['items'] if i['item_id']==request.target_item_id),None)
    if raw is None:raise WorkflowError('allocation_target_unavailable')
    buckets=[]
    for row in raw['price_logs']:
        if row is None:continue
        try:
            stamp=datetime.fromisoformat(row['time'].replace('Z','+00:00'))
            if stamp.tzinfo is None:continue
            epoch=int(stamp.astimezone(timezone.utc).timestamp())
        except (ValueError,OverflowError):continue
        if request.history_start_epoch<=epoch<=request.history_end_epoch:
            buckets.append(HistoryBucket(bucket_at_epoch=epoch,price=row['price'],source_quantity=row['quantity']))
    buckets=sorted(buckets,key=lambda b:b.bucket_at_epoch)[-8:]
    if len({b.bucket_at_epoch for b in buckets})!=len(buckets):raise WorkflowError('history_duplicate_bucket')
    complete=all(h.quantity==0 or units.get(k) is not None for k,h in holdings.items())
    total=sum(h.quantity*(units.get(k) or 0) for k,h in holdings.items()) if complete else None
    observed=request.exchange_observation
    fresh=observed is not None and now-observed.observed_at_epoch<=300
    entry=observed.buy_price_per_unit if fresh and observed else units[target]
    ratio=request.intended_spend/entry if entry is not None and entry>0 else None
    if ratio is not None and (not math.isfinite(ratio) or ratio>1e12):raise WorkflowError('allocation_quantity_out_of_range')
    quantity=math.floor(ratio) if ratio is not None else None
    cost=quantity*entry+request.exchange_fee if quantity is not None and entry is not None else None
    remaining=total-cost if total is not None and cost is not None else None
    budget: Literal['within_estimated_holdings_and_reserve','insufficient_estimated_holdings','unknown']='unknown' if remaining is None else (
        'within_estimated_holdings_and_reserve' if remaining>=request.reserve_amount else 'insufficient_estimated_holdings')
    liquidity: Literal['reported_quotes_cover_both_sides','reported_depth_insufficient','depth_unknown','quote_stale_or_missing']='quote_stale_or_missing'
    if fresh and observed:
        if quantity is None or observed.available_buy_units is None or observed.available_sell_units is None:liquidity='depth_unknown'
        elif min(observed.available_buy_units,observed.available_sell_units)<quantity:liquidity='reported_depth_insufficient'
        else:liquidity='reported_quotes_cover_both_sides'
    opportunities=[]
    if request.purchase_comparison_id:
        comparison=store.get_artifact(owner,'purchase_comparison',request.purchase_comparison_id,PurchaseComparison)
        if (comparison.request.league,comparison.request.budget.currency)!=(portfolio.league,request.reference_currency):raise WorkflowError('allocation_purchase_context_mismatch')
        for candidate in comparison.candidates:
            price=candidate.total_estimated_cost
            opportunities.append(EquipmentOpportunity(candidate_key=candidate.key,estimated_package_cost=price,
                qualified_joint_plan=candidate.qualified_in_all_scenarios,quote_needs_recheck=now>=comparison.quote_recheck_after_epoch,
                affordable_before_allocation=total-request.reserve_amount>=price if total is not None and price is not None else None,
                affordable_after_allocation=remaining-request.reserve_amount>=price if remaining is not None and price is not None else None))
    result=AllocationResult(allocation_id='allocation_'+secrets.token_hex(16),portfolio_id=portfolio.portfolio_id,
        portfolio_revision=portfolio.revision,league=portfolio.league,reference_currency=request.reference_currency,
        target_category=target[0],target_item_id=target[1],aggregate_unit_price=units[target],history_buckets=buckets,
        requested_history_window_fully_covered=bool(buckets) and buckets[0].bucket_at_epoch<=request.history_start_epoch and buckets[-1].bucket_at_epoch>=request.history_end_epoch
            and all(b.bucket_at_epoch-a.bucket_at_epoch==3600 for a,b in zip(buckets,buckets[1:])),
        estimated_total_holdings=total,purchase_units=quantity,allocated_cost_including_fee=cost,holding_value_remaining=remaining,budget_status=budget,
        entry_basis='reported_buy_quote' if fresh else 'aggregated_estimate' if entry is not None else 'unavailable',
        immediate_round_trip_loss=cost-quantity*observed.sell_price_per_unit if fresh and observed and cost is not None and quantity is not None else None,
        maximum_allocation_loss=cost,exchange_spread_percent_of_ask=100*(observed.buy_price_per_unit-observed.sell_price_per_unit)/observed.buy_price_per_unit if fresh and observed else None,
        liquidity=liquidity,equipment_opportunities=opportunities,future_cases=[AllocationCase(key=c.key,sell_price_per_unit=c.sell_price_per_unit,
            net_gain_or_loss=quantity*c.sell_price_per_unit-cost) for c in request.future_price_cases] if quantity is not None and cost is not None else [],artifact_digest='0'*64)
    if any(v is not None and (not math.isfinite(v) or abs(v)>1e15) for v in [total,cost,remaining,*[c.net_gain_or_loss for c in result.future_cases]]):raise WorkflowError('allocation_value_out_of_range')
    value=AllocationDocument(request=request,result=result,quote=quote,history_retrieved_at=category['retrieved_at'],
        created_at_epoch=now,expires_at_epoch=min(portfolio.expires_at_epoch,now+(30*86400 if request.persist_plan else 3600)))
    result.artifact_digest=digest(value.model_dump(mode='json'))
    bounded_dto(result)
    store.save_artifact(owner,'currency_allocation',result.allocation_id,value,value.expires_at_epoch,request.persist_plan)
    return result


def page(request: AllocationPageRequest,store: DecisionStore,owner: str) -> AllocationPage:
    value=store.get_artifact(owner,'currency_allocation',request.allocation_id,AllocationDocument)
    current=get_portfolio(store,owner,value.request.portfolio_id)
    text=canonical(value.model_dump(mode='json'));end=request.offset+request.limit
    return bounded_dto(AllocationPage(allocation_id=request.allocation_id,artifact_digest=value.result.artifact_digest,
        content=text[request.offset:end],total=len(text),next_offset=end if end<len(text) else None,
        source_portfolio_revision_changed=current.revision!=value.result.portfolio_revision))
