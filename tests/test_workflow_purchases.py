"""Budget completeness, scenario crossings and durable evidence are contracts."""
import json
import time
from types import SimpleNamespace
import pytest
from poe2_companion.capabilities import digest
from poe2_companion.calculation_config import CalculationConfiguration
from poe2_companion.engine_models import MetricCoverage
from poe2_companion.experiment_models import SetSupports
from poe2_companion.subjects import SubjectBinding, EvaluatedSubject
from poe2_companion.purchase_models import PurchaseComparisonRequest, PurchasePageRequest, PurchaseComparison
from poe2_companion.purchases import compare, page
from poe2_companion.workflow_store import DecisionStore, WorkflowError
from test_workflow_decisions import decision


def document(index,level,condition,score):
    value = decision(False)
    value.experiment_id = 'exp_'+f'{index:032x}'
    value.request.edits[0].native_level = level
    value.request.configuration = CalculationConfiguration(enemy_blinded=condition)
    target = value.request.target
    subject = EvaluatedSubject(skill_instance_id=target.skill_instance_id,skill_id='FireballPlayer',
        actor_ref=target.actor_ref,component_ref='FireballPlayer',weapon_set_id=1)
    value.calculation.result.subject = SubjectBinding(saved=subject,requested=target,evaluated=subject,status='matched',
        scenario_digest=digest({'configuration':value.request.configuration.model_dump(mode='json'),'combat_scenario':None}))
    value.calculation.result.stats[0].value = float(score)
    value.calculation.result.equipment_validity = 'pass'
    value.calculation.result.metric_coverage = [MetricCoverage(stat='Life',status='pass',reason='unconditional_resource_dependency_verified')]
    value.plan_digest = digest(value.request.model_dump(mode='json'))
    return value


class ScoutBatch:
    def __init__(self): self.calls = 0
    async def catalog(self,league,allow_stale):
        self.calls += 1
        assert not allow_stale
        return {'retrieved_at':'2026-09-11T09:00:00Z','data':{'reference_currencies':[
            {'api_id':'divine','relative_price':50.0},{'api_id':'chaos','relative_price':1.0}]}}


def cost(amount,currency='divine',kind='skill_gem',entity='skill:s1:g1:n1'):
    return {'edit_index':0,'kind':kind,'entity_id':entity,'evidence':'user_reported_price',
        'unit_price':{'amount':float(amount),'currency':currency},'observed_at_epoch':int(time.time())}


def request(candidates,**kwargs):
    return PurchaseComparisonRequest(league='Forbidden Rites',declared_character_league='Forbidden Rites',
        budget={'amount':34.0,'currency':'divine'},liquid_budget={'amount':1.0,'currency':'divine'},
        weights=[{'stat':'Life','weight':1.0}],candidates=candidates,**kwargs)


async def test_single_fx_snapshot_crossing_frontier_and_restart(tmp_path):
    store = DecisionStore('member',tmp_path/'state',tmp_path/'keys'/'key')
    docs = [document(1,2,False,100),document(2,2,True,200),document(3,3,False,200),document(4,3,True,100)]
    for row in docs: store.save('alice',row)
    workflow = SimpleNamespace(store=store,trade=None)
    scout = ScoutBatch()
    result = await compare(request([
        {'key':'expensive','experiment_ids':[d.experiment_id for d in docs[:2]],'costs':[cost(20)]},
        {'key':'cheap','experiment_ids':[d.experiment_id for d in docs[2:]],'costs':[cost(100,'chaos')]}],persist_comparison=True),workflow,'alice',scout)
    assert scout.calls == 1
    assert [c.total_estimated_cost for c in result.candidates] == [20,2]
    assert [c.liquid_currency_shortfall for c in result.candidates] == [19,1]
    assert len(result.rank_crossings) == 1 and result.primary_candidate_key is None
    assert all(c.on_robust_frontier for c in result.candidates)
    assert not result.fx.executable_exchange_rate and result.fx.source_updated_at is None
    assert not result.proposal_debits_currency
    stored = store.get_artifact('alice','purchase_comparison',result.comparison_id,PurchaseComparison)
    assert all(d.state == 'proposed' for d in docs)
    assert not stored.arbitrary_probabilities_assigned
    store.close()
    store = DecisionStore('member',tmp_path/'state',tmp_path/'keys'/'key')
    workflow.store = store
    chunks = []
    offset = 0
    while True:
        part = page(PurchasePageRequest(comparison_id=result.comparison_id,section='exact_json',offset=offset),workflow,'alice')
        assert part.artifact_digest == result.artifact_digest
        chunks.append(part.content)
        if part.next_offset is None: break
        offset = part.next_offset
    assert json.loads(''.join(chunks)) == stored.model_dump(mode='json')
    with pytest.raises(WorkflowError,match='unavailable'):
        page(PurchasePageRequest(comparison_id=result.comparison_id),workflow,'bob')
    store.delete_artifact('bob','purchase_comparison',result.comparison_id)
    assert store.get_artifact('alice','purchase_comparison',result.comparison_id,PurchaseComparison)
    store.delete_artifact('alice','purchase_comparison',result.comparison_id)
    with pytest.raises(WorkflowError,match='unavailable'):
        page(PurchasePageRequest(comparison_id=result.comparison_id),workflow,'alice')
    store.close()


async def test_missing_socket_bill_and_stale_price_do_not_certify_budget():
    store = DecisionStore('member')
    doc = document(1,2,False,150)
    doc.request.edits = [SetSupports(type='set_supports',skill_instance_id='skill:s1:g1:n1',
        support_gem_ids=['Metadata/Items/Gems/TestSupport'],observed_socket_capacity=1,
        original_observed_socket_capacity=0,socket_capacity_evidence='planned_upgrade')]
    store.save('alice',doc)
    workflow = SimpleNamespace(store=store,trade=None)
    req = request([{'key':'upgrade','experiment_ids':[doc.experiment_id],
        'costs':[cost(1,kind='support_gem',entity='Metadata/Items/Gems/TestSupport')]}])
    result = await compare(req,workflow,'alice',None)
    assert result.candidates[0].known_cost == 1 and result.candidates[0].total_estimated_cost is None
    assert result.candidates[0].missing_cost_count == 1
    assert result.candidates[0].budget_status == 'incomplete_costs' and result.primary_candidate_key is None
    req.candidates[0].costs[0].observed_at_epoch -= 400
    stale = await compare(req,workflow,'alice',None)
    assert stale.candidates[0].missing_cost_count == 2 and stale.candidates[0].known_cost == 0


async def test_mismatched_scenarios_rejected_before_price_lookup():
    store = DecisionStore('member')
    a,b = document(1,2,False,100),document(2,3,True,200)
    for d in (a,b): store.save('alice',d)
    scout = ScoutBatch()
    with pytest.raises(WorkflowError,match='scenarios_mismatch'):
        await compare(request([{'key':'a','experiment_ids':[a.experiment_id],'costs':[cost(1)]},
            {'key':'b','experiment_ids':[b.experiment_id],'costs':[cost(10,'chaos')]}]),SimpleNamespace(store=store,trade=None),'alice',scout)
    assert scout.calls == 0
