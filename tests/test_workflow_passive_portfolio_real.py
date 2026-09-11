"""Native graph, complete travel costs and independent same-base alternatives."""
import base64,hashlib,zlib
from xml.etree import ElementTree as ET
import httpx
from poe2_companion.engine import EngineClient
from poe2_companion.engine_worker import worker_app
from poe2_companion.engine_models import ENGINE_DATA_COMMIT
from poe2_companion.passive_portfolio import PassivePortfolioRequest,compare
from poe2_companion.workflows import WorkflowService
from poe2_companion.workflow_store import DecisionStore
from test_engine_real import real_engine,FIXTURE,BID


async def test_native_path_portfolio_regular_and_weapon_branches_charge_every_node(real_engine):
    root=ET.fromstring(FIXTURE.read_bytes())
    group=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
    ET.SubElement(group,'Gem',{'skillId':'FireballPlayer','level':'1','quality':'0','enabled':'true'})
    raw=base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    (real_engine.private_dir/(BID+'.pob')).write_bytes(raw)
    catalog=(await real_engine.inspector.document(BID,catalog=True))[0].catalog
    nodes={n.node_id:n for n in catalog.nodes};start=nodes[catalog.class_start_node_id]
    first=next(nodes[i] for i in start.linked_node_ids if nodes[i].type=='Normal' and not nodes[i].special_allocation_rule)
    second=next(nodes[i] for i in first.linked_node_ids if i!=start.node_id and nodes[i].type=='Normal' and not nodes[i].special_allocation_rule)
    calls=0;calculate=real_engine.calculate
    async def counted(request):
        nonlocal calls
        calls+=1;return await calculate(request)
    real_engine.calculate=counted
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://pob-worker'))
    workflow=WorkflowService(client,DecisionStore('m'))
    query=PassivePortfolioRequest(template={'base_build_id':BID,'base_snapshot_digest':hashlib.sha256(raw).hexdigest(),
        'tree_revision':'0_5','engine_data_commit':ENGINE_DATA_COMMIT,'target':{'skill_instance_id':'skill:s1:g1:n1','actor_ref':'player','weapon_set_id':1},
        'ordinary_points_available':2,'weapon_set_1_points_available':2},
        alternatives=[{'target_node_ids':[second.node_id],'allocation_mode':mode} for mode in [0,1,2]],
        attribute_choices=[{'node_id':n.node_id,'attribute':'intelligence'} for n in [first,second] if n.attribute_choice_required],objective_metric='Int')
    try:
        result=await compare(query,workflow,'alice')
        ordinary,weapon,unknown=result.comparisons
        assert calls==1 and result.native_worker_invocations==1
        assert ordinary.total_new_path_nodes==weapon.total_new_path_nodes==2
        assert ordinary.ordinary_points_delta==weapon.ordinary_points_delta==2
        assert weapon.weapon_set_points_delta==2
        assert unknown.status=='weapon_point_budget_unreported' and unknown.experiment_id is None
        for row in [ordinary,weapon]:
            document=workflow.store.get('alice',row.experiment_id)
            assert document.request.edits[0].node_ids==[first.node_id,second.node_id]
            assert row.status=='valid_changeset'
            assert row.gain_per_new_path_point==row.marginal_gain/2
        assert not result.global_optimum_proven
        assert (real_engine.private_dir/(BID+'.pob')).read_bytes()==raw
    finally:await client.close()
