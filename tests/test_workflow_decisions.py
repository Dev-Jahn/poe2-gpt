"""Handoff 006/015: persistent owner isolation and exact revision semantics."""
import time
import pytest
from poe2_companion.capabilities import digest
from poe2_companion.engine import EngineClient
from poe2_companion.engine_models import ENGINE_DATA_COMMIT,EngineSnapshot,EngineCalculation
from poe2_companion.experiment_models import ExperimentRequest,ExperimentAudit
from poe2_companion.workflow_store import DecisionStore,DecisionDocument,WorkflowError
from poe2_companion.workflows import WorkflowService,PlanPageRequest,PlanTransition

BID='bld_'+'1'*32
EID='exp_'+'2'*32


def decision(persistent=True):
    request=ExperimentRequest(base_build_id=BID,base_snapshot_digest='a'*64,tree_revision='0_5',
        engine_data_commit=ENGINE_DATA_COMMIT,target={'skill_instance_id':'skill:s1:g1:n1','actor_ref':'player','weapon_set_id':1},
        edits=[{'type':'set_gem','skill_instance_id':'skill:s1:g1:n1','native_level':2,'quality':0}],persist_decision=persistent)
    snapshot=EngineSnapshot(stats=[{'name':'Life','value':100.0}],equipped=[],issues=[],issue_count=0,
        validation='pass',active_weapon_set=1,main_skill_group=1)
    calculation=EngineCalculation(build_id=BID,calculation_id='calc_'+'3'*32,diagnostics_expires_at_epoch=1,
        calculated_at_epoch=1,baseline=snapshot,result=snapshot)
    return DecisionDocument(experiment_id=EID,request=request,plan_digest=digest(request.model_dump(mode='json')),
        audit=ExperimentAudit(status='valid_changeset',failures=[],applied_edits=[],transition_validation='no_equipment_transition'),
        calculation=calculation,created_at_epoch=int(time.time()),expires_at_epoch=int(time.time())+3600)


async def test_restart_preserves_historical_decision_not_live_calculation(tmp_path):
    key=tmp_path/'keys'/'key'
    store=DecisionStore('owner',tmp_path/'state',key)
    original=decision();store.save('issuer\0alice',original)
    store.close()
    assert b'skill:s1:g1:n1' not in (tmp_path/'state'/'decisions.sqlite3').read_bytes()
    store=DecisionStore('owner',tmp_path/'state',key)
    with pytest.raises(WorkflowError,match='unavailable'): store.get('issuer\0bob',EID)
    engine=EngineClient('/unused')
    workflow=WorkflowService(engine,store)
    try:
        page=workflow.page('issuer\0alice',PlanPageRequest(experiment_id=EID,section='plan_json'))
        assert page.calculation_replayability=='stored_decision_only'
        assert page.state=='proposed' and not page.saved_base_is_current_character
        accepted=workflow.transition('issuer\0alice',PlanTransition(experiment_id=EID,expected_revision=1,
            expected_plan_digest=original.plan_digest,state='accepted'))
        assert accepted.state=='accepted' and accepted.source_confirmation=='pending_source_confirmation'
        with pytest.raises(WorkflowError,match='revision_conflict'):
            workflow.transition('issuer\0alice',PlanTransition(experiment_id=EID,expected_revision=1,
                expected_plan_digest=original.plan_digest,state='applied',applied_edit_indices=[0]))
        applied=workflow.transition('issuer\0alice',PlanTransition(experiment_id=EID,expected_revision=2,
            expected_plan_digest=original.plan_digest,state='applied',applied_edit_indices=[0]))
        assert applied.state=='applied' and applied.artifact_digest==page.artifact_digest
        assert store.get('issuer\0alice',EID).request.base_build_id==BID
        store.delete('issuer\0bob',EID)
        assert store.get('issuer\0alice',EID)
        store.delete('issuer\0alice',EID)
        with pytest.raises(WorkflowError,match='unavailable'):store.get('issuer\0alice',EID)
    finally:
        await engine.close();store.close()


def test_opt_in_and_quota_are_enforced(tmp_path):
    store=DecisionStore('owner')
    with pytest.raises(WorkflowError,match='persistence_unconfigured'):store.save('alice',decision())
    store.save('alice',decision(False))
    assert store.get('alice',EID).state=='proposed'
    with pytest.raises(WorkflowError):store.get('bob',EID)
