"""Read-only asking-price comparisons and probability-explicit crafting maths."""
from __future__ import annotations
import math
from pathlib import Path
from statistics import median
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .builds import DTO, bounded_dto, tool_json_bytes
from .equipment import Currency, LeagueName, EquipmentService, FX, Stat, AggregateStat
from .scout import Scout
from .currency_models import CurrencyQuote
from .trade import TradeClient, TradeListing, SearchID
from .workflow_store import WorkflowError

Amount = Annotated[float, Field(ge=0,le=1e12,allow_inf_nan=False)]


class SaleIdentity(DTO):
    base_type: Annotated[str, Field(min_length=1,max_length=100)]
    rarity: Literal['normal','magic','rare','unique']
    unique_name: Annotated[str, Field(min_length=1,max_length=160)] | None = None
    item_level: Annotated[int, Field(ge=1,le=100)] | None = None
    corrupted: bool
    rune_count: Annotated[int, Field(ge=0,le=12)] | None = None
    item_stats: Annotated[list[Stat], Field(max_length=12)] = Field(default_factory=list)
    evidence: Literal['user_transcribed_item']

    @model_validator(mode='after')
    def unique(self) -> Self:
        if self.rarity=='unique' and self.unique_name is None: raise ValueError('exact_unique_name_required')
        if len({s.metric for s in self.item_stats})!=len(self.item_stats): raise ValueError('duplicate_sale_metric')
        return self


class ComparableRef(DTO):
    search_id: SearchID
    listing_ref: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class SaleRequest(DTO):
    league: LeagueName
    subject: SaleIdentity
    comparables: Annotated[list[ComparableRef], Field(min_length=1,max_length=8)]
    reference_currency: Currency = 'divine'
    offset: Annotated[int, Field(ge=0,le=8)] = 0
    limit: Annotated[int, Field(ge=1,le=5)] = 3
    @model_validator(mode='after')
    def unique(self) -> Self:
        if len({r.listing_ref for r in self.comparables})!=len(self.comparables): raise ValueError('duplicate_comparable_listing')
        return self


class SaleComparable(DTO):
    listing_ref: str
    base_type: str
    normalized_asking_price: float | None
    observed_at_epoch: int
    identity_matches: bool
    differences: list[str]
    item_stat_deltas: list[AggregateStat]
    item_stat_deltas_scope: Literal['recognized_item_values_only'] = 'recognized_item_values_only'
    all_rolls_compared: Literal[False] = False
    completed_sale: Literal[False] = False


class SaleAnalysis(DTO):
    league: str
    reference_currency: str
    comparables: list[SaleComparable]
    total_comparables: int
    next_offset: int | None
    matched_asking_count: int
    asking_price_low: float | None
    asking_price_median: float | None
    asking_price_high: float | None
    fx: FX
    price_band_scope: Literal['retained_identity_matched_asks_not_sale_prediction'] = 'retained_identity_matched_asks_not_sale_prediction'
    fast_sale_price_guaranteed: Literal[False] = False
    time_to_sale_estimated: Literal[False] = False
    next_action: Literal['review_roll_differences_and_list_manually','obtain_matching_comparables']


async def sale(request: SaleRequest, trade: TradeClient, scout: Scout) -> SaleAnalysis:
    retained: list[tuple[TradeListing,dict,dict]]=[]
    for ref in request.comparables:
        entry=trade.retained(ref.search_id)
        query=entry['request']
        league=query.league if hasattr(query,'league') else query['league']
        if league!=request.league: raise WorkflowError('sale_comparison_league_mismatch')
        row=entry['rows'].get(ref.listing_ref)
        if not isinstance(row,TradeListing): raise WorkflowError('sale_listing_not_retained')
        retained.append((row,entry.get('engine_items',{}).get(ref.listing_ref,{}),entry.get('description_items',{}).get(ref.listing_ref,{})))
    currencies={row.price.currency for row,_,_ in retained if row.price is not None}
    fx=await EquipmentService(Path('/unused'),scout).fx(request.league,currencies,request.reference_currency)
    results=[]
    for row,item,description in retained:
        differences=[]
        same=(row.base_type==request.subject.base_type and row.rarity==request.subject.rarity and row.corrupted==request.subject.corrupted)
        if row.base_type!=request.subject.base_type: differences.append('different_base_type')
        if row.rarity!=request.subject.rarity: differences.append('different_rarity')
        if row.corrupted!=request.subject.corrupted: differences.append('different_corruption')
        if request.subject.unique_name is not None and description.get('name')!=request.subject.unique_name:
            same=False;differences.append('different_or_unknown_unique_identity')
        if request.subject.item_level is None or item.get('ilvl') is None: differences.append('item_level_not_fully_known')
        elif item['ilvl']!=request.subject.item_level: differences.append('different_item_level')
        socketed=item.get('socketedItems')
        if request.subject.rune_count is None or not isinstance(socketed,list): differences.append('rune_state_not_fully_known')
        elif len(socketed)!=request.subject.rune_count: differences.append('different_rune_count')
        current={s.metric:s.value for s in row.item_stats}
        deltas=[AggregateStat(metric=s.metric,value=current[s.metric]-s.value) for s in request.subject.item_stats if s.metric in current]
        if any(s.value for s in deltas): differences.append('different_recognized_roll_values')
        if len(deltas)!=len(request.subject.item_stats) or row.unknown_modifier_count: differences.append('uncompared_modifiers_remain')
        price=row.price.amount*fx.rates[row.price.currency] if row.price else None
        if price is not None and not math.isfinite(price): raise WorkflowError('sale_value_out_of_range')
        results.append(SaleComparable(listing_ref=row.listing_ref,base_type=row.base_type,normalized_asking_price=price,
            observed_at_epoch=row.observed_at_epoch,identity_matches=same,differences=differences,item_stat_deltas=deltas))
    prices=[r.normalized_asking_price for r in results if r.identity_matches and r.normalized_asking_price is not None]
    end=min(len(results),request.offset+request.limit)
    result=SaleAnalysis(league=request.league,reference_currency=request.reference_currency,comparables=results[request.offset:end],
        total_comparables=len(results),next_offset=end if end<len(results) else None,
        matched_asking_count=len(prices),asking_price_low=min(prices) if prices else None,
        asking_price_median=median(prices) if prices else None,asking_price_high=max(prices) if prices else None,fx=fx,
        next_action='review_roll_differences_and_list_manually' if prices else 'obtain_matching_comparables')
    while tool_json_bytes(result)>8192 and len(result.comparables)>1:
        result.comparables.pop();result.next_offset=request.offset+len(result.comparables)
    return bounded_dto(result)


class CraftRequest(DTO):
    reference_currency: Currency = 'divine'
    base_opportunity_value: Amount
    currency_and_omen_cost: Amount
    success_net_sale_value: Amount
    failure_salvage_value: Amount
    attempts: Annotated[int, Field(ge=1,le=100)] = 1
    available_risk_budget: Amount
    success_probability_hypothesis: Annotated[float, Field(ge=0,le=1,allow_inf_nan=False)] | None = None
    probability_evidence: Literal['unknown','user_supplied_hypothesis'] = 'unknown'
    @model_validator(mode='after')
    def evidence(self) -> Self:
        if (self.success_probability_hypothesis is None)!=(self.probability_evidence=='unknown'):
            raise ValueError('craft_probability_evidence_mismatch')
        if self.success_net_sale_value<=self.failure_salvage_value: raise ValueError('craft_success_must_exceed_salvage')
        return self


class CraftAnalysis(DTO):
    reference_currency: str
    at_risk_cost_per_attempt: float
    loss_if_failure_per_attempt: float
    maximum_failure_loss_for_attempts: float
    maximum_loss_exceeds_risk_budget: bool
    break_even_success_probability: float
    break_even_possible: bool
    conditional_expected_profit_per_attempt: float | None
    conditional_variance_per_attempt: float | None
    probability_all_attempts_fail_under_iid_hypothesis: float | None
    game_expected_value_verified: Literal[False] = False
    mod_pool_and_weights_verified: Literal[False] = False
    all_fail_probability_is_general_ruin_probability: Literal[False] = False
    calculation_scope: Literal['unknown_odds_thresholds_only','explicit_user_probability_and_iid_hypothesis']
    next_action: Literal['obtain_verified_mod_pool_and_crafting_rules','review_hypothesis_and_maximum_loss_before_spending']


def crafting(request: CraftRequest) -> CraftAnalysis:
    cost=request.base_opportunity_value+request.currency_and_omen_cost
    failure_loss=max(0.0,cost-request.failure_salvage_value)
    gap=request.success_net_sale_value-request.failure_salvage_value
    threshold=(cost-request.failure_salvage_value)/gap
    if not math.isfinite(threshold): raise WorkflowError('craft_value_out_of_range')
    p=request.success_probability_hypothesis
    return CraftAnalysis(reference_currency=request.reference_currency,at_risk_cost_per_attempt=cost,
        loss_if_failure_per_attempt=failure_loss,maximum_failure_loss_for_attempts=failure_loss*request.attempts,
        maximum_loss_exceeds_risk_budget=failure_loss*request.attempts>request.available_risk_budget,
        break_even_success_probability=max(0.0,threshold),break_even_possible=threshold<=1,
        conditional_expected_profit_per_attempt=p*request.success_net_sale_value+(1-p)*request.failure_salvage_value-cost if p is not None else None,
        conditional_variance_per_attempt=p*(1-p)*gap*gap if p is not None else None,
        probability_all_attempts_fail_under_iid_hypothesis=(1-p)**request.attempts if p is not None else None,
        calculation_scope='unknown_odds_thresholds_only' if p is None else 'explicit_user_probability_and_iid_hypothesis',
        next_action='obtain_verified_mod_pool_and_crafting_rules' if p is None else 'review_hypothesis_and_maximum_loss_before_spending')


class RewardChoice(DTO):
    category: Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')]
    item_id: Annotated[int, Field(ge=1,le=2147483647)]
    quantity: Annotated[float, Field(gt=0,le=1e9,allow_inf_nan=False)] = 1.0


class RewardRequest(DTO):
    league: LeagueName
    reference_currency: Currency = 'divine'
    choices: Annotated[list[RewardChoice], Field(min_length=1,max_length=8)]
    choice_source: Literal['user_observed_reward_menu','user_proposed_drop_pool']
    game_patch: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+\.[0-9]+[a-z]?$')]


class RewardAnalysis(DTO):
    quote: CurrencyQuote
    game_patch: str
    choice_source: str
    highest_estimated_choice_index: int | None
    result_scope: Literal['supplied_options_only_partial_pool'] = 'supplied_options_only_partial_pool'
    game_drop_pool_verified: Literal[False] = False
    actual_sale_value_guaranteed: Literal[False] = False
    next_action: Literal['verify_exact_offered_identity_and_liquidity','verify_actual_drop_pool_before_content_choice']


async def rewards(request: RewardRequest, scout: Scout) -> RewardAnalysis:
    quote=CurrencyQuote.model_validate(await scout.quote([c.model_dump(mode='json') for c in request.choices],request.league,request.reference_currency,False))
    known=quote.complete and request.choice_source=='user_observed_reward_menu'
    best=max(range(len(quote.items)),key=lambda i:quote.items[i].estimated_total or 0) if known else None
    return bounded_dto(RewardAnalysis(quote=quote,game_patch=request.game_patch,choice_source=request.choice_source,
        highest_estimated_choice_index=best,next_action='verify_exact_offered_identity_and_liquidity' if known else 'verify_actual_drop_pool_before_content_choice'))
