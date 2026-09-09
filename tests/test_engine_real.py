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
        request=EngineTradeRequest(build_id=BID,search_ids=[sid],declared_character_league='Forbidden Rites',budget={'amount':5.0,'currency':'divine'},weights=[{'stat':'Life','weight':1.0}])
        maximum=await client.recommend(request,trade,None)
        assert maximum.feasible and maximum.cost==5 and maximum.score_gain==210
        assert maximum.evaluated_combinations==5 and len(maximum.changes)==1
        minimum=await client.recommend(EngineTradeRequest(build_id=BID,search_ids=[sid],declared_character_league='Forbidden Rites',budget={'amount':5.0,'currency':'divine'},mode='minimize_cost',constraints=[{'stat':'Life','minimum':1300.0}]),trade,None)
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

async def test_real_sequential_replacement_retains_other_original_items(real_engine):
    """Old A supplies the attributes to equip B; B then enables new A."""
    root = ET.fromstring(FIXTURE.read_bytes())
    items = root.find('Items')
    # Use actual engine base requirements: new helmet 19, new boots 17.
    # Base Strength 15, old helmet +2, new helmet +3, new boots +4.
    for identifier, base, strength in ((1, 'Rusted Greathelm', 2), (2, 'Rusted Greaves', 0)):
        ET.SubElement(items, 'Item', {'id': str(identifier)}).text = (
            f'Rarity: RARE\nSynthetic Test\n{base}\nItem Level: 80\nImplicits: 0\n'
            + (f'+{strength} to Strength\n' if strength else '')
        )
    slots = {'Helmet': '1', 'Boots': '2'}
    item_set = items.find('ItemSet')
    for name, identifier in slots.items():
        slot = next((s for s in item_set.findall('Slot') if s.get('name') == name), None)
        if slot is None:
            slot = ET.SubElement(item_set, 'Slot', {'name': name})
        slot.set('itemId', identifier)
    (real_engine.private_dir / (BID + '.pob')).write_bytes(
        base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))))
    a = change('helmet', 'Soldier Greathelm', mods=['+3 to Strength'])
    b = change('boots', 'Iron Greaves', mods=['+4 to Strength'], ref='b')
    result = await real_engine.calculate(WorkerRequest(build_id=BID, scenarios=[[a, b]]))
    assert result.baseline.validation == 'pass'
    assert val(result.baseline, 'Str') == 17
    assert result.results[0].validation == 'pass'
    assert result.results[0].equip_order == ['boots', 'helmet']
    assert val(result.results[0], 'Str') == 22


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


def save_synthetic(engine, root):
    (engine.private_dir/(BID+'.pob')).write_bytes(base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))))


async def test_real_unknown_nodes_and_modern_custom_modifiers(real_engine):
    root=ET.fromstring(FIXTURE.read_bytes())
    root.find('./Tree/Spec').set('nodes','47175,2147483647')
    save_synthetic(real_engine,root)
    unknown=(await real_engine.calculate(WorkerRequest(build_id=BID))).baseline
    assert unknown.validation=='indeterminate'
    assert any(i.code=='unknown_passive' for i in unknown.issues)
    root=ET.fromstring(FIXTURE.read_bytes())
    block=root.find('./Config/ConfigSet/CustomModifierBlock')
    block.text='+100 to maximum Life'
    save_synthetic(real_engine,root)
    enabled=(await real_engine.calculate(WorkerRequest(build_id=BID))).baseline
    assert enabled.validation=='indeterminate'
    assert any(i.code=='custom_modifiers_present' for i in enabled.issues)
    block.set('enabled','false')
    save_synthetic(real_engine,root)
    disabled=(await real_engine.calculate(WorkerRequest(build_id=BID))).baseline
    assert disabled.validation=='pass'
    assert val(enabled,'Life')>val(disabled,'Life')


async def test_real_minion_metrics_and_full_dps_scope(real_engine):
    root=ET.fromstring(FIXTURE.read_bytes())
    skill=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1','includeInFullDPS':'false','label':MARKER})
    ET.SubElement(skill,'Gem',{'nameSpec':'Skeletal Arsonist','gemId':'Metadata/Items/Gems/SkillGemSkeletalArsonist',
        'skillId':'SummonSkeletalArsonistsPlayer','level':'1','quality':'0','enabled':'true'})
    save_synthetic(real_engine,root)
    result=(await real_engine.calculate(WorkerRequest(build_id=BID))).baseline
    assert result.selected_skill.actor=='minion'
    assert result.selected_skill.skill_id=='SummonSkeletalArsonistsPlayer'
    assert result.selected_skill.name=='Skeletal Arsonist Minion'
    assert val(result,'MinionCombinedDPS')>0
    assert not result.full_dps_enabled
    assert 'FullDPS' not in {s.name for s in result.stats}
    assert MARKER not in result.model_dump_json()


async def test_real_055_socketed_soul_core_and_unknown_rune(real_engine):
    body=item('Rusted Cuirass')
    body['sockets']=[{'type':'rune'}]
    body['socketedItems']=[{'baseType':'Soul Core of Jiquani','socket':0}]
    unknown={**body,'socketedItems':[{'baseType':'Unknown Rune','socket':0}]}
    vitality={**body,'corrupted':True,'socketedItems':[{'baseType':"Atziri's Soul Core of Vitality",'socket':0}]}
    incompatible={**body,'socketedItems':[{'baseType':"Atziri's Soul Core of Alacrity",'socket':0}]}
    request=WorkerRequest(build_id=BID,scenarios=[[{'slot':'body_armour','item':body}],
        [{'slot':'body_armour','item':unknown}],[{'slot':'body_armour','item':vitality}],
        [{'slot':'body_armour','item':incompatible}]])
    result=await real_engine.calculate(request)
    assert result.results[0].validation=='pass'
    # 0.5.5 is 5% maximum Life; the previous core granted only 3%.
    assert val(result.results[0],'Life')==1261  # 1146 base Life * 1.10, rounded by PoB
    assert result.results[1].validation=='indeterminate'
    assert any(i.code=='scenario_calculation_failed' for i in result.results[1].issues)
    assert result.results[2].validation=='pass'
    # One corrupted equipped item contributes 1% increased Life from this new core.
    assert val(result.results[2],'Life')==1215
    assert result.results[3].validation=='indeterminate'
    assert any(i.code=='scenario_calculation_failed' for i in result.results[3].issues)


async def test_real_vertex_equipment_requirements_do_not_erase_gem_requirements(real_engine):
    ring=change('ring_left',mods=['Equipment has no Attribute Requirements'])
    query=WorkerRequest(build_id=BID,scenarios=[[ring,change('helmet','Soldier Greathelm',ref='b')],
        [ring,change('weapon_main','Long Quarterstaff',ref='b')],
        [ring,change('helmet','Soldier Greathelm',ref='b',level=99)]])
    r=await real_engine.calculate(query)
    assert r.results[0].validation=='pass'
    assert not any(i.code=='attribute_requirement' for i in r.results[0].issues)
    assert r.results[1].validation=='pass'
    assert not any(i.code=='attribute_requirement' for i in r.results[1].issues)
    assert any(i.code=='level_requirement' for i in r.results[2].issues)
    root=ET.fromstring(FIXTURE.read_bytes())
    skill=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
    ET.SubElement(skill,'Gem',{'nameSpec':'Fireball','gemId':'Metadata/Items/Gems/SkillGemFireball',
        'skillId':'FireballPlayer','level':'20','quality':'0','enabled':'true'})
    save_synthetic(real_engine,root)
    gems=await real_engine.calculate(WorkerRequest(build_id=BID,scenarios=[[ring]]))
    assert any(i.code=='attribute_requirement' and i.stat=='Int' for i in gems.results[0].issues)


@pytest.mark.parametrize('current_es', [None, 100, 0, 50, 150])
async def test_real_forgotten_warden_deflection_uses_missing_es(real_engine, current_es):
    root=ET.fromstring(FIXTURE.read_bytes())
    if current_es is not None:
        ET.SubElement(root.find('./Config/ConfigSet'),'Input',
            {'name':'multiplierCurrentEnergyShield','number':str(current_es)})
    save_synthetic(real_engine,root)
    mods=['+200 to maximum Energy Shield', '+95 to Deflection Rating per 50 missing Energy Shield']
    scenarios=[
        [change('ring_left',mods=mods)],
        [change('ring_left',mods=mods+['100% increased Deflection Rating'])]]
    if current_es==0:
        scenarios.extend([[change('ring_left',mods=[f'+{es} to maximum Energy Shield',mods[1]])]
            for es in (49,50,99,100)])
        scenarios.append([change('ring_left',mods=mods+['Cannot have Energy Shield'])])
    result=await real_engine.calculate(WorkerRequest(build_id=BID,scenarios=scenarios))
    plain,increased=result.results[:2]
    assert plain.validation=='pass' and increased.validation=='pass'
    if current_es in (None,100,150):
        assert val(plain,'DeflectionRating')==0
    elif current_es==0:
        assert val(plain,'EnergyShield')==200
        assert val(plain,'DeflectionRating')==380
        assert [val(s,'DeflectionRating') for s in result.results[2:6]]==[0,95,95,190]
        assert result.results[6].validation=='pass'
        assert val(result.results[6],'EnergyShield')==0
        assert val(result.results[6],'DeflectionRating')==0
    else:
        assert val(plain,'DeflectionRating')==190
    assert val(increased,'DeflectionRating')==2*val(plain,'DeflectionRating')


async def test_real_chakra_unknown_rune_never_silently_disappears(real_engine):
    root=ET.fromstring(FIXTURE.read_bytes())
    # Isolate the rune-slot path without constructing an entire ascendancy.
    # This intentional override independently remains diagnosed below.
    root.find('./Config/ConfigSet/CustomModifierBlock').text='Can tattoo Runes onto your body, gaining'
    slot=ET.SubElement(root.find('./Items/ItemSet'),'RuneSlot',
        {'slotName':'Helmet Rune #1','runeName':'Unknown Synthetic Rune'})
    save_synthetic(real_engine,root)
    unknown=(await real_engine.calculate(WorkerRequest(build_id=BID))).baseline
    assert unknown.validation=='indeterminate'
    assert any(i.code=='unknown_rune' for i in unknown.issues)
    assert any(i.code=='custom_modifiers_present' for i in unknown.issues)
    slot.set('runeName','None')
    save_synthetic(real_engine,root)
    empty=(await real_engine.calculate(WorkerRequest(build_id=BID))).baseline
    assert not any(i.code=='unknown_rune' for i in empty.issues)


async def test_real_explicit_configuration_reapplies_to_comparison_and_preserves_source(real_engine,monkeypatch):
    from poe2_companion.engine_models import CompareRequest
    import hashlib
    root=ET.fromstring(FIXTURE.read_bytes())
    group=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
    ET.SubElement(group,'Gem',{'skillId':'GhostDancePlayer','nameSpec':'Ghost Dance','level':'1','quality':'0','enabled':'true'})
    ET.SubElement(root.find('./Config/ConfigSet'),'Input',{'name':'conditionLostGhostShroudRecently','boolean':'true'})
    ET.SubElement(root,'Notes').text=MARKER
    items=root.find('./Items')
    for item_id,evasion in ((42,1000),(43,2000)):
        ET.SubElement(items,'Item',{'id':str(item_id)}).text=(
            'Rarity: RARE\nSynthetic Test\nIron Ring\nImplicits: 0\n'
            f'+{evasion} to Evasion Rating\n+500 to maximum Energy Shield')
    root.find("./Items/ItemSet/Slot[@name='Ring 1']").set('itemId','42')
    save_synthetic(real_engine,root)
    path=real_engine.private_dir/(BID+'.pob')
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    private_results=[]
    calculate=real_engine.calculate
    async def observe(request):
        result=await calculate(request)
        private_results.append(result)
        return result
    monkeypatch.setattr(real_engine,'calculate',observe)
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://worker'))
    try:
        args={'build_id':BID,'replacements':[{'slot':'ring_left','saved_item_id':43}],
            'combat_scenario':{'horizon_seconds':2,'gain_roll_model':'independent_nonrecursive_per_event','events':[]}}
        on=await client.calculate(CompareRequest(**args,configuration={'ghost_shroud_lost_recently':True}))
        off=await client.calculate(CompareRequest(**args,configuration={'ghost_shroud_lost_recently':False}))
        def metrics(row):
            mechanic=next(m for m in row.mechanics if m.mechanic=='ghost_dance')
            return {m.name:m.value for m in mechanic.metrics}
        # The public 8 KiB projection may omit mechanics; verify native values
        # at the private boundary, and verify public truncation separately.
        active,inactive=private_results
        assert metrics(active.baseline)['ghost_shroud_recent_loss_configured']==metrics(active.results[0])['ghost_shroud_recent_loss_configured']==1
        assert metrics(inactive.baseline)['ghost_shroud_recent_loss_configured']==metrics(inactive.results[0])['ghost_shroud_recent_loss_configured']==0
        assert metrics(active.results[0])['energy_shield_regeneration_per_second']>metrics(active.baseline)['energy_shield_regeneration_per_second']>0
        assert metrics(inactive.baseline)['energy_shield_regeneration_per_second']==metrics(inactive.results[0])['energy_shield_regeneration_per_second']==0
        assert on.scope==off.scope=='explicit_configuration_active_weapon_set'
        for calc in (on,off):
            assert len(calc.model_dump_json().encode())<=8192
            assert MARKER not in calc.model_dump_json()
            for row in (calc.baseline,calc.result):
                assert row.combat_scenario_status=='calculated'
                if row.combat_scenario is None:
                    assert row.combat_scenario_truncated
                else:
                    assert row.combat_scenario.snapshot_dps_unchanged
        for result in private_results:
            for row in (result.baseline,*result.results):
                assert row.combat_scenario.status=='calculated'
                assert row.combat_scenario.snapshot_dps_unchanged
        assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    finally:
        await client.close()
