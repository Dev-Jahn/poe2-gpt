"""Complete cost evidence and comparable, immutable scenario decisions."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .builds import DTO, PlayerStat
from .profiles import Digest
from .experiment_models import ExperimentID
from .engine_models import CharacterWeight, CharacterConstraint
from .equipment import Price, FX, LeagueName

ComparisonID = Annotated[str, Field(pattern=r'^cmp_[0-9a-f]{32}$')]
CostKind = Literal['item','support_gem','skill_gem','gem_quality','socket_upgrade','rune','instill_recipe','respec','temporary_item','fee']
EntityID = Annotated[str, Field(min_length=1, max_length=180, pattern=r'^[^\x00-\x1f\x7f]+$')]


class CostEvidence(DTO):
    edit_index: Annotated[int, Field(ge=0, le=31)] | None = None
    kind: CostKind
    entity_id: EntityID
    quantity: Annotated[float, Field(gt=0, le=1000000, allow_inf_nan=False)] = 1
    evidence: Literal['user_reported_price','user_confirmed_owned','unknown']
    unit_price: Price | None = None
    gold_cost: Annotated[int, Field(ge=0, le=1000000000000)] | None = None
    observed_at_epoch: Annotated[int, Field(ge=0, le=100000000000)] | None = None

    @model_validator(mode='after')
    def valid_evidence(self) -> Self:
        if self.unit_price is not None and self.gold_cost is not None: raise ValueError('one_cost_unit_required')
        if self.evidence == 'user_reported_price' and ((self.unit_price is None and self.gold_cost is None) or self.observed_at_epoch is None):
            raise ValueError('quoted_cost_requires_price_and_time')
        if self.evidence != 'user_reported_price' and (self.unit_price is not None or self.gold_cost is not None):
            raise ValueError('unpriced_evidence_cannot_supply_price')
        return self


class DecisionCandidate(DTO):
    key: Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{1,32}$')]
    # One identical edit plan under one or more explicit scenarios.
    experiment_ids: Annotated[list[ExperimentID], Field(min_length=1, max_length=4)]
    costs: Annotated[list[CostEvidence], Field(max_length=64)] = Field(default_factory=list)


class PurchaseComparisonRequest(DTO):
    league: LeagueName
    declared_character_league: LeagueName | None = None
    budget: Price
    liquid_budget: Price | None = None
    gold_available: Annotated[int, Field(ge=0, le=1000000000000)] | None = None
    reserve_percent: Annotated[float, Field(ge=0, le=99, allow_inf_nan=False)] = 0
    candidates: Annotated[list[DecisionCandidate], Field(min_length=1, max_length=6)]
    weights: Annotated[list[CharacterWeight], Field(min_length=1, max_length=4)]
    constraints: Annotated[list[CharacterConstraint], Field(max_length=8)] = Field(default_factory=list)
    maximum_price_age_seconds: Annotated[int, Field(ge=1, le=3600)] = 300
    persist_comparison: bool = False

    @model_validator(mode='after')
    def distinct(self) -> Self:
        if len({c.key for c in self.candidates}) != len(self.candidates): raise ValueError('duplicate_candidate_key')
        if len({w.stat for w in self.weights}) != len(self.weights): raise ValueError('duplicate_weight')
        if len({c.stat for c in self.constraints}) != len(self.constraints): raise ValueError('duplicate_constraint')
        if self.liquid_budget is not None and self.liquid_budget.currency != self.budget.currency:
            raise ValueError('liquid_budget_must_use_reference_currency')
        for candidate in self.candidates:
            if len(set(candidate.experiment_ids)) != len(candidate.experiment_ids): raise ValueError('duplicate_scenario_experiment')
            keys = [(c.edit_index,c.kind,c.entity_id) for c in candidate.costs]
            if len(set(keys)) != len(keys): raise ValueError('duplicate_cost_evidence')
        return self


class BillLine(DTO):
    edit_index: int | None
    kind: CostKind
    entity_id: str
    quantity: float
    normalized_cost: float | None
    gold_cost: int | None = None
    original_price: Price | None = None
    observed_at_epoch: int | None = None
    status: Literal['retained_listing_ask','user_reported_price','user_confirmed_owned','missing','stale']
    availability_verified: Literal[False] = False


class ScenarioDecision(DTO):
    experiment_id: ExperimentID
    scenario_digest: Digest
    plan_digest: Digest
    score: float | None
    metrics: Annotated[list[PlayerStat], Field(max_length=12)]
    constraint_failures: Annotated[list[str], Field(max_length=8)]
    missing_or_uncovered_metrics: Annotated[list[str], Field(max_length=12)]
    equipment_validity: Literal['pass','fail','indeterminate']
    native_joint_validation: Literal['pass','fail','indeterminate','not_evaluated']
    qualified: bool


class CandidateDecision(DTO):
    key: str
    edit_plan_digest: Digest
    scenarios: Annotated[list[ScenarioDecision], Field(max_length=4)]
    bill: Annotated[list[BillLine], Field(max_length=512)]
    known_cost: float
    total_estimated_cost: float | None
    gold_required: int | None
    budget_status: Literal['within_estimated_budget','over_budget','incomplete_costs']
    liquid_currency_shortfall: float | None
    executable_exchange_quote: Literal[False] = False
    gold_sufficient: bool | None
    price_is_realized_transaction: Literal[False] = False
    qualified_in_all_scenarios: bool
    on_robust_frontier: bool = False


class RankCrossing(DTO):
    candidate_a: str
    candidate_b: str
    a_better_scenarios: Annotated[list[Digest], Field(max_length=4)]
    b_better_scenarios: Annotated[list[Digest], Field(max_length=4)]


class PurchaseComparison(DTO):
    comparison_id: ComparisonID
    request: PurchaseComparisonRequest
    candidates: Annotated[list[CandidateDecision], Field(max_length=6)]
    fx: FX
    reserve_amount: float
    spendable_budget: float
    primary_candidate_key: str | None
    rank_crossings: Annotated[list[RankCrossing], Field(max_length=15)]
    created_at_epoch: int
    quote_recheck_after_epoch: int
    expires_at_epoch: int
    artifact_digest: Digest
    schema_revision: Literal['purchase-comparison-v1'] = 'purchase-comparison-v1'
    global_optimum_claimed: Literal[False] = False
    comparison_scope: Literal['supplied_joint_decisions_under_matching_explicit_scenarios'] = 'supplied_joint_decisions_under_matching_explicit_scenarios'
    arbitrary_probabilities_assigned: Literal[False] = False
    proposal_debits_currency: Literal[False] = False


class PurchaseCandidateSummary(DTO):
    key: str
    total_estimated_cost: float | None
    known_cost: float
    gold_required: int | None
    budget_status: Literal['within_estimated_budget','over_budget','incomplete_costs']
    liquid_currency_shortfall: float | None
    qualified_in_all_scenarios: bool
    on_robust_frontier: bool
    score_minimum: float | None
    score_maximum: float | None
    missing_cost_count: int


class PurchaseSummary(DTO):
    comparison_id: ComparisonID
    artifact_digest: Digest
    candidates: Annotated[list[PurchaseCandidateSummary], Field(max_length=6)]
    primary_candidate_key: str | None
    rank_crossings: Annotated[list[RankCrossing], Field(max_length=15)]
    rank_crossings_total: int
    rank_crossings_truncated: bool = False
    quote_recheck_after_epoch: int
    fx: FX
    spendable_budget: float
    expires_at_epoch: int
    global_optimum_claimed: Literal[False] = False
    proposal_debits_currency: Literal[False] = False
    detail_tool: Literal['get_purchase_comparison'] = 'get_purchase_comparison'


class PurchasePageRequest(DTO):
    comparison_id: ComparisonID
    section: Literal['bill','scenarios','exact_json','primary_route'] = 'primary_route'
    candidate_key: Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{1,32}$')] | None = None
    offset: Annotated[int, Field(ge=0, le=1000000)] = 0
    limit: Annotated[int, Field(ge=1, le=1500)] = 1000


class PurchasePage(DTO):
    comparison_id: ComparisonID
    artifact_digest: Digest
    section: Literal['bill','scenarios','exact_json','primary_route']
    content: Annotated[str, Field(max_length=5000)]
    total: int
    next_offset: int | None
    comparison_is_live_state: Literal[False] = False
    quote_recheck_required: bool


class DeletePurchaseComparison(DTO):
    comparison_id: ComparisonID
