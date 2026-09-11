"""Unreported unlocks and ordinary/ascendancy budgets cannot be inferred."""
import time
from types import SimpleNamespace
import pytest
from poe2_companion.observations import ObservationRequest, record
from poe2_companion.progression import ProgressionRequest, plan
from poe2_companion.workflow_store import DecisionStore, WorkflowError

BID = 'bld_'+'1'*32
DIGEST = 'a'*64


class ProfileEngine:
    async def profile(self, request):
        return SimpleNamespace(snapshot_digest=DIGEST,metadata=SimpleNamespace(level=70),
            skill_instances=[],next_offset=None)


def observation(store, values):
    return record(store,'alice',ObservationRequest(base_build_id=BID,base_snapshot_digest=DIGEST,
        observed_at_epoch=int(time.time()),values=values)).observation_id


async def test_unknown_quests_and_separate_point_pools():
    store = DecisionStore('member')
    evidence = observation(store,[{'kind':'available_points','ordinary':2,'ascendancy':0}])
    request = ProgressionRequest(build_id=BID,snapshot_digest=DIGEST,observation_ids=[evidence],milestones=[
        {'character_level':71,'ordinary_points_spent':3,'ascendancy_points_spent':2,'required_unlocks':['amulet_instilling']},
        {'character_level':74,'ordinary_points_spent':3}])
    result = await plan(request,ProfileEngine(),store,'alice')
    first,second = result.milestones
    assert first.ordinary_points_available_before_step == 3 and first.ordinary_points_remaining == 0
    assert first.ascendancy_points_available_before_step == 0
    assert 'ascendancy_points_insufficient' in first.unmet_or_unknown
    assert 'unlock_unknown:amulet_instilling' in first.unmet_or_unknown
    assert second.ordinary_points_available_before_step == 3 and second.ordinary_points_remaining == 0
    assert not result.unknown_quest_rewards_assumed_complete
    assert result.reported_level is None and result.saved_level == 70


async def test_reported_revision_and_conflict_require_explicit_resolution():
    store = DecisionStore('member')
    one = observation(store,[{'kind':'character_level','level':73}])
    two = observation(store,[{'kind':'character_level','level':74}])
    request = ProgressionRequest(build_id=BID,snapshot_digest=DIGEST,observation_ids=[one],milestones=[{'character_level':75}])
    result = await plan(request,ProfileEngine(),store,'alice')
    assert result.saved_level == 70 and result.reported_level == 73
    assert not result.reported_state_confirmed_by_source
    assert 'ordinary_points_unknown' in result.milestones[0].unmet_or_unknown
    request.observation_ids.append(two)
    with pytest.raises(WorkflowError,match='conflicting_progression'):
        await plan(request,ProfileEngine(),store,'alice')
    with pytest.raises(WorkflowError,match='unavailable'):
        await plan(request,ProfileEngine(),store,'bob')
