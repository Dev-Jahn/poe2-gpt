"""One worker, isolated support alternatives, native differential and provenance."""
import base64
import hashlib
import zlib
from xml.etree import ElementTree as ET
import httpx
from poe2_companion.engine import EngineClient
from poe2_companion.engine_worker import worker_app
from poe2_companion.engine_models import ENGINE_DATA_COMMIT
from poe2_companion.support_portfolio import SupportPortfolioRequest, compare
from poe2_companion.workflows import WorkflowService
from poe2_companion.workflow_store import DecisionStore
from test_engine_real import real_engine, FIXTURE, BID


async def test_support_alternatives_share_worker_but_not_mutations(real_engine):
    root = ET.fromstring(FIXTURE.read_bytes())
    group = ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
    ET.SubElement(group,'Gem',{'skillId':'FireballPlayer','level':'1','quality':'0','enabled':'true'})
    raw = base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    (real_engine.private_dir/(BID+'.pob')).write_bytes(raw)
    calls = 0
    calculate = real_engine.calculate
    async def counted(request):
        nonlocal calls
        calls += 1
        return await calculate(request)
    real_engine.calculate = counted
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://pob-worker')
    client = EngineClient('/unused',http=http)
    workflow = WorkflowService(client,DecisionStore('member'))
    request = SupportPortfolioRequest(base_build_id=BID,base_snapshot_digest=hashlib.sha256(raw).hexdigest(),
        tree_revision='0_5',engine_data_commit=ENGINE_DATA_COMMIT,
        target={'skill_instance_id':'skill:s1:g1:n1','actor_ref':'player','weapon_set_id':1},observed_socket_capacity=0,
        alternatives=[{'support_gem_ids':[],'proposed_socket_capacity':0},
            {'support_gem_ids':['Metadata/Items/Gems/SkillGemControlledDestructionSupport'],'proposed_socket_capacity':1}])
    try:
        result = await compare(request,workflow,'alice')
        assert calls == 1 and result.worker_invocations == 1
        assert len(result.comparisons) == 2
        empty,supported = result.comparisons
        assert empty.additional_sockets_required == 0 and supported.additional_sockets_required == 1
        assert supported.total_purchase_cost is None and not supported.socket_upgrade_cost_known
        dps = lambda row: next(s.value for s in row.metrics if s.name == 'CombinedDPS')
        assert dps(supported) > dps(empty)
        assert next(s.value for s in supported.marginal_metrics if s.name == 'CombinedDPS') == dps(supported)-dps(empty)
        assert supported.supports[0].name == 'Controlled Destruction'
        a,b = [workflow.store.get('alice',i) for i in result.experiment_ids]
        assert a.calculation.baseline.stats == b.calculation.baseline.stats
        assert b.request.edits[0].socket_capacity_evidence == 'planned_upgrade'
        assert b.request.edits[0].original_observed_socket_capacity == 0
        assert a.request.edits[0].support_gem_ids == []
        assert (real_engine.private_dir/(BID+'.pob')).read_bytes() == raw
    finally:
        await client.close()


async def test_isolated_support_is_scenario_specific_and_new_gem_does_not_inherit_sockets(real_engine):
    import pytest,time
    from poe2_companion.profiles import ProfileRequest
    from poe2_companion.progression import ProgressionRequest,plan
    from poe2_companion.observations import ObservationRequest,record
    root=ET.fromstring(FIXTURE.read_bytes())
    group=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
    ET.SubElement(group,'Gem',{'skillId':'FireballPlayer','level':'1','quality':'0','enabled':'true'})
    raw=base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)));(real_engine.private_dir/(BID+'.pob')).write_bytes(raw)
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://pob-worker'))
    store=DecisionStore('m');workflow=WorkflowService(client,store)
    try:
        profile=await client.profile(ProfileRequest(build_id=BID))
        skill=next(s for s in profile.skill_instances if s.skill_id=='FireballPlayer')
        observed=record(store,'alice',ObservationRequest(base_build_id=BID,base_snapshot_digest=profile.snapshot_digest,
            observed_at_epoch=int(time.time()),values=[{'kind':'gem_state','skill_instance_id':skill.skill_instance_id,'native_level':1,'socket_capacity':5}]))
        milestones=await plan(ProgressionRequest(build_id=BID,snapshot_digest=profile.snapshot_digest,observation_ids=[observed.observation_id],
            milestones=[{'character_level':90,'gem_goals':[{'skill_instance_id':skill.skill_instance_id,'gem_catalog_id':skill.gem_catalog_id,
                'native_level':10,'support_socket_capacity':5,'acquisition':'level_existing_gem'}]},
                {'character_level':91,'gem_goals':[{'skill_instance_id':skill.skill_instance_id,'gem_catalog_id':skill.gem_catalog_id,
                'native_level':10,'support_socket_capacity':5,'acquisition':'replace_with_purchased_gem'}]}]),client,store,'alice')
        existing,replacement=[m.gems[0] for m in milestones.milestones]
        assert existing.socket_capacity_evidence=='user_reported_sufficient' and replacement.socket_capacity_evidence=='unknown'
        assert replacement.native_level==existing.native_level==10 and not replacement.effective_level_used_for_requirements
        assert existing.character_level_required==replacement.character_level_required
        values=[]
        for isolated in [False,True]:
            result=await compare(SupportPortfolioRequest(base_build_id=BID,base_snapshot_digest=profile.snapshot_digest,
                tree_revision=profile.metadata.tree_version,engine_data_commit=profile.engine_data_commit,
                target={'skill_instance_id':skill.skill_instance_id,'actor_ref':'player','weapon_set_id':1},
                observed_socket_capacity=1,configuration={'enemy_isolated':isolated},alternatives=[
                    {'support_gem_ids':['Metadata/Items/Gems/SkillGemVoranasSiegeSupport'],'proposed_socket_capacity':1}]),workflow,'alice')
            snapshot=store.get('alice',result.experiment_ids[0]).calculation.result
            assert snapshot.subject.status=='matched'
            values.append(next(s.value for s in snapshot.stats if s.name=='AverageDamage'))
            assert result.configuration_fields==['enemy_isolated'] and not result.conditional_effect_uptime_proven
        # Independent pinned rule: 20% MORE Hit Damage only against an isolated enemy.
        assert values[1]==pytest.approx(values[0]*1.2,rel=1e-5)
        assert (real_engine.private_dir/(BID+'.pob')).read_bytes()==raw
    finally:await client.close();store.close()
