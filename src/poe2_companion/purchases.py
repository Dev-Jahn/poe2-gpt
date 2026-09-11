"""One FX batch, complete bills and scenario crossings for real joint decisions."""
from __future__ import annotations
from decimal import Decimal
from pathlib import Path
import secrets
import time
from typing import TYPE_CHECKING, Literal
from .builds import bounded_dto, BuildError
from .capabilities import canonical, digest
from .equipment import EquipmentService, FX
from .engine import verify_character_league
from .engine_models import ENGINE_COMMIT, ENGINE_DATA_COMMIT
from .experiment_models import (EquipItem, SetGem, SetSupports, SocketRune, InstillAmulet,
    RefundPassives, SetAscendancy)
from .purchase_models import (PurchaseComparisonRequest, PurchaseComparison, PurchaseSummary,
    PurchaseCandidateSummary, CandidateDecision, ScenarioDecision, BillLine, RankCrossing,
    PurchasePageRequest, PurchasePage, CostKind, CostEvidence)
from .workflow_store import WorkflowError

if TYPE_CHECKING:
    from .workflows import WorkflowService
    from .workflow_store import DecisionDocument
    from .scout import Scout


def normalized_plan(document: DecisionDocument) -> str:
    request = document.request
    return digest({'base':request.base_snapshot_digest,'tree':request.tree_revision,
        'data':request.engine_data_commit,'target':request.target.model_dump(mode='json'),
        'edits':[e.model_dump(mode='json') for e in request.edits]})


def scenario(document: DecisionDocument, request: PurchaseComparisonRequest) -> ScenarioDecision:
    snapshot = document.calculation.result
    target = document.request.target
    binding = snapshot.subject if snapshot else None
    if binding is None or binding.status != 'matched' or binding.requested != target:
        scenario_digest = digest({'configuration':document.request.configuration.model_dump(mode='json') if document.request.configuration else None,
            'combat_scenario':document.request.combat_scenario.model_dump(mode='json') if document.request.combat_scenario else None})
    else: scenario_digest = binding.scenario_digest
    wanted = {w.stat for w in request.weights} | {c.stat for c in request.constraints}
    values = {s.name:s.value for s in snapshot.stats} if snapshot else {}
    covered = {c.stat for c in snapshot.metric_coverage if c.status == 'pass'} if snapshot else set()
    unresolved: list[str] = sorted(s for s in wanted if s not in values or s not in covered)
    failures: list[str] = [c.stat for c in request.constraints if c.stat in values and values[c.stat] < c.minimum]
    score = None
    if all(w.stat in values for w in request.weights):
        score = sum(min(values[w.stat],w.cap) * w.weight if w.cap is not None else values[w.stat] * w.weight for w in request.weights)
    equipment = snapshot.equipment_validity or snapshot.validation if snapshot else 'indeterminate'
    qualified = bool(snapshot and binding and binding.status == 'matched' and equipment == 'pass'
        and not failures and not unresolved and document.audit.status == 'valid_changeset'
        and document.audit.transition_validation in {'verified','no_equipment_transition'})
    return ScenarioDecision(experiment_id=document.experiment_id,scenario_digest=scenario_digest,
        plan_digest=document.plan_digest,score=score,metrics=[s for s in snapshot.stats if s.name in wanted] if snapshot else [],
        constraint_failures=failures,missing_or_uncovered_metrics=unresolved,equipment_validity=equipment,
        native_joint_validation=snapshot.validation if snapshot else 'not_evaluated',qualified=qualified)


def required_components(document: DecisionDocument) -> list[tuple[int,CostKind,str,float]]:
    required: list[tuple[int,CostKind,str,float]] = []
    for index,edit in enumerate(document.request.edits):
        if isinstance(edit,EquipItem) and edit.source.kind == 'retained_trade_listing':
            required.append((index,'item',edit.source.listing_ref,1))
        elif isinstance(edit,SetGem):
            required.append((index,'skill_gem',edit.skill_instance_id,1))
            if edit.quality: required.append((index,'gem_quality',edit.skill_instance_id,1))
        elif isinstance(edit,SetSupports):
            required.extend((index,'support_gem',identifier,1) for identifier in edit.support_gem_ids)
            before = edit.original_observed_socket_capacity
            if edit.socket_capacity_evidence == 'planned_upgrade' or before is not None and edit.observed_socket_capacity > before:
                # A quote is for the whole socket upgrade, not an assumed
                # interchangeable currency per socket or another gem's sockets.
                required.append((index,'socket_upgrade',edit.skill_instance_id,1))
        elif isinstance(edit,SocketRune): required.append((index,'rune',edit.rune_catalog_id,1))
        elif isinstance(edit,InstillAmulet): required.append((index,'instill_recipe',edit.recipe_catalog_id,1))
        elif isinstance(edit,RefundPassives) or isinstance(edit,SetAscendancy) and edit.refund_node_ids:
            required.append((index,'respec','passive-refund',1))
    return required


async def compare(request: PurchaseComparisonRequest, workflow: WorkflowService, owner: str, scout: Scout | None) -> PurchaseSummary:
    now = int(time.time())
    if request.persist_comparison and workflow.store.db is None: raise WorkflowError('workflow_persistence_unconfigured')
    documents = [[workflow.store.get(owner,i) for i in candidate.experiment_ids] for candidate in request.candidates]
    all_documents = [document for group in documents for document in group]
    first = all_documents[0]
    identity = (first.request.base_build_id,first.request.base_snapshot_digest,first.request.target)
    for document in all_documents:
        if (document.request.base_build_id,document.request.base_snapshot_digest,document.request.target) != identity:
            raise WorkflowError('purchase_comparison_subject_mismatch')
        if document.calculation.engine_commit != ENGINE_COMMIT or document.calculation.engine_data_commit != ENGINE_DATA_COMMIT:
            raise WorkflowError('purchase_comparison_engine_revision_mismatch')
    await verify_character_league(first.calculation.baseline.origin,request.league,request.declared_character_league,scout)
    grouped_scenarios = [[scenario(document,request) for document in group] for group in documents]
    scenario_sets = [{s.scenario_digest for s in group} for group in grouped_scenarios]
    if any(len(keys) != len(group) for keys,group in zip(scenario_sets,grouped_scenarios,strict=True)) or any(keys != scenario_sets[0] for keys in scenario_sets):
        raise WorkflowError('purchase_comparison_scenarios_mismatch')
    bills = []
    for candidate,group in zip(request.candidates,documents,strict=True):
        if len({normalized_plan(document) for document in group}) != 1: raise WorkflowError('candidate_changes_differ_between_scenarios')
        evidence = {(c.edit_index,c.kind,c.entity_id):c for c in candidate.costs}
        required = required_components(group[0])
        lines = []
        for index,kind,identifier,quantity in required:
            key = (index,kind,identifier)
            if kind == 'item':
                edit = group[0].request.edits[index]
                assert isinstance(edit,EquipItem) and edit.source.kind == 'retained_trade_listing'
                # Price comes from the very listing used by the private importer.
                # No new search or repeated provider fetch during comparison.
                listing = None
                if workflow.trade is not None:
                    try:
                        entry = workflow.trade.retained(edit.source.search_id)
                        if entry['request'].league != request.league: raise WorkflowError('purchase_listing_league_mismatch')
                        listing = entry['rows'].get(identifier)
                    except WorkflowError: raise
                    except Exception: pass
                fresh = listing is not None and listing.price is not None and 0 <= now-listing.observed_at_epoch <= request.maximum_price_age_seconds
                lines.append(BillLine(edit_index=index,kind=kind,entity_id=identifier,quantity=quantity,normalized_cost=None,
                    original_price=listing.price if listing else None,observed_at_epoch=listing.observed_at_epoch if listing else None,
                    status='retained_listing_ask' if fresh else 'stale' if listing else 'missing'))
                evidence.pop(key,None)
                continue
            supplied = evidence.pop(key,None)
            if supplied is None:
                lines.append(BillLine(edit_index=index,kind=kind,entity_id=identifier,quantity=quantity,normalized_cost=None,status='missing'))
            else:
                if supplied.quantity < quantity: raise WorkflowError('bill_component_quantity_insufficient')
                lines.append(cost_line(supplied,now,request.maximum_price_age_seconds))
        for supplied in evidence.values():
            if supplied.edit_index is not None and supplied.edit_index >= len(group[0].request.edits):
                raise WorkflowError('bill_edit_index_unavailable')
            lines.append(cost_line(supplied,now,request.maximum_price_age_seconds))
        bills.append(lines)
    currencies = {line.original_price.currency for bill in bills for line in bill if line.original_price is not None}
    if currencies <= {request.budget.currency}:
        fx = FX(reference_currency=request.budget.currency,rates={request.budget.currency:1.0},source='same_currency_no_conversion',retrieved_at=None)
    else:
        if scout is None: raise WorkflowError('comparison_currency_unavailable')
        fx = await EquipmentService(Path('/unused'),scout).fx(request.league,currencies,request.budget.currency)
    reserve = Decimal(str(request.budget.amount))*Decimal(str(request.reserve_percent))/100
    spendable = Decimal(str(request.budget.amount))-reserve
    candidates = []
    for candidate,group,scenarios,bill in zip(request.candidates,documents,grouped_scenarios,bills,strict=True):
        total = Decimal(0)
        complete = True
        gold = 0
        gold_known = True
        for line in bill:
            if line.status in {'missing','stale'}:
                complete = False
                if line.kind == 'respec': gold_known = False
                continue
            if line.original_price is not None:
                amount = Decimal(str(line.original_price.amount))*Decimal(str(line.quantity))*Decimal(str(fx.rates[line.original_price.currency]))
                total += amount
                line.normalized_cost = float(amount)
            elif line.status == 'user_confirmed_owned': line.normalized_cost = 0
            elif line.gold_cost is not None: gold += line.gold_cost
        liquid_shortfall = max(0,float(total+reserve)-request.liquid_budget.amount) if request.liquid_budget is not None else None
        gold_sufficient = gold <= request.gold_available if gold_known and request.gold_available is not None else True if gold_known and gold == 0 else None
        budget_status: Literal['over_budget','within_estimated_budget','incomplete_costs'] = 'over_budget' if total > spendable else 'within_estimated_budget' if complete else 'incomplete_costs'
        candidates.append(CandidateDecision(key=candidate.key,edit_plan_digest=normalized_plan(group[0]),scenarios=scenarios,bill=bill,
            known_cost=float(total),total_estimated_cost=float(total) if complete else None,gold_required=gold if gold_known else None,
            budget_status=budget_status,liquid_currency_shortfall=liquid_shortfall,gold_sufficient=gold_sufficient,
            qualified_in_all_scenarios=all(s.qualified for s in scenarios) and complete and total <= spendable and gold_sufficient is True))
    crossings = frontier(candidates)
    qualified = [c for c in candidates if c.qualified_in_all_scenarios and c.on_robust_frontier]
    # A crossing is preserved even when a cheap candidate has better efficiency.
    # No single best route is asserted until the explicit scenario is resolved.
    primary = qualified[0].key if len(qualified) == 1 else None
    identifier = 'cmp_'+secrets.token_hex(16)
    comparison = PurchaseComparison(comparison_id=identifier,request=request,candidates=candidates,fx=fx,
        reserve_amount=float(reserve),spendable_budget=float(spendable),primary_candidate_key=primary,rank_crossings=crossings,
        created_at_epoch=now,quote_recheck_after_epoch=min([now+request.maximum_price_age_seconds]+[line.observed_at_epoch+request.maximum_price_age_seconds for bill in bills for line in bill if line.observed_at_epoch is not None]),expires_at_epoch=now+(30*86400 if request.persist_comparison else 3600),artifact_digest='0'*64)
    comparison.artifact_digest = digest(comparison.model_dump(mode='json',exclude={'artifact_digest'}))
    workflow.store.save_artifact(owner,'purchase_comparison',identifier,comparison,comparison.expires_at_epoch,request.persist_comparison)
    return summary(comparison)


def cost_line(cost: CostEvidence, now: int, age: int) -> BillLine:
    if cost.observed_at_epoch is not None and cost.observed_at_epoch > now+300: raise WorkflowError('price_timestamp_in_future')
    if cost.kind == 'respec' and cost.unit_price is not None: raise WorkflowError('respec_requires_gold_cost')
    status: Literal['missing','stale','user_reported_price','user_confirmed_owned'] = 'missing' if cost.evidence == 'unknown' else cost.evidence
    if status == 'user_reported_price' and (cost.observed_at_epoch is None or not 0 <= now-cost.observed_at_epoch <= age): status = 'stale'
    return BillLine(edit_index=cost.edit_index,kind=cost.kind,entity_id=cost.entity_id,quantity=cost.quantity,
        normalized_cost=None,status=status,original_price=cost.unit_price,gold_cost=cost.gold_cost,
        observed_at_epoch=cost.observed_at_epoch)


def frontier(candidates: list[CandidateDecision]) -> list[RankCrossing]:
    crossings = []
    scores = {c.key:{s.scenario_digest:s.score for s in c.scenarios} for c in candidates}
    for index,a in enumerate(candidates):
        for b in candidates[index+1:]:
            common = [(key,x,scores[b.key].get(key)) for key,x in scores[a.key].items()]
            left = [key for key,x,y in common if x is not None and y is not None and x > y]
            right = [key for key,x,y in common if x is not None and y is not None and x < y]
            if left and right: crossings.append(RankCrossing(candidate_a=a.key,candidate_b=b.key,a_better_scenarios=left,b_better_scenarios=right))
        if not a.qualified_in_all_scenarios: continue
        a.on_robust_frontier = True
        for b in candidates:
            if b is a or not b.qualified_in_all_scenarios: continue
            pairs = [(x,scores[b.key].get(key)) for key,x in scores[a.key].items()]
            if (a.total_estimated_cost is not None and b.total_estimated_cost is not None and b.total_estimated_cost <= a.total_estimated_cost
                    and all(x is not None and y is not None and y >= x for x,y in pairs)
                    and (b.total_estimated_cost < a.total_estimated_cost or any(x is not None and y is not None and y > x for x,y in pairs))):
                a.on_robust_frontier = False
                break
    return crossings


def summary(document: PurchaseComparison) -> PurchaseSummary:
    rows = []
    for candidate in document.candidates:
        scores = [s.score for s in candidate.scenarios if s.score is not None]
        rows.append(PurchaseCandidateSummary(key=candidate.key,total_estimated_cost=candidate.total_estimated_cost,
            known_cost=candidate.known_cost,gold_required=candidate.gold_required,budget_status=candidate.budget_status,
            liquid_currency_shortfall=candidate.liquid_currency_shortfall,qualified_in_all_scenarios=candidate.qualified_in_all_scenarios,
            on_robust_frontier=candidate.on_robust_frontier,score_minimum=min(scores) if scores else None,score_maximum=max(scores) if scores else None,
            missing_cost_count=sum(line.status in {'missing','stale'} for line in candidate.bill)))
    result = PurchaseSummary(comparison_id=document.comparison_id,artifact_digest=document.artifact_digest,candidates=rows,
        primary_candidate_key=document.primary_candidate_key,rank_crossings=list(document.rank_crossings),rank_crossings_total=len(document.rank_crossings),quote_recheck_after_epoch=document.quote_recheck_after_epoch,fx=document.fx,
        spendable_budget=document.spendable_budget,expires_at_epoch=document.expires_at_epoch)
    while True:
        try: return bounded_dto(result)
        except BuildError:
            if not result.rank_crossings: raise
            result.rank_crossings.pop();result.rank_crossings_truncated=True


def page(request: PurchasePageRequest, workflow: WorkflowService, owner: str) -> PurchasePage:
    document = workflow.store.get_artifact(owner,'purchase_comparison',request.comparison_id,PurchaseComparison)
    if document.artifact_digest != digest(document.model_dump(mode='json',exclude={'artifact_digest'})):
        raise WorkflowError('artifact_integrity_failure')
    candidates = [c for c in document.candidates if request.candidate_key is None or c.key == request.candidate_key]
    if request.candidate_key is not None and not candidates: raise WorkflowError('purchase_candidate_unavailable')
    if request.section == 'exact_json': text = canonical(document.model_dump(mode='json'))
    elif request.section == 'bill': text = canonical([{'candidate':c.key,'bill':[r.model_dump(mode='json') for r in c.bill]} for c in candidates])
    elif request.section == 'scenarios': text = canonical([{'candidate':c.key,'scenarios':[r.model_dump(mode='json') for r in c.scenarios]} for c in candidates])
    elif document.primary_candidate_key is None:
        text = '실행 경로를 확정하지 않았습니다. 미확정 비용·요구 조건을 확인하고, 순위가 바뀌는 전투 조건을 선택하세요.'
    else:
        primary = next(c for c in document.candidates if c.key == document.primary_candidate_key)
        text = ('1. 같은 캐릭터 스냅샷과 전투 조건인지 확인하세요.\n'
            '2. 젬 소켓·주입·전직 해금과 재화 보유량을 확인하고, 보관된 비용표의 매물과 가격을 다시 확인하세요.\n'
            f'3. 예상 총액 {primary.total_estimated_cost:g} {document.request.budget.currency}, 예비비 {document.reserve_amount:g}를 확보하세요.\n'
            '4. 검증된 계획의 장착·패시브·보조 젬 변경 순서대로 적용하세요. 순서가 검증되지 않았다면 진행하지 마세요.\n'
            '5. 요구 능력치, 저항, 남은 자원과 실제 회복을 확인하세요. 회복이 악화되면 다음 구매를 중단하고 마지막 성공 상태와 비교하세요.\n'
            '6. 적용한 단계만 기록하고 캐릭터를 다시 조회하세요. 제안은 보유 재화에서 차감되지 않습니다.\n'
            '상세 실행 계획: '+primary.scenarios[0].experiment_id)
    end = request.offset+request.limit
    fragment = text[request.offset:end]
    while len(fragment.encode()) > 4500: end-=1;fragment=text[request.offset:end]
    return bounded_dto(PurchasePage(comparison_id=document.comparison_id,artifact_digest=document.artifact_digest,
        section=request.section,content=fragment,total=len(text),next_offset=end if end<len(text) else None,
        quote_recheck_required=int(time.time())>=document.quote_recheck_after_epoch))
