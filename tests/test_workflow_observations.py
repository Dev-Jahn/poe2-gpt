import time
import pytest
from poe2_companion.observations import ObservationRequest,ObservationPageRequest,record,page
from poe2_companion.workflow_store import DecisionStore,WorkflowError


def request(**values):
    data={'base_build_id':'bld_'+'1'*32,'base_snapshot_digest':'a'*64,'observed_at_epoch':int(time.time()),
        'values':[{'kind':'available_points','ordinary':2,'ascendancy':0}]}
    data.update(values)
    return ObservationRequest.model_validate(data)


def test_reports_remain_pending_and_conflicts_do_not_merge(tmp_path):
    store=DecisionStore('owner',tmp_path/'state',tmp_path/'keys'/'key')
    first=record(store,'alice',request(persist_observation=True))
    second=record(store,'alice',request(values=[{'kind':'available_points','ordinary':0,'ascendancy':2}],persist_observation=True))
    assert first.status=='pending_source_confirmation' and first.engine_verified is False
    result=page(store,'alice',ObservationPageRequest(observation_ids=[first.observation_id,second.observation_id]))
    assert result.conflicting_fields==['available_points']
    assert result.next_action=='clarify_conflicting_observations' and not result.overlay_applied_to_engine
    store.close();store=DecisionStore('owner',tmp_path/'state',tmp_path/'keys'/'key')
    assert store.get_observation('alice',first.observation_id)==first
    with pytest.raises(WorkflowError,match='unavailable'):store.get_observation('bob',first.observation_id)
    store.delete_observation('bob',first.observation_id)
    assert store.get_observation('alice',first.observation_id)
    store.delete_observation('alice',first.observation_id)
    with pytest.raises(WorkflowError,match='unavailable'):store.get_observation('alice',first.observation_id)
    store.close()


def test_post_application_resource_report_advances_observed_without_source_confirmation():
    from test_workflow_decisions import decision
    store=DecisionStore('owner');doc=decision(False)
    doc.state='applied';doc.applied_edit_indices=[0];doc.last_reported_application_at_epoch=int(time.time())-1
    store.save('alice',doc)
    row=record(store,'alice',request(related_experiment_id=doc.experiment_id,
        values=[{'kind':'resource_outcome','resource':'energy_shield','maximum':1000.,'minimum_during_encounter':0.,'encounter':'ritual','outcome':'depleted'}]))
    saved=store.get('alice',doc.experiment_id)
    assert saved.state=='observed' and saved.source_confirmation=='pending_source_confirmation'
    assert saved.applied_edit_indices==[0] and row.observation_id in saved.observation_ids
