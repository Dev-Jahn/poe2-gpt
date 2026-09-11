"""Human routes use verified order; prerequisites and adverse evidence block."""
import json
import time
from types import SimpleNamespace
import pytest
from poe2_companion.execution_plans import ExecutionRequest,ExecutionPageRequest,ExecutionDocument,create,page
from poe2_companion.observations import ObservationRequest,record
from poe2_companion.workflow_store import DecisionStore,WorkflowError
from poe2_companion.workflows import WorkflowService
from poe2_companion.experiment_models import InstillAmulet,EquipItem,EquipmentTransition
from poe2_companion.passive_execution import PassiveOrderRequest,order
from poe2_companion.catalog_models import NativeCatalog
from poe2_companion.inspection import InspectionPage
from test_workflow_catalog import node,BID
from test_workflow_purchases import document


def test_click_order_allocates_from_root_and_refunds_from_leaf_without_extra_nodes():
    nodes=[node(1,[2],True),node(2,[1,3]),node(3,[2,4]),node(4,[3])]
    catalog=NativeCatalog(tree_version='0_5',nodes=nodes,gems=[],runes=[],class_start_node_id=1)
    query=PassiveOrderRequest(build_id=BID,tree_revision='0_5',actions=[
        {'edit_index':0,'action':'allocate','node_ids':[4,3,2]},
        {'edit_index':1,'action':'refund','node_ids':[2,3,4]}])
    result=order(catalog,query)
    assert result.status=='verified' and not result.extra_nodes_added
    assert result.actions[0].node_ids==[2,3,4] and result.actions[1].node_ids==[4,3,2]
    gap=query.model_copy(deep=True);gap.actions[0].node_ids=[4]
    assert order(catalog,gap).status=='no_order_within_requested_nodes'
    catalog.nodes[2].special_allocation_rule=True
    assert order(catalog,query).status=='unsupported_node_rule'


async def test_unconfirmed_instill_unlock_returns_only_preceding_action():
    store=DecisionStore('m');doc=document(1,2,False,100)
    doc.request.edits=[InstillAmulet(type='instill_amulet',notable_node_id=123,recipe_catalog_id='instill:123')]
    store.save('alice',doc)
    result=await create(ExecutionRequest(experiment_id=doc.experiment_id),WorkflowService(SimpleNamespace(),store),'alice')
    assert result.status=='blocked' and result.primary_route_count==0
    assert 'unlock_unknown:amulet_instilling' in result.blocking_reasons
    assert 'whole_purchase_bill_required' in result.blocking_reasons
    assert [s.phase for s in result.next_steps]==['prerequisite']
    with pytest.raises(WorkflowError):page(ExecutionPageRequest(execution_id=result.execution_id),store,'bob')


async def test_native_order_receipt_includes_helper_and_new_adverse_report_invalidates_route():
    store=DecisionStore('m');doc=document(1,2,False,100)
    doc.request.edits=[EquipItem(type='equip_item',slot='helmet',source={'kind':'saved_item','saved_item_id':10})]
    doc.audit.transition_validation='verified'
    doc.audit.equipment_transition=EquipmentTransition(status='verified',states_evaluated=4,search_exhausted=False,
        optimality='fewest_actions_within_supplied_owned_choices',actions=[
            {'slot':'ring_left','action':'equip','saved_item_id':20,'temporary':True,'owned_helper':True},
            {'slot':'helmet','action':'equip','saved_item_id':10,'edit_index':0,'temporary':False,'owned_helper':False},
            {'slot':'ring_left','action':'unequip','temporary':False,'owned_helper':False}])
    store.save('alice',doc)
    async def inspect(request):return InspectionPage(build_id=request.build_id,section='equipment',
        records=[{'kind':'item','saved_item_id':request.saved_item_id,'base_type':'Gold Ring' if request.saved_item_id==20 else 'Iron Hat'}],total=1)
    workflow=WorkflowService(SimpleNamespace(inspect=inspect),store)
    result=await create(ExecutionRequest(experiment_id=doc.experiment_id),workflow,'alice')
    assert result.status=='ready_for_user_execution' and result.primary_route_count==1
    saved=store.get_artifact('alice','execution_plan',result.execution_id,ExecutionDocument)
    actions=[s for s in saved.steps if s.phase=='apply']
    assert actions[0].temporary and 'Gold Ring' in actions[0].instruction
    assert 'Iron Hat' in actions[1].instruction and '비우세요' in actions[2].instruction
    assert not saved.game_state_verified
    observation=record(store,'alice',ObservationRequest(base_build_id=doc.request.base_build_id,base_snapshot_digest=doc.request.base_snapshot_digest,
        observed_at_epoch=int(time.time()),related_experiment_id=doc.experiment_id,values=[{'kind':'resource_outcome',
            'resource':'energy_shield','maximum':100.,'minimum_during_encounter':0.,'encounter':'ritual','outcome':'depleted'}]))
    assert observation.observation_id in store.get('alice',doc.experiment_id).observation_ids
    assert page(ExecutionPageRequest(execution_id=result.execution_id),store,'alice').source_revision_changed
    blocked=await create(ExecutionRequest(experiment_id=doc.experiment_id),workflow,'alice')
    assert blocked.status=='blocked' and any('adverse_outcome_reported' in v for v in blocked.blocking_reasons)
    parts=[];offset=0
    while True:
        value=page(ExecutionPageRequest(execution_id=result.execution_id,section='exact_json',offset=offset),store,'alice')
        parts.append(value.content)
        if value.next_offset is None:break
        offset=value.next_offset
    assert json.loads(''.join(parts))==saved.model_dump(mode='json')


async def test_purchase_comparison_does_not_repeat_an_adverse_reported_plan():
    from poe2_companion.purchases import compare
    from test_workflow_purchases import request as purchase_request,cost
    store=DecisionStore('m');doc=document(1,2,False,100);store.save('alice',doc)
    record(store,'alice',ObservationRequest(base_build_id=doc.request.base_build_id,base_snapshot_digest=doc.request.base_snapshot_digest,
        observed_at_epoch=int(time.time()),related_experiment_id=doc.experiment_id,values=[{'kind':'resource_outcome',
            'resource':'energy_shield','maximum':100.,'minimum_during_encounter':0.,'encounter':'ritual','outcome':'depleted'}]))
    result=await compare(purchase_request([{'key':'failed','experiment_ids':[doc.experiment_id],'costs':[cost(1)]}]),
        SimpleNamespace(store=store,trade=None),'alice',None)
    assert not result.candidates[0].qualified_in_all_scenarios and result.primary_candidate_key is None
    assert result.candidates[0].user_observation_status=='adverse_outcome_reported'


def test_rollback_requires_actual_success_report_and_preserves_unchanged_fields():
    from poe2_companion.rollback_plans import RollbackRequest,RollbackDocument,create as rollback
    from poe2_companion.experiment_models import UnequipItem
    store=DecisionStore('m')
    good=document(1,2,False,100);bad=document(2,3,False,50)
    for doc in [good,bad]:
        doc.request.edits.append(UnequipItem(type='unequip_item',slot='weapon_off'))
        doc.state='applied';doc.applied_edit_indices=[0,1]
        store.save('alice',doc)
    request=RollbackRequest(failed_experiment_id=bad.experiment_id,last_successful_experiment_id=good.experiment_id)
    with pytest.raises(WorkflowError,match='matching_success_and_failure'):rollback(request,store,'alice')
    now=int(time.time())
    for doc,stable,stamp in [(good,True,now-30),(bad,False,now)]:
        record(store,'alice',ObservationRequest(base_build_id=doc.request.base_build_id,base_snapshot_digest=doc.request.base_snapshot_digest,
            observed_at_epoch=stamp,related_experiment_id=doc.experiment_id,values=[{'kind':'resource_outcome','resource':'energy_shield',
                'maximum':100.,'minimum_during_encounter':90. if stable else 0.,'encounter':'ritual','outcome':'stable' if stable else 'depleted'}]))
    result=rollback(request,store,'alice')
    assert result.changed_target_fields==1 and not result.rollback_transition_verified and not result.repeat_failed_plan
    saved=store.get_artifact('alice','rollback_plan',result.rollback_id,RollbackDocument)
    assert saved.changes[0].entity_ref=='gem:skill:s1:g1:n1'
    assert json.loads(saved.changes[0].desired_value_json)=={'native_level':2,'quality':0}
    assert saved.failure_observation_ids and saved.successful_observation_ids
    assert not saved.causal_effect_proven_by_user_reports
    with pytest.raises(WorkflowError):rollback(request,store,'bob')
