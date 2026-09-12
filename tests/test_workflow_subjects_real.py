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
    combat={'horizon_seconds':2,'gain_roll_model':'independent_nonrecursive_per_event','events':[]}
    valid=await real_engine.calculate(WorkerRequest(build_id=BID,target=target,combat_scenario=combat))
    assert valid.baseline.combat_scenario_status=='calculated'
    missing=await real_engine.calculate(WorkerRequest(build_id=BID,target={**target,'skill_instance_id':'skill:s1:g9:n1'},combat_scenario=combat,scenarios=[[]]))
    assert missing.baseline.subject.status=='unavailable'
    assert missing.baseline.subject.reason=='instance_not_found'
    assert missing.baseline.stats==[]
    for row in [missing.baseline,*missing.results]:
        assert row.combat_scenario is None and row.combat_scenario_status is None
        assert row.selected_skill is None and row.mechanics==[]
    assert deltas(result.baseline,missing.baseline)==[]
    other=await real_engine.calculate(WorkerRequest(build_id=BID,target={**target,'skill_instance_id':'skill:s1:g3:n1'}))
    assert other.baseline.subject.evaluated.skill_instance_id=='skill:s1:g3:n1'
    assert deltas(result.baseline,other.baseline)==[]


async def test_hollow_copy_has_its_own_actor_identity(real_engine):
    from test_martial_mechanics_real import synthetic
    root=ET.fromstring(synthetic('MetaHollowFormPlayer',clone='StormWavePlayer'))
    ET.SubElement(root.find('Items'),'Item',{'id':'100'}).text = (
        'Rarity: RARE\nSynthetic Staff\nWrapped Quarterstaff\nImplicits: 0\nAdds 50 to 50 Physical Damage\n')
    itemset=root.find('./Items/ItemSet')
    weapon=next((s for s in itemset.findall('Slot') if s.get('name')=='Weapon 1'),None)
    if weapon is None: weapon=ET.SubElement(itemset,'Slot',{'name':'Weapon 1'})
    weapon.set('itemId','100')
    raw=base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    (real_engine.private_dir/(BID+'.pob')).write_bytes(raw)
    target={'skill_instance_id':'skill:s1:g2:n2','actor_ref':'hollow_image','weapon_set_id':1}
    copied=await real_engine.calculate(WorkerRequest(build_id=BID,target=target))
    assert copied.baseline.subject.status=='matched'
    assert copied.baseline.subject.evaluated.actor_ref=='hollow_image'
    assert copied.baseline.selected_skill.actor=='hollow_image'
    wrong=await real_engine.calculate(WorkerRequest(build_id=BID,target={**target,'actor_ref':'player'}))
    assert wrong.baseline.subject.status=='unavailable' and wrong.baseline.subject.reason=='actor_mismatch'
    assert wrong.baseline.stats==[] and deltas(copied.baseline,wrong.baseline)==[]


async def test_vessel_copy_binds_original_instance_and_explicit_owner(real_engine):
    from test_spirit_vessel_real import synthetic,vessel,gem
    root=synthetic()
    group=vessel(root,level=20)
    gem(group,'Furious Slam','FuriousSlamPlayer')
    gem(group,'Oil Barrage','OilBarragePlayer')
    def save():
        (real_engine.private_dir/(BID+'.pob')).write_bytes(base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))))
    save()
    target={'skill_instance_id':'skill:s1:g2:n2','actor_ref':'spirit_vessel','actor_owner_instance_id':'skill:s1:g2:n1','weapon_set_id':1}
    first=(await real_engine.calculate(WorkerRequest(build_id=BID,target=target))).baseline
    assert first.subject.status=='matched'
    assert first.subject.evaluated.skill_id=='FuriousSlamPlayer'
    assert first.subject.evaluated.skill_instance_id=='skill:s1:g2:n2'
    assert first.subject.evaluated.actor_owner_instance_id=='skill:s1:g2:n1'
    assert first.selected_skill.actor=='spirit_vessel' and first.selected_skill.skill_id=='FuriousSlamPlayer'
    assert next(s.value for s in first.stats if s.name=='MinionCombinedDPS')>0
    assert not {'CombinedDPS','ManaLeechRate','Speed'} & {s.name for s in first.stats}
    other=(await real_engine.calculate(WorkerRequest(build_id=BID,target={**target,'skill_instance_id':'skill:s1:g2:n3'}))).baseline
    assert other.subject.status=='matched' and other.subject.evaluated.skill_id=='OilBarragePlayer'
    assert deltas(first,other)==[]
    gem(group,'Furious Slam','FuriousSlamPlayer')
    save()
    duplicate=(await real_engine.calculate(WorkerRequest(build_id=BID,target=target))).baseline
    assert duplicate.subject.status=='unavailable' and duplicate.subject.reason=='ambiguous_component'
    assert duplicate.stats==[]
