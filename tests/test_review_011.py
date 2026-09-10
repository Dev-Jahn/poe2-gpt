"""Protocol and recommendation regressions from the 0.11 review."""
import json
import time
from decimal import Decimal

import httpx
import pytest
from jsonschema import Draft202012Validator
from mcp.shared.memory import create_connected_server_and_client_session

from poe2_companion.builds import BuildReader
from poe2_companion.diagnostics import DiagnosticRequest
from poe2_companion.engine import EngineClient
from poe2_companion.engine_models import EngineError, EngineSnapshot, EngineTradeRequest, TradeChange
from poe2_companion.engine_protocol import WorkerChange, WorkerResult
from poe2_companion.inspection import InspectionPage
from poe2_companion.recommendation import Option, enumerate_plans
from poe2_companion.scout import Scout
from poe2_companion.server import build_server
from poe2_companion.trade import TradeClient, TradeSearchRequest, parse_listing
from test_engine_real import BID, item
from test_scout import Backend
from test_trade import TradeBackend


def snapshot(life=100, equipped=()):
    return EngineSnapshot(stats=[{'name':'Life','value':life}],equipped=list(equipped),
        issues=[],issue_count=0,validation='pass',equipment_validity='pass',
        active_weapon_set=1,main_skill_group=0)


@pytest.mark.parametrize('status',[None,'online','available','any'])
async def test_instant_buyout_is_default_and_override_is_preserved(status):
    backend=TradeBackend()
    client=TradeClient('test',transport=httpx.MockTransport(backend),interval=0)
    request=TradeSearchRequest(category='accessory.ring',**({'status':status} if status else {}))
    try:
        result=await client.search(request)
        sent=next(json.loads(r.content) for r in backend.requests if r.method=='POST')
        assert sent['query']['status']['option']==(status or 'securable')
        assert result.instant_buyout_only is (status is None)
        assert result.status_filter==(status or 'securable')
        assert result.travel_link_supported is False
        assert result.website_url.startswith('https://www.pathofexile.com/trade2/search/')
    finally:
        await client.close()


async def test_empty_inspection_over_actual_mcp_session_and_one_worker_per_page(tmp_path):
    calls=[]
    def respond(request):
        query=json.loads(request.content)['inspection']
        calls.append(query)
        page=InspectionPage(build_id=BID,section=query['section'],records=[],total=0)
        return httpx.Response(200,json=WorkerResult(baseline=snapshot(),results=[],inspection=page).model_dump(mode='json'))
    engine=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.MockTransport(respond),base_url='http://worker'))
    scout=Scout(user_agent='test',transport=httpx.MockTransport(Backend()),interval=0)
    server=build_server(scout,engine=engine,build_reader=BuildReader(tmp_path))
    cases=[
        ('inspect_build',{'request':{'build_id':BID,'section':'configuration','configuration_key':'not_saved'}}),
        ('inspect_build',{'request':{'build_id':BID,'section':'equipment','saved_item_id':999}}),
        ('inspect_build',{'request':{'build_id':BID,'section':'skills','offset':1000}}),
        ('get_build_equipment',{'build_id':BID,'saved_item_id':999}),
        ('get_build_equipment',{'build_id':BID,'slot':'ring_left'}),
        ('get_build_equipment',{'build_id':BID,'slot':'ring_left','offset':20}),
    ]
    try:
        async with create_connected_server_and_client_session(server) as session:
            schemas={tool.name:tool.outputSchema for tool in (await session.list_tools()).tools}
            for name,arguments in cases:
                before=len(calls)
                result=await session.call_tool(name,arguments)
                assert not result.isError, result
                assert result.structuredContent['records']==[]
                Draft202012Validator(schemas[name]).validate(result.structuredContent)
                assert len(calls)==before+1
        assert calls[-1]['slot']=='ring_left' and calls[-1]['offset']==20
    finally:
        await engine.close();await scout.close()


def test_keep_equip_unequip_space_and_budget_are_explicit():
    raw=item('Quarterstaff')
    pool={slot:[Option(WorkerChange(slot=slot,item=raw),
        TradeChange(slot=slot,listing_ref='a'*64,normalized_cost=2),Decimal(2))]
        for slot in ('weapon_main','weapon_off')}
    plans=enumerate_plans(pool,{'weapon_main','weapon_off'},2,Decimal(2))
    target=next(p for p in plans if [(c.slot,c.action) for c in p.public]==[
        ('weapon_main','equip'),('weapon_off','unequip')])
    assert target.cost==2 and target.changes[1].saved_item_id==0
    assert target.public[1].listing_ref is None and target.public[1].normalized_cost==0
    assert any(p.public and all(c.action=='unequip' for c in p.public) for p in plans)
    assert all(len([c for c in p.public if c.listing_ref])<=1 for p in plans)
    assert all(len(p.changes)<=1 for p in enumerate_plans(pool,{'weapon_off'},1,Decimal(2)))
    assert all(c.action=='equip' for p in enumerate_plans(pool,set(),2,Decimal(2)) for c in p.public)
    assert all(p.cost==0 for p in enumerate_plans(pool,{'weapon_off'},2,Decimal(1)))
    with pytest.raises(EngineError,match='engine_candidate_space_too_large'):
        enumerate_plans({}, {'helmet','body_armour','boots','gloves','belt','amulet','ring_left',
            'ring_right','weapon_main','weapon_off'},3,Decimal(2))


async def test_recommendation_retains_same_price_identity_constraints_fx_and_prefilter_reasons():
    sid='ts_'+'2'*32
    trade=TradeClient('test')
    now=int(time.time())
    rows={};private={}
    for ref,price in [('a',2),('b',2),('c',2),('d',None),('e',10),('f',2)]:
        raw=item(ref=ref)
        listing={'price':{'amount':price,'currency':'divine'}} if price else {}
        rows[ref*64]=parse_listing({'id':ref*64,'item':raw,'listing':listing},now-301 if ref=='c' else now)
        private[ref*64]=raw
    private['f'*64]['identified']=False
    trade.searches[sid]={'request':TradeSearchRequest(category='accessory.ring'),'created':now,
        'ids':list(rows),'rows':rows,'engine_items':private}
    seen=[]
    class Client(EngineClient):
        async def batch(self,request):
            seen.append(request)
            results=[]
            for changes in request.scenarios:
                ref=next((c.item['id'] for c in changes if c.item),None)
                results.append(snapshot(120 if ref=='a'*64 else 105))
            return WorkerResult(baseline=snapshot(),results=results)
    engine=Client('/unused')
    request=EngineTradeRequest(build_id=BID,search_ids=[sid],budget={'amount':5,'currency':'divine'},
        declared_character_league='Forbidden Rites',weights=[{'stat':'Life','weight':1}],
        constraints=[{'stat':'Life','minimum':110}])
    try:
        result=await engine.recommend(request,trade,None)
        assert result.feasible and result.changes[0].listing_ref=='a'*64
        calculation_id=result.calculation.calculation_id
        def page(section):
            return engine.receipts.page(DiagnosticRequest(calculation_id=calculation_id,section=section,limit=20))
        candidates=page('candidates').candidates
        a=next(c for c in candidates if c.selected)
        b=next(c for c in candidates if any(v.listing_ref=='b'*64 for v in c.changes))
        assert a.cost==b.cost==2 and a.rank==1
        assert b.status=='constraints_not_met' and b.constraint_violations[0].actual==105
        assert b.changes[0].slot in {'ring_left','ring_right'}
        excluded={v.listing_ref:v.reason for v in page('excluded_listings').excluded_listings}
        assert excluded=={'c'*64:'stale','d'*64:'missing_price','e'*64:'over_budget','f'*64:'private_import_rejected'}
        inputs={v.path:v.value for v in page('inputs').inputs}
        assert inputs['weights.0.stat']=='Life' and inputs['constraints.0.minimum']==110
        # Inputs are paginated too: recover every retained rate and source.
        recovered={};offset=0
        while offset is not None:
            p=engine.receipts.page(DiagnosticRequest(calculation_id=calculation_id,section='inputs',offset=offset,limit=20))
            recovered.update({v.path:v.value for v in p.inputs});offset=p.next_offset
        assert recovered['fx.rates.divine']==1 and recovered['fx.executable_exchange_rate'] is False
        result.changes[0].listing_ref='f'*64
        b.changes.clear()
        assert next(c for c in page('candidates').candidates if c.selected).changes[0].listing_ref=='a'*64
        assert 'explicitMods' not in page('candidates').model_dump_json()
        # All exclusions still produce a receipt and a baseline result.
        empty=await engine.recommend(request.model_copy(update={'candidate_refs':['c'*64]}),trade,None)
        assert not empty.feasible and empty.excluded_listings==1 and empty.calculation.calculation_id
    finally:
        await engine.close();await trade.close()
