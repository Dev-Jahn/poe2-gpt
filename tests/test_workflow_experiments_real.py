"""Handoff 004: whole-plan native calculation and immutable atomic rejection."""
import base64
import hashlib
import zlib
from xml.etree import ElementTree as ET
from poe2_companion.engine_protocol import WorkerRequest
from poe2_companion.experiment_models import ExperimentRequest
from poe2_companion.engine_models import ENGINE_DATA_COMMIT
from test_engine_real import real_engine, FIXTURE, BID, val


async def test_joint_native_edit_and_independent_clones(real_engine):
    root=ET.fromstring(FIXTURE.read_bytes())
    group=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
    ET.SubElement(group,'Gem',{'skillId':'FireballPlayer','level':'1','quality':'0','enabled':'true'})
    raw=base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    path=real_engine.private_dir/(BID+'.pob');path.write_bytes(raw)
    target={'skill_instance_id':'skill:s1:g1:n1','actor_ref':'player','weapon_set_id':1}
    def request(level,extra=()):
        return ExperimentRequest(base_build_id=BID,base_snapshot_digest=hashlib.sha256(raw).hexdigest(),
            tree_revision='0_5',engine_data_commit=ENGINE_DATA_COMMIT,target=target,
            edits=[{'type':'set_gem','skill_instance_id':'skill:s1:g1:n1','native_level':level,'quality':0},*extra])
    async def run(edit):
        return await real_engine.calculate(WorkerRequest(build_id=BID,target=target,experiment=edit))
    level2=await run(request(2))
    assert level2.experiment_audit.status=='valid_changeset'
    assert val(level2.results[0],'CombinedDPS')>val(level2.baseline,'CombinedDPS')
    level3=await run(request(3))
    assert val(level3.baseline,'CombinedDPS')==val(level2.baseline,'CombinedDPS')
    assert val(level3.results[0],'CombinedDPS')>val(level2.results[0],'CombinedDPS')
    invalid=await run(request(3,[{'type':'refund_passives','node_ids':[2147483647]}]))
    assert invalid.experiment_audit.status=='rejected_atomically'
    assert invalid.experiment_audit.failures[0].edit_index==1
    assert invalid.experiment_audit.applied_edits==[] and invalid.results==[]
    assert path.read_bytes()==raw
