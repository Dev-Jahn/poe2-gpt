"""Handoff 002/003: native parse isolation, cache and stable skill identity."""
import base64
import hashlib
import zlib
from xml.etree import ElementTree as ET

from poe2_companion.inspection import InspectionRequest
from poe2_companion.profiles import ProfileRequest
from test_engine_real import real_engine, FIXTURE, BID, MARKER


async def test_static_load_busy_worker_unknown_modifier_and_hot_pages(real_engine):
    root=ET.fromstring(FIXTURE.read_bytes())
    ET.SubElement(root,'Notes').text=MARKER
    ET.SubElement(root.find('Items'),'Item',{'id':'1'}).text=(
        'Rarity: RARE\nSynthetic\nSapphire Ring\nItem Level: 80\nImplicits: 0\n'
        'This deliberately unsupported modifier has no calculation implementation')
    skill_set=root.find('./Skills/SkillSet')
    for _ in range(2):
        group=ET.SubElement(skill_set,'Skill',{'enabled':'true','mainActiveSkill':'1'})
        ET.SubElement(group,'Gem',{'skillId':'MeleeAtAnimationSpeed','level':'1','quality':'0','enabled':'true'})
    raw=base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    (real_engine.private_dir/(BID+'.pob')).write_bytes(raw)
    async with real_engine.lock:
        page=await real_engine.inspector.inspect(InspectionRequest(build_id=BID,section='equipment',saved_item_id=1))
        assert any(r.status=='unparsed' for r in page.records)
        assert MARKER not in page.model_dump_json()
        count=real_engine.inspector.process_runs
        async with real_engine.inspector.lock:
            for offset in range(10):
                paged=await real_engine.inspector.inspect(InspectionRequest(build_id=BID,section='equipment',saved_item_id=1,offset=offset,limit=1))
                assert paged.records==page.records[offset:offset+1]
        assert real_engine.inspector.process_runs==count
        profile=await real_engine.inspector.profile(ProfileRequest(build_id=BID,changed_since_build_id=BID))
    assert profile.snapshot_digest==hashlib.sha256(raw).hexdigest()
    assert profile.changed_since=='same_content'
    assert profile.calculated_metrics_available is False
    assert len(profile.skill_instances)==2
    assert len({s.skill_instance_id for s in profile.skill_instances})==2
    assert all(s.quality==0 and s.support is False for s in profile.skill_instances)
    assert MARKER not in profile.model_dump_json()


async def test_static_native_contract_empty_configuration_and_false(real_engine):
    query=InspectionRequest(build_id=BID,section='configuration',configuration_key='enemy_maimed',
        configuration={'enemy_maimed':False})
    page=await real_engine.inspector.inspect(query)
    assert page.records[0].effective_value is False
    assert page.records[0].override_value is False
    empty=await real_engine.inspector.inspect(InspectionRequest(build_id=BID,section='equipment',saved_item_id=999))
    assert empty.model_dump(mode='json')['records']==[]
