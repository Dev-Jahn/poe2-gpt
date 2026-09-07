"""Real LuaJIT integration, enabled by POE2_TEST_ENGINE_DIR. Synthetic data only."""
import base64
import os
import zlib
import time
from pathlib import Path
from xml.etree import ElementTree as ET
import httpx
import pytest
from poe2_companion.engine_worker import PrivateEngine, worker_app
from poe2_companion.engine_protocol import WorkerRequest
from poe2_companion.engine_models import EngineRequest, EngineTradeRequest
from poe2_companion.engine import EngineClient
from poe2_companion.trade import TradeClient, parse_listing, TradeSearchRequest

FIXTURE=Path(__file__).parent/'fixtures/engine_synthetic.xml'
BID='bld_'+'1'*32
MARKER='PRIVATE_POB_CONTEXT_SENTINEL_'*20

def item(base='Iron Ring',mods=None,ref='a',level=1):
    return {'id':ref*64,'name':'Synthetic Test','typeLine':base,'baseType':base,'frameType':2,'ilvl':80,'identified':True,
            'requirements':[{'name':'Level','values':[[str(level),0]]}], 'explicitMods':mods or []}

def change(slot,base='Iron Ring',mods=None,ref='a',level=1):
    return {'slot':slot,'item':item(base,mods,ref,level)}

@pytest.fixture
def real_engine(tmp_path):
    source=os.environ.get('POE2_TEST_ENGINE_DIR')
    if not source:
        pytest.skip('Set POE2_TEST_ENGINE_DIR to run real PoE2 LuaJIT integration')
    root=ET.fromstring(FIXTURE.read_bytes());ET.SubElement(root,'Notes').text=MARKER
    raw=base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    (tmp_path/(BID+'.pob')).write_bytes(raw)
    engine=PrivateEngine(tmp_path,Path(source),os.environ.get('POE2_TEST_LUAJIT','luajit'))
    return engine

def val(snapshot,stat):
    return next(s.value for s in snapshot.stats if s.name==stat)

async def test_real_calculation_slots_attributes_order_unknown_and_levels(real_engine):
    engine=real_engine
    import hashlib
    original_digest=hashlib.sha256((engine.private_dir/(BID+'.pob')).read_bytes()).hexdigest()
    cases=[
        [change('ring_left',mods=['+100 to maximum Life'])],
        [change('helmet','Soldier Greathelm',['+50 to maximum Life'])],
        [change('helmet','Soldier Greathelm',['+50 to Strength'])],
        [change('helmet','Soldier Greathelm',['+50 to maximum Life']),change('ring_left',mods=['+10 to Strength'],ref='b')],
        [change('helmet','Iron Ring',['+100 to maximum Life'])],
        [change('ring_left',mods=['+100 to maximum Life'],level=99)],
        [change('ring_left',mods=['This is deliberately not a PoE modifier'])],
        [change('weapon_main','Wooden Club',['100% increased Physical Damage'])],
        [change('weapon_main','Wrapped Quarterstaff',[]),change('weapon_off','Splintered Tower Shield',[],ref='b')],
        [change('ring_left','Not A Real Base',['+100 to maximum Life'])],
    ]
    result=await engine.calculate(WorkerRequest(build_id=BID,scenarios=cases))
    assert result.baseline.validation=='pass'
    good,lacking,self_supported,ordered,wrong_slot,level,unknown,weapon,twohand,badbase=result.results
    assert good.validation=='pass' and val(good,'Life')-val(result.baseline,'Life')==105
    assert good.equipped[0].origin=='trade_candidate' and good.equipped[0].saved_item_id is None
    assert lacking.validation=='fail' and any(i.stat=='Str' and i.required==19 and i.available==15 for i in lacking.issues)
    assert self_supported.validation=='indeterminate' and any(i.code=='equip_sequence_unverified' for i in self_supported.issues)
    assert ordered.validation=='pass' and ordered.equip_order==['ring_left','helmet']
    assert wrong_slot.validation=='fail' and any(i.code=='slot_incompatible' for i in wrong_slot.issues)
    assert level.validation=='fail' and any(i.code=='level_requirement' for i in level.issues)
    assert unknown.validation=='indeterminate' and any(i.code=='unparsed_modifier' for i in unknown.issues)
    assert weapon.validation=='pass' and val(weapon,'CombinedDPS')>val(result.baseline,'CombinedDPS')
    assert twohand.validation=='fail' and any(i.code=='slot_incompatible' and i.slot=='weapon_off' for i in twohand.issues)
    assert badbase.validation=='indeterminate' and not badbase.stats
    encoded=result.model_dump_json()
    assert MARKER not in encoded and 'explicitMods' not in encoded
    assert hashlib.sha256((engine.private_dir/(BID+'.pob')).read_bytes()).hexdigest()==original_digest

async def test_real_trade_budget_optimizer_and_private_http_boundary(real_engine):
    engine=real_engine
    http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(engine)),base_url='http://pob-worker')
    client=EngineClient('/unused',http=http)
    trade=TradeClient(user_agent='synthetic-integration-test')
    sid='ts_'+'2'*32
    rows={};raw_items={}
    for ref,life,cost in [('a',100,2),('b',200,5)]:
        private=item(mods=[f'+{life} to maximum Life'],ref=ref)
        listing={'id':ref*64,'item':private,'listing':{'price':{'amount':cost,'currency':'divine'}}}
        rows[ref*64]=parse_listing(listing,int(time.time()));raw_items[ref*64]=private
    trade.searches[sid]={'request':TradeSearchRequest(category='accessory.ring'), 'created':int(time.time()),'ids':list(rows), 'rows':rows,'engine_items':raw_items}
    try:
        assert (await client.status()).reachable
        assert (await client.calculate(EngineRequest(build_id=BID))).character_recalculated
        request=EngineTradeRequest(build_id=BID,search_ids=[sid],budget={'amount':5.0,'currency':'divine'},weights=[{'stat':'Life','weight':1.0}])
        maximum=await client.recommend(request,trade,None)
        assert maximum.feasible and maximum.cost==5 and maximum.score_gain==210
        assert maximum.evaluated_combinations==5 and len(maximum.changes)==1
        minimum=await client.recommend(EngineTradeRequest(build_id=BID,search_ids=[sid],budget={'amount':5.0,'currency':'divine'},mode='minimize_cost',constraints=[{'stat':'Life','minimum':1300.0}]),trade,None)
        assert minimum.feasible and minimum.cost==2
        assert len(maximum.model_dump_json().encode())<=8192
    finally:
        await client.close();await trade.close()

async def test_real_removing_strength_item_invalidates_unchanged_helmet(real_engine):
    engine=real_engine
    fixture=FIXTURE.with_name('engine_cascade_synthetic.xml')
    (engine.private_dir/(BID+'.pob')).write_bytes(base64.urlsafe_b64encode(zlib.compress(fixture.read_bytes())))
    query=WorkerRequest(build_id=BID,scenarios=[[change('ring_left',mods=['+100 to maximum Life'])],[{'slot':'ring_right','saved_item_id':1}]])
    result=await engine.calculate(query)
    assert result.baseline.validation=='pass'
    assert result.results[1].validation=='fail' and any(i.code=='duplicate_physical_item' for i in result.results[1].issues)
    assert result.results[0].validation=='fail'
    assert any(i.slot=='helmet' and i.stat=='Str' and i.required==19 and i.available==15 for i in result.results[0].issues)

async def test_real_gem_and_class_requirements(real_engine):
    engine=real_engine
    root=ET.fromstring(FIXTURE.read_bytes())
    skillset=root.find('./Skills/SkillSet')
    skill=ET.SubElement(skillset,'Skill',{'enabled':'true','mainActiveSkill':'1','slot':'Weapon 1'})
    ET.SubElement(skill,'Gem',{'nameSpec':'Fireball','gemId':'Metadata/Items/Gems/SkillGemFireball','skillId':'FireballPlayer','level':'20','quality':'0','enabled':'true'})
    # Character level 1 and a level-20 gem must not silently pass requirements.
    root.find('Build').set('level','1')
    (engine.private_dir/(BID+'.pob')).write_bytes(base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))))
    r=await engine.calculate(WorkerRequest(build_id=BID))
    assert r.baseline.validation=='fail'
    assert any(i.code in {'gem_level_requirement','attribute_requirement'} for i in r.baseline.issues)
    # Restore level-90 baseline and exercise class restriction via official importer.
    (engine.private_dir/(BID+'.pob')).write_bytes(base64.urlsafe_b64encode(zlib.compress(FIXTURE.read_bytes())))
    candidate=item(mods=['+100 to maximum Life'])
    candidate['requirements'].append({'name':'Class:','values':[['Witch',0]]})
    r=await engine.calculate(WorkerRequest(build_id=BID,scenarios=[[{'slot':'ring_left','item':candidate}]]))
    assert r.results[0].validation=='fail'
    assert any(i.code=='class_requirement' for i in r.results[0].issues)

async def test_real_unix_socket_worker_through_mcp(real_engine):
    import asyncio,sys,tempfile
    import socket as socket_module
    try:
        probe=socket_module.socket(socket_module.AF_UNIX,socket_module.SOCK_STREAM)
        probe.close()
    except PermissionError:
        pytest.skip('This execution environment blocks AF_UNIX; verify socket deployment on homelab')
    from mcp.shared.memory import create_connected_server_and_client_session
    from poe2_companion.scout import Scout
    from poe2_companion.server import build_server
    from test_scout import Backend
    engine=real_engine
    with tempfile.TemporaryDirectory(prefix='pob-ipc-') as td:
        socket=str(Path(td)/'worker.sock')
        env={**os.environ,'POE2_PRIVATE_DIR':str(engine.private_dir),'POE2_ENGINE_DIR':str(engine.engine_dir),'POE2_ENGINE_SOCKET':socket,'POE2_LUAJIT':engine.luajit}
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','poe2_companion.engine_worker',env=env,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        client=EngineClient(socket)
        scout=Scout(user_agent='test',transport=httpx.MockTransport(Backend()),interval=0)
        try:
            for _ in range(100):
                if (await client.status()).reachable:break
                await asyncio.sleep(.05)
            else:pytest.fail('private_worker_did_not_start')
            server=build_server(scout,engine=client)
            async with create_connected_server_and_client_session(server) as session:
                result=await session.call_tool('recalculate_build',{'request':{'build_id':BID}})
                assert not result.isError and result.structuredContent['character_recalculated']
                assert result.structuredContent['baseline']['validation']=='pass'
                assert len(json_dump(result.structuredContent).encode())<=8192
                assert MARKER not in result.model_dump_json()
                bad=await session.call_tool('recalculate_build',{'request':{'build_id':BID,'pob_code':MARKER}})
                assert bad.isError and MARKER not in bad.model_dump_json()
        finally:
            await client.close();await scout.close()
            if process.returncode is None:process.terminate()
            await asyncio.wait_for(process.wait(),5)

def json_dump(value):
    import json
    return json.dumps(value)

async def test_real_engine_through_mcp_sdk_without_socket(real_engine):
    from mcp.shared.memory import create_connected_server_and_client_session
    from poe2_companion.scout import Scout
    from poe2_companion.server import build_server
    from test_scout import Backend
    engine=real_engine
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(engine)),base_url='http://pob-worker'))
    scout=Scout(user_agent='test',transport=httpx.MockTransport(Backend()),interval=0)
    try:
        async with create_connected_server_and_client_session(build_server(scout,engine=client)) as session:
            result=await session.call_tool('recalculate_build',{'request':{'build_id':BID}})
            assert not result.isError and result.structuredContent['character_recalculated']
            assert result.structuredContent['baseline']['validation']=='pass'
            assert MARKER not in result.model_dump_json()
            assert len(json_dump(result.structuredContent).encode())<=8192
    finally:
        await client.close();await scout.close()
