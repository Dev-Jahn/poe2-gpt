"""User-reported balances and idempotent execution evidence, separate from proposals."""
from __future__ import annotations
from decimal import Decimal
import secrets
import time
import math
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .builds import DTO, bounded_dto
from .capabilities import canonical, digest
from .currency_models import CurrencyQuote
from .equipment import LeagueName, Currency
from .profiles import Digest
from .purchase_models import ComparisonID, PurchaseComparison
from .workflow_store import DecisionStore, WorkflowError
from .scout import Scout

PortfolioID = Annotated[str, Field(pattern=r'^pf_[0-9a-f]{32}$')]
Quantity = Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)]


class CurrencyHolding(DTO):
    category: Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')]
    item_id: Annotated[int, Field(ge=1, le=2147483647)]
    quantity: Quantity


class PortfolioCreate(DTO):
    league: LeagueName
    holdings: Annotated[list[CurrencyHolding], Field(min_length=1, max_length=30)]
    source: Literal['user_reported','user_imported_snapshot'] = 'user_reported'
    observed_at_epoch: Annotated[int, Field(ge=0, le=100000000000)]
    persist_portfolio: bool = False

    @model_validator(mode='after')
    def distinct(self) -> Self:
        if len({(h.category,h.item_id) for h in self.holdings}) != len(self.holdings): raise ValueError('duplicate_currency_holding')
        return self


class CurrencyTransfer(CurrencyHolding):
    direction: Literal['debit','credit']


class PortfolioEventRequest(DTO):
    portfolio_id: PortfolioID
    expected_revision: Annotated[int, Field(ge=1, le=1000000)]
    event_id: Annotated[str, Field(pattern=r'^[0-9a-f]{32}$')]
    kind: Literal['proposed','spent','received','realized_sale']
    transfers: Annotated[list[CurrencyTransfer], Field(min_length=1, max_length=30)]
    evidence: Literal['user_proposed','user_reported_completed']
    observed_at_epoch: Annotated[int, Field(ge=0, le=100000000000)]
    comparison_id: ComparisonID | None = None
    proposal_event_id: Annotated[str, Field(pattern=r'^[0-9a-f]{32}$')] | None = None

    @model_validator(mode='after')
    def execution_evidence(self) -> Self:
        if self.kind == 'proposed' and self.proposal_event_id is not None: raise ValueError('proposal_cannot_resolve_proposal')
        if (self.kind == 'proposed') != (self.evidence == 'user_proposed'): raise ValueError('execution_evidence_required')
        if self.kind == 'spent' and any(t.direction != 'debit' for t in self.transfers): raise ValueError('spent_event_only_debits')
        if self.kind in {'received','realized_sale'} and any(t.direction != 'credit' for t in self.transfers): raise ValueError('received_event_only_credits')
        if any(t.quantity <= 0 for t in self.transfers): raise ValueError('event_quantity_must_be_positive')
        return self


class LedgerEvent(DTO):
    event_id: str
    request_digest: Digest
    kind: Literal['proposed','spent','received','realized_sale']
    transfers: Annotated[list[CurrencyTransfer], Field(max_length=30)]
    evidence: Literal['user_proposed','user_reported_completed']
    observed_at_epoch: int
    recorded_at_epoch: int
    applied_revision: int
    comparison_id: ComparisonID | None = None
    proposal_event_id: Annotated[str, Field(pattern=r'^[0-9a-f]{32}$')] | None = None
    balance_changed: bool


class CurrencyPortfolio(DTO):
    portfolio_id: PortfolioID
    revision: int
    league: LeagueName
    initial_holdings: Annotated[list[CurrencyHolding], Field(max_length=30)]
    holdings: Annotated[list[CurrencyHolding], Field(max_length=30)]
    source: Literal['user_reported','user_imported_snapshot']
    initial_observed_at_epoch: int
    created_at_epoch: int
    expires_at_epoch: int
    events: Annotated[list[LedgerEvent], Field(max_length=128)]
    valuation: CurrencyQuote | None = None
    valuation_revision: int | None = None
    game_balance_verified: Literal[False] = False
    persistent: bool
    artifact_digest: Digest


class PortfolioSummary(DTO):
    portfolio_id: PortfolioID
    revision: int
    league: str
    holdings: Annotated[list[CurrencyHolding], Field(max_length=30)]
    event_count: int
    unexecuted_proposal_count: int
    artifact_digest: Digest
    expires_at_epoch: int
    persisted: bool
    duplicate_event: bool = False
    valuation_matches_current_revision: bool
    game_balance_verified: Literal[False] = False
    proposals_automatically_deducted: Literal[False] = False


class PortfolioPageRequest(DTO):
    portfolio_id: PortfolioID
    section: Literal['ledger','valuation','exact_json'] = 'ledger'
    offset: Annotated[int, Field(ge=0, le=1000000)] = 0
    limit: Annotated[int, Field(ge=1, le=1200)] = 1000


class PortfolioPage(DTO):
    portfolio_id: PortfolioID
    revision: int
    artifact_digest: Digest
    section: Literal['ledger','valuation','exact_json']
    content: str
    total: int
    next_offset: int | None
    history_bucket_is_current_observation_time: Literal[False] = False
    valuation_is_executable_exchange_quote: Literal[False] = False


class ValuePortfolio(DTO):
    portfolio_id: PortfolioID
    expected_revision: Annotated[int, Field(ge=1, le=1000000)]
    reference_currency: Currency = 'divine'


class DeletePortfolio(DTO):
    portfolio_id: PortfolioID


class ReviewPurchaseQuote(DTO):
    previous_comparison_id: ComparisonID
    current_comparison_id: ComparisonID


class RepricedCandidate(DTO):
    candidate_key: str
    previous_estimated_cost: float | None
    current_estimated_cost: float | None
    difference: float | None
    current_budget_status: Literal['within_estimated_budget','over_budget','incomplete_costs']
    requires_renewed_budget_confirmation: bool


class QuoteReview(DTO):
    previous_comparison_id: ComparisonID
    current_comparison_id: ComparisonID
    candidates: Annotated[list[RepricedCandidate], Field(max_length=6)]
    current_quote_needs_refresh: bool
    existing_approval_applied_automatically: Literal[False] = False
    holdings_modified: Literal[False] = False


def seal(value: CurrencyPortfolio) -> None:
    value.artifact_digest = digest(value.model_dump(mode='json',exclude={'artifact_digest'}))


def get(store: DecisionStore, owner: str, identifier: str) -> CurrencyPortfolio:
    value = store.get_artifact(owner,'currency_portfolio',identifier,CurrencyPortfolio)
    if value.artifact_digest != digest(value.model_dump(mode='json',exclude={'artifact_digest'})):
        raise WorkflowError('artifact_integrity_failure')
    return value


def summary(value: CurrencyPortfolio, duplicate: bool = False) -> PortfolioSummary:
    resolved = {e.proposal_event_id for e in value.events if e.balance_changed and e.proposal_event_id is not None}
    return bounded_dto(PortfolioSummary(portfolio_id=value.portfolio_id,revision=value.revision,league=value.league,
        holdings=value.holdings,event_count=len(value.events),unexecuted_proposal_count=sum(e.kind == 'proposed' and e.event_id not in resolved for e in value.events),
        artifact_digest=value.artifact_digest,expires_at_epoch=value.expires_at_epoch,persisted=value.persistent,
        duplicate_event=duplicate,valuation_matches_current_revision=value.valuation is not None and value.valuation_revision == value.revision))


async def create(request: PortfolioCreate, store: DecisionStore, owner: str, scout: Scout) -> PortfolioSummary:
    now = int(time.time())
    if request.persist_portfolio and store.db is None: raise WorkflowError('workflow_persistence_unconfigured')
    if request.observed_at_epoch > now+300: raise WorkflowError('portfolio_timestamp_in_future')
    # Exact category+item_id resolution preserves tiers and similar orb names.
    await scout.quote([{'category':h.category,'item_id':h.item_id,'quantity':1.0} for h in request.holdings],request.league,'divine',False)
    value = CurrencyPortfolio(portfolio_id='pf_'+secrets.token_hex(16),revision=1,league=request.league,
        initial_holdings=request.holdings,holdings=request.holdings,source=request.source,
        initial_observed_at_epoch=request.observed_at_epoch,created_at_epoch=now,
        expires_at_epoch=now+(90*86400 if request.persist_portfolio else 3600),events=[],persistent=request.persist_portfolio,
        artifact_digest='0'*64)
    seal(value)
    store.save_artifact(owner,'currency_portfolio',value.portfolio_id,value,value.expires_at_epoch,request.persist_portfolio)
    return summary(value)


async def record(request: PortfolioEventRequest, store: DecisionStore, owner: str, scout: Scout) -> PortfolioSummary:
    value = get(store,owner,request.portfolio_id)
    event_digest = digest(request.model_dump(mode='json',exclude={'expected_revision'}))
    existing = next((e for e in value.events if e.event_id == request.event_id),None)
    if existing:
        if existing.request_digest != event_digest: raise WorkflowError('portfolio_event_id_conflict')
        return summary(value,True)
    if value.revision != request.expected_revision: raise WorkflowError('portfolio_revision_conflict')
    if len(value.events) >= 128: raise WorkflowError('portfolio_event_limit_exceeded')
    now = int(time.time())
    if request.observed_at_epoch > now+300 or request.observed_at_epoch < value.initial_observed_at_epoch:
        raise WorkflowError('portfolio_event_timestamp_outside_revision')
    if request.proposal_event_id:
        proposal = next((e for e in value.events if e.event_id == request.proposal_event_id and e.kind == 'proposed'),None)
        if proposal is None: raise WorkflowError('portfolio_proposal_unavailable')
        if any(e.proposal_event_id == request.proposal_event_id and e.balance_changed for e in value.events):
            raise WorkflowError('portfolio_proposal_already_executed')
        shape = lambda entries: sorted((t.category,t.item_id,t.direction,t.quantity) for t in entries)
        if shape(proposal.transfers) != shape(request.transfers): raise WorkflowError('portfolio_proposal_amount_changed')
        if proposal.comparison_id != request.comparison_id: raise WorkflowError('portfolio_proposal_comparison_changed')
    if request.comparison_id:
        comparison = store.get_artifact(owner,'purchase_comparison',request.comparison_id,PurchaseComparison)
        if comparison.request.league != value.league: raise WorkflowError('portfolio_comparison_league_mismatch')
    current = {(h.category,h.item_id):Decimal(str(h.quantity)) for h in value.holdings}
    new_ids = {(t.category,t.item_id) for t in request.transfers}-set(current)
    if new_ids:
        await scout.quote([{'category':category,'item_id':identifier,'quantity':1.0} for category,identifier in sorted(new_ids)],value.league,'divine',False)
    if request.kind != 'proposed':
        for transfer in request.transfers:
            key = (transfer.category,transfer.item_id)
            current[key] = current.get(key,Decimal(0)) + Decimal(str(transfer.quantity)) * (-1 if transfer.direction == 'debit' else 1)
        if any(q < 0 or q > Decimal('1e12') for q in current.values()): raise WorkflowError('portfolio_balance_out_of_range')
        if len(current) > 30: raise WorkflowError('portfolio_holding_limit_exceeded')
        value.holdings = [CurrencyHolding(category=k[0],item_id=k[1],quantity=float(q)) for k,q in sorted(current.items())]
        value.valuation = None
        value.valuation_revision = None
    value.revision += 1
    value.events.append(LedgerEvent(event_id=request.event_id,request_digest=event_digest,kind=request.kind,
        transfers=request.transfers,evidence=request.evidence,observed_at_epoch=request.observed_at_epoch,
        recorded_at_epoch=now,applied_revision=value.revision,comparison_id=request.comparison_id,proposal_event_id=request.proposal_event_id,balance_changed=request.kind != 'proposed'))
    if value.valuation is not None: value.valuation_revision = value.revision
    seal(value)
    store.update_portfolio(owner,value.portfolio_id,value,request.expected_revision)
    return summary(value)


async def value_portfolio(request: ValuePortfolio, store: DecisionStore, owner: str, scout: Scout) -> PortfolioSummary:
    value = get(store,owner,request.portfolio_id)
    if value.revision != request.expected_revision: raise WorkflowError('portfolio_revision_conflict')
    quote = CurrencyQuote.model_validate(await scout.quote([{'category':h.category,'item_id':h.item_id,'quantity':1.0} for h in value.holdings],value.league,request.reference_currency,False))
    quantities = {(h.category,h.item_id):h.quantity for h in value.holdings}
    for item in quote.items:
        item.quantity = quantities[(item.category,item.item_id)]
        item.estimated_total = 0.0 if item.quantity == 0 else item.unit_price*item.quantity if item.unit_price is not None else None
        if item.estimated_total is not None and not math.isfinite(item.estimated_total): raise WorkflowError('portfolio_value_out_of_range')
    quote.complete = all(item.estimated_total is not None for item in quote.items)
    quote.estimated_total = sum(item.estimated_total or 0 for item in quote.items) if quote.complete else None
    if quote.estimated_total is not None and not math.isfinite(quote.estimated_total): raise WorkflowError('portfolio_value_out_of_range')
    value.revision += 1
    value.valuation = quote
    value.valuation_revision = value.revision
    seal(value)
    store.update_portfolio(owner,value.portfolio_id,value,request.expected_revision)
    return summary(value)


def page(request: PortfolioPageRequest, store: DecisionStore, owner: str) -> PortfolioPage:
    value = get(store,owner,request.portfolio_id)
    data = value.model_dump(mode='json') if request.section == 'exact_json' else value.valuation.model_dump(mode='json') if request.section == 'valuation' and value.valuation is not None else None if request.section == 'valuation' else [e.model_dump(mode='json') for e in value.events]
    text = canonical(data)
    end = request.offset+request.limit
    return bounded_dto(PortfolioPage(portfolio_id=value.portfolio_id,revision=value.revision,artifact_digest=value.artifact_digest,
        section=request.section,content=text[request.offset:end],total=len(text),next_offset=end if end<len(text) else None))


def review_quote(request: ReviewPurchaseQuote, store: DecisionStore, owner: str) -> QuoteReview:
    previous,current = [store.get_artifact(owner,'purchase_comparison',identifier,PurchaseComparison)
        for identifier in (request.previous_comparison_id,request.current_comparison_id)]
    if (previous.request.league,previous.request.budget.currency) != (current.request.league,current.request.budget.currency):
        raise WorkflowError('quote_comparison_currency_or_league_mismatch')
    before = {c.key:c for c in previous.candidates}
    if set(before) != {c.key for c in current.candidates}: raise WorkflowError('quote_candidate_set_changed')
    rows = []
    for candidate in current.candidates:
        old = before[candidate.key]
        if old.edit_plan_digest != candidate.edit_plan_digest: raise WorkflowError('quote_plan_changed')
        a,b = old.total_estimated_cost,candidate.total_estimated_cost
        rows.append(RepricedCandidate(candidate_key=candidate.key,previous_estimated_cost=a,current_estimated_cost=b,
            difference=b-a if a is not None and b is not None else None,current_budget_status=candidate.budget_status,
            requires_renewed_budget_confirmation=(candidate.budget_status == 'over_budget'
                or current.request.budget.amount > previous.request.budget.amount)))
    return bounded_dto(QuoteReview(previous_comparison_id=previous.comparison_id,current_comparison_id=current.comparison_id,
        candidates=rows,current_quote_needs_refresh=int(time.time())>=current.quote_recheck_after_epoch))
