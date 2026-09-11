"""Native own-stat bootstrap counterexample and explicitly owned bridge gear."""
import base64
import hashlib
import zlib
from xml.etree import ElementTree as ET
from poe2_companion.engine_protocol import WorkerRequest
from poe2_companion.experiment_models import ExperimentRequest, OwnedHelper
from poe2_companion.engine_models import ENGINE_DATA_COMMIT
from test_engine_real import real_engine, FIXTURE, BID


async def test_owned_bridge_is_required_then_removed(real_engine):
    root = ET.fromstring(FIXTURE.read_bytes())
    for identifier,base,strength in [(10,'Soldier Greathelm',50),(11,'Iron Ring',10)]:
        ET.SubElement(root.find('Items'),'Item',{'id':str(identifier)}).text = (
            f'Rarity: RARE\nSynthetic Test\n{base}\nItem Level: 80\nImplicits: 0\n+{strength} to Strength\n')
    group = ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
    ET.SubElement(group,'Gem',{'skillId':'FireballPlayer','level':'1','quality':'0','enabled':'true'})
    raw = base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    (real_engine.private_dir/(BID+'.pob')).write_bytes(raw)
    target = {'skill_instance_id':'skill:s1:g1:n1','actor_ref':'player','weapon_set_id':1}
    request = ExperimentRequest(base_build_id=BID,base_snapshot_digest=hashlib.sha256(raw).hexdigest(),
        tree_revision='0_5',engine_data_commit=ENGINE_DATA_COMMIT,target=target,
        edits=[{'type':'equip_item','slot':'helmet','source':{'kind':'saved_item','saved_item_id':10}}])
    first = await real_engine.calculate(WorkerRequest(build_id=BID,target=target,experiment=request))
    assert first.experiment_audit.equipment_transition.status == 'no_valid_order_within_choices'
    assert first.results[0].validation != 'pass'
    request.temporary_equipment = [OwnedHelper(slot='ring_left',saved_item_id=11,availability='user_confirmed_owned')]
    request = ExperimentRequest.model_validate_json(request.model_dump_json())
    second = await real_engine.calculate(WorkerRequest(build_id=BID,target=target,experiment=request))
    transition = second.experiment_audit.equipment_transition
    assert second.experiment_audit.transition_validation == 'verified'
    assert transition.helper_purchase_cost == 0
    assert [(a.slot,a.action) for a in transition.actions] == [('ring_left','equip'),('helmet','equip'),('ring_left','unequip')]
    assert all(i.slot != 'ring_left' for i in second.results[0].equipped)
    assert not any(i.code == 'equip_sequence_unverified' for i in second.results[0].issues)
    request.transition_state_budget = 1
    bounded = await real_engine.calculate(WorkerRequest(build_id=BID,target=target,experiment=request))
    assert bounded.experiment_audit.equipment_transition.status == 'search_budget_exhausted'
    assert not bounded.experiment_audit.equipment_transition.search_exhausted
    assert (real_engine.private_dir/(BID+'.pob')).read_bytes() == raw


async def test_mixed_gem_upgrade_uses_preceding_equipment_not_final_stats(real_engine):
    root=ET.fromstring(FIXTURE.read_bytes())
    ET.SubElement(root.find('Items'),'Item',{'id':'10'}).text=(
        'Rarity: RARE\nSynthetic Bridge\nIron Ring\nItem Level: 80\nImplicits: 0\n+250 to Intelligence\n')
    group=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
    ET.SubElement(group,'Gem',{'skillId':'FireballPlayer','level':'1','quality':'0','enabled':'true'})
    raw=base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    (real_engine.private_dir/(BID+'.pob')).write_bytes(raw)
    target={'skill_instance_id':'skill:s1:g1:n1','actor_ref':'player','weapon_set_id':1}
    request=ExperimentRequest(base_build_id=BID,base_snapshot_digest=hashlib.sha256(raw).hexdigest(),
        tree_revision='0_5',engine_data_commit=ENGINE_DATA_COMMIT,target=target,edits=[
            {'type':'set_gem','skill_instance_id':target['skill_instance_id'],'native_level':20,'quality':0},
            {'type':'equip_item','slot':'ring_left','source':{'kind':'saved_item','saved_item_id':10}}])
    result=await real_engine.calculate(WorkerRequest(build_id=BID,target=target,experiment=request))
    transition=result.experiment_audit.equipment_transition
    assert transition.status=='verified'
    assert [(a.action,a.edit_index) for a in transition.actions]==[('equip',1),('apply_edit',0)]
    assert result.results[0].subject.status=='matched'
    assert all(s.satisfied for s in result.results[0].requirements.sources)
    request.transition_state_budget=1
    limited=await real_engine.calculate(WorkerRequest(build_id=BID,target=target,experiment=request))
    assert limited.experiment_audit.equipment_transition.status=='search_budget_exhausted'
    assert (real_engine.private_dir/(BID+'.pob')).read_bytes()==raw
