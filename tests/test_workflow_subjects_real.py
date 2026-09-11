"""Handoff 003: never compare the saved main skill against a different target."""
import base64
import zlib
from xml.etree import ElementTree as ET
import pytest
from poe2_companion.engine_protocol import WorkerRequest
from poe2_companion.engine import deltas
from test_engine_real import real_engine, FIXTURE, BID


async def test_explicit_instance_subject_and_ineligible_candidate(real_engine):
    root=ET.fromstring(FIXTURE.read_bytes())
    skillset=root.find('./Skills/SkillSet')
    for skill in ('MeleeAtAnimationSpeed','FireballPlayer','FireballPlayer'):
        group=ET.SubElement(skillset,'Skill',{'enabled':'true','mainActiveSkill':'1'})
        ET.SubElement(group,'Gem',{'skillId':skill,'level':'1','quality':'0','enabled':'true'})
    (real_engine.private_dir/(BID+'.pob')).write_bytes(base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))))
    target={'skill_instance_id':'skill:s1:g2:n1','actor_ref':'player','weapon_set_id':1}
    result=await real_engine.calculate(WorkerRequest(build_id=BID,target=target,scenarios=[[]]))
    assert result.baseline.subject.saved.skill_id=='MeleeAtAnimationSpeed'
    assert result.baseline.subject.status=='matched'
    assert result.baseline.subject.evaluated.skill_instance_id=='skill:s1:g2:n1'
    assert result.baseline.selected_skill.skill_id=='FireballPlayer'
    assert result.results[0].subject.evaluated==result.baseline.subject.evaluated
    assert all(v.value==0 for v in deltas(result.baseline,result.results[0]))
    missing=await real_engine.calculate(WorkerRequest(build_id=BID,target={**target,'skill_instance_id':'skill:s1:g9:n1'}))
    assert missing.baseline.subject.status=='unavailable'
    assert missing.baseline.subject.reason=='instance_not_found'
    assert missing.baseline.stats==[]
    assert deltas(result.baseline,missing.baseline)==[]
    other=await real_engine.calculate(WorkerRequest(build_id=BID,target={**target,'skill_instance_id':'skill:s1:g3:n1'}))
    assert other.baseline.subject.evaluated.skill_instance_id=='skill:s1:g3:n1'
    assert deltas(result.baseline,other.baseline)==[]
