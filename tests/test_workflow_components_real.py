"""Native component enumeration and actor-bound lossless receipts."""
import base64
import zlib
from xml.etree import ElementTree as ET
import httpx
from poe2_companion.engine import EngineClient, deltas
from poe2_companion.engine_worker import worker_app
from poe2_companion.skill_components import ComponentRequest,calculate
from poe2_companion.builds import tool_json_bytes
from test_engine_real import real_engine,FIXTURE,BID


async def test_native_gem_components_remain_separate_receipts(real_engine):
    root=ET.fromstring(FIXTURE.read_bytes())
    for skill in ['InfernalCryPlayer','FireballPlayer']:
        group=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
        ET.SubElement(group,'Gem',{'skillId':skill,'level':'1','quality':'0','enabled':'true'})
    raw=base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    (real_engine.private_dir/(BID+'.pob')).write_bytes(raw)
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://worker'))
    try:
        result=await calculate(ComponentRequest(build_id=BID,targets=[
            {'skill_instance_id':'skill:s1:g1:n1','actor_ref':'player','weapon_set_id':1,'aggregation':'component_breakdown'},
            {'skill_instance_id':'skill:s1:g2:n1','actor_ref':'player','weapon_set_id':1}],limit=6),client)
        assert result.total_components==3 and result.next_offset is None
        assert result.combined_rotation_dps is None and tool_json_bytes(result)<=8192
        subjects=[p.subject.evaluated for p in result.components]
        assert {s.component_ref for s in subjects}=={'InfernalCryPlayer','InfernalCryCorpseExplosionPlayer','FireballPlayer'}
        assert [p.requested_index for p in result.components]==[0,0,1]
        a,b=[client.receipts.snapshot(p.calculation_id,'baseline') for p in result.components[:2]]
        assert deltas(a,b)==[]
        assert all(p.subject.requested.aggregation=='single_skill' for p in result.components)
        assert (real_engine.private_dir/(BID+'.pob')).read_bytes()==raw
    finally:await client.close()
