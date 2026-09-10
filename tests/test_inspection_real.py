import base64
import zlib
from xml.etree import ElementTree as ET

from poe2_companion.engine_protocol import WorkerRequest
from poe2_companion.inspection import InspectionRequest
from test_engine_real import real_engine, FIXTURE, BID, MARKER


async def test_interpreted_saved_equipment_skills_and_config(real_engine):
    root = ET.fromstring(FIXTURE.read_bytes())
    # A saved immunity estimate must not block native equipment inspection.
    saved_hit = root.find('./Build/PlayerStat[@stat="ChaosMaximumHitTaken"]')
    if saved_hit is None:
        saved_hit = ET.SubElement(root.find('Build'), 'PlayerStat', {'stat':'ChaosMaximumHitTaken'})
    saved_hit.set('value', 'inf')
    ET.SubElement(root, 'Notes').text = MARKER
    items = root.find('Items')
    for identifier, mod in ((1, '+30% to Cold Resistance'), (2, '+100 to maximum Life')):
        ET.SubElement(items, 'Item', {'id': str(identifier)}).text = (
            f'Rarity: RARE\nSynthetic Item\nSapphire Ring\nItem Level: 80\nImplicits: 0\n{mod}')
    for slot in items.find('ItemSet').findall('Slot'):
        if slot.get('name') == 'Ring 1':
            slot.set('itemId', '1')
    group = ET.SubElement(root.find('./Skills/SkillSet'), 'Skill', {'enabled': 'true', 'mainActiveSkill': '1'})
    ET.SubElement(group, 'Gem', {'skillId': 'MeleeAtAnimationSpeed', 'level': '1', 'quality': '0', 'enabled': 'true'})
    ET.SubElement(root.find('./Config/ConfigSet'), 'Input', {'name': 'enemyLevel', 'number': '80'})
    second=ET.SubElement(root.find('Config'),'ConfigSet',{'id':'2'})
    ET.SubElement(second,'Input',{'name':'enemyLevel','number':'70'})
    (real_engine.private_dir / (BID + '.pob')).write_bytes(base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))))
    async def get(section, **kwargs):
        result = await real_engine.calculate(WorkerRequest(build_id=BID,
            configuration=kwargs.get('configuration'),
            inspection=InspectionRequest(build_id=BID, section=section, **kwargs)))
        assert MARKER not in result.model_dump_json()
        return result.inspection
    page = await get('equipment')
    assert {r.saved_item_id for r in page.records} == {1, 2}
    assert next(r for r in page.records if r.saved_item_id == 1).placements
    assert not next(r for r in page.records if r.saved_item_id == 2).placements
    detail = await get('equipment', saved_item_id=2)
    assert any(r.kind == 'modifier' and r.text == '+100 to maximum Life' for r in detail.records)
    assert any('Life' in r.canonical_ids for r in detail.records)
    skills = await get('skills')
    assert any(r.kind == 'gem' and r.canonical_id == 'MeleeAtAnimationSpeed' for r in skills.records)
    assert any(r.kind == 'skill_group' and r.selected for r in skills.records)
    config = await get('configuration', configuration_key='enemyLevel')
    found = next((r for r in config.records if r.canonical_id == 'enemyLevel'), None)
    assert found and found.saved_value == 80 and found.effective_source == 'saved'
    sets=await get('sets')
    assert {r.set_id for r in sets.records if r.kind=='configuration_set'}=={1,2}
    alternate=await get('configuration',set_id=2,configuration_key='enemyLevel')
    assert alternate.records[0].effective_value==70 and alternate.records[0].set_id==2
    false_override=await get('configuration',configuration_key='enemy_maimed',configuration={'enemy_maimed':False})
    assert false_override.records[0].effective_value is False
    assert false_override.records[0].override_value is False and false_override.records[0].effective_source=='override'
    # Exercise the exact MCP host contract, including union-free structured output.
    import httpx
    from jsonschema import Draft202012Validator
    from mcp.shared.memory import create_connected_server_and_client_session
    from poe2_companion.engine import EngineClient
    from poe2_companion.engine_worker import worker_app
    from poe2_companion.builds import BuildReader
    from poe2_companion.server import build_server
    from poe2_companion.scout import Scout
    from test_scout import Backend
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://pob-worker'))
    scout=Scout(user_agent='test',transport=httpx.MockTransport(Backend()),interval=0)
    server=build_server(scout,engine=client,build_reader=BuildReader(real_engine.private_dir/'unused-projections'))
    try:
        async with create_connected_server_and_client_session(server) as session:
            tool=next(t for t in (await session.list_tools()).tools if t.name=='get_build_equipment')
            result=await session.call_tool('get_build_equipment',{'build_id':BID,'slot':'ring_left'})
            assert not result.isError, result
            assert result.structuredContent['records'][0]['base_type']=='Sapphire Ring'
            assert len(result.model_dump_json().encode())<16384  # MCP includes text plus structured data.
            Draft202012Validator(tool.outputSchema).validate(result.structuredContent)
            schemas={t.name:t.outputSchema for t in (await session.list_tools()).tools}
            for name,args in [
                ('get_build_equipment',{'build_id':BID,'slot':'ring_right'}),
                ('get_build_equipment',{'build_id':BID,'slot':'ring_left','offset':999}),
                ('get_build_equipment',{'build_id':BID,'saved_item_id':999}),
                ('inspect_build',{'request':{'build_id':BID,'section':'configuration','configuration_key':'not_a_config_key'}}),
                ('inspect_build',{'request':{'build_id':BID,'section':'equipment','saved_item_id':999}}),
            ]:
                empty=await session.call_tool(name,args)
                assert not empty.isError, empty
                assert empty.structuredContent['records']==[]
                Draft202012Validator(schemas[name]).validate(empty.structuredContent)
            report=await session.call_tool('validate_build_equipment',{'request':{'build_id':BID}})
            assert not report.isError and report.structuredContent['calculation_id']
            assert 'stats' not in report.structuredContent
    finally:
        await client.close();await scout.close()
