"""Joint Ghost Dance and ES passive removal against independent native endpoints."""
import base64
import hashlib
import re
import zlib
from collections import deque
from xml.etree import ElementTree as ET
import httpx
from poe2_companion.engine import EngineClient
from poe2_companion.engine_models import ENGINE_DATA_COMMIT
from poe2_companion.engine_worker import worker_app
from poe2_companion.experiment_models import ExperimentRequest
from poe2_companion.workflow_store import DecisionStore
from poe2_companion.workflows import WorkflowService
from poe2_companion.native_recovery import NativeRecoveryRequest,bind
from poe2_companion.plan_dependencies import DependencyRequest,analyze
from test_engine_real import real_engine,FIXTURE,BID,val


async def test_joint_buffer_and_ghost_dance_loss_has_native_bound_recovery(real_engine):
    catalog=(await real_engine.inspector.document(BID,catalog=True))[0].catalog
    nodes={n.node_id:n for n in catalog.nodes}
    queue=deque([[catalog.class_start_node_id]]);seen={catalog.class_start_node_id};path=None
    while queue:
        current=queue.popleft();node=nodes[current[-1]]
        if any(re.fullmatch(r'\d+% increased maximum Energy Shield',s) for s in node.stats):path=current;break
        for key in node.linked_node_ids:
            if key not in seen and key in nodes and not nodes[key].ascendancy and not nodes[key].special_allocation_rule:
                seen.add(key);queue.append([*current,key])
    assert path and len(path)<64
    root=ET.fromstring(FIXTURE.read_bytes())
    root.find('./Tree/Spec').set('nodes',','.join(map(str,path)))
    for id,base,mods,slot in [(100,'Silk Robe','+1000 to Evasion Rating\n+500 to maximum Energy Shield','Body Armour'),
            (101,'Gold Amulet','+300 to Strength\n+300 to Dexterity\n+300 to Intelligence','Amulet')]:
        ET.SubElement(root.find('Items'),'Item',{'id':str(id)}).text=f'Rarity: RARE\nSynthetic Defence\n{base}\nImplicits: 0\n{mods}'
        itemset=root.find('./Items/ItemSet')
        row=next((s for s in itemset.findall('Slot') if s.get('name')==slot),None)
        if row is None:row=ET.SubElement(itemset,'Slot',{'name':slot})
        row.set('itemId',str(id))
    for skill in ['FireballPlayer','GhostDancePlayer']:
        group=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
        ET.SubElement(group,'Gem',{'skillId':skill,'level':'1','quality':'0','enabled':'true'})
    raw=base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    (real_engine.private_dir/(BID+'.pob')).write_bytes(raw)
    target={'skill_instance_id':'skill:s1:g1:n1','actor_ref':'player','weapon_set_id':1}
    ghost={'type':'set_gem','skill_instance_id':'skill:s1:g2:n1','native_level':1,'quality':0,'enabled':False}
    es={'type':'refund_passives','node_ids':[path[-1]]}
    requests=[ExperimentRequest(base_build_id=BID,base_snapshot_digest=hashlib.sha256(raw).hexdigest(),tree_revision='0_5',
        engine_data_commit=ENGINE_DATA_COMMIT,target=target,configuration={'ghost_shroud_lost_recently':True},edits=edits)
        for edits in [[ghost],[es],[ghost,es]]]
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://worker'))
    store=DecisionStore('m');workflow=WorkflowService(client,store)
    try:
        results=await workflow.create_variants('alice',requests)
        documents=[store.get('alice',r.experiment_id) for r in results]
        a,b,joint=[d.calculation.result for d in documents];before=documents[0].calculation.baseline
        assert all(s is not None for s in [a,b,joint])
        assert val(before,'EnergyShieldRegenRecovery')>0 and val(joint,'EnergyShieldRegenRecovery')==0
        assert val(joint,'EnergyShield')==val(b,'EnergyShield')<val(before,'EnergyShield')==val(a,'EnergyShield')
        dependency=analyze(DependencyRequest(experiment_id=results[2].experiment_id),store,'alice')
        assert {'EnergyShield','EnergyShieldRegenRecovery'}<={r.metric for r in dependency.lost_supplies}
        assert 'ghost_dance' in dependency.lost_mechanics
        inputs=dict(calculation_id=results[2].calculation_id,target=target,scenario='ritual',duration_seconds=3.,
            resources=[{'resource':'energy_shield'}],incoming_hits=[
                {'at':float(t),'resource':'energy_shield','post_mitigation_damage':200.} for t in range(3)])
        baseline=bind(NativeRecoveryRequest(**inputs,side='baseline'),before)
        candidate=bind(NativeRecoveryRequest(**inputs),joint)
        assert baseline.status==candidate.status=='scenario_integrated'
        assert baseline.recovery.cases[0].outcomes[0].recharge_active_seconds==0
        assert candidate.recovery.cases[0].outcomes[0].final<baseline.recovery.cases[0].outcomes[0].final
        assert (real_engine.private_dir/(BID+'.pob')).read_bytes()==raw
    finally:await client.close();store.close()
