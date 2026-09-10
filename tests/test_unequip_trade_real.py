"""A real weapon transition must clear its shield before equipping two hands."""
import base64
import time
import zlib
from xml.etree import ElementTree as ET

import httpx

from poe2_companion.diagnostics import DiagnosticRequest
from poe2_companion.engine import EngineClient
from poe2_companion.engine_models import EngineTradeRequest
from poe2_companion.engine_worker import worker_app
from poe2_companion.trade import TradeClient, TradeSearchRequest, parse_listing
from test_engine_real import real_engine, FIXTURE, BID, item


async def test_recommend_two_hands_by_removing_shield_in_a_proven_sequence(real_engine):
    root=ET.fromstring(FIXTURE.read_bytes())
    items=root.find('Items')
    for identifier,base,slot,mods in [
        (1,'Wooden Club','Weapon 1',[]),
        (2,'Splintered Tower Shield','Weapon 2',[]),
        (3,'Iron Ring','Ring 1',['+100 to all Attributes']),
    ]:
        ET.SubElement(items,'Item',{'id':str(identifier)}).text='\n'.join([
            'Rarity: RARE','Synthetic',base,'Item Level: 80','Implicits: 0',*mods])
        next(s for s in items.find('ItemSet').findall('Slot') if s.get('name')==slot).set('itemId',str(identifier))
    (real_engine.private_dir/(BID+'.pob')).write_bytes(base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))))
    sid='ts_'+'2'*32
    raw=item('Wrapped Quarterstaff',['+200 to maximum Life'])
    now=int(time.time())
    row=parse_listing({'id':'a'*64,'item':raw,'listing':{'price':{'amount':2,'currency':'divine'}}},now)
    trade=TradeClient('test')
    trade.searches[sid]={'request':TradeSearchRequest(category='weapon.warstaff'),'created':now,
        'ids':['a'*64],'rows':{'a'*64:row},'engine_items':{'a'*64:raw}}
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://worker'))
    request=EngineTradeRequest(build_id=BID,search_ids=[sid],declared_character_league='Forbidden Rites',
        budget={'amount':3,'currency':'divine'},weights=[{'stat':'Life','weight':1}],max_changes=2)
    try:
        result=await client.recommend(request,trade,None)
        assert result.feasible and result.cost==2, result
        assert [(c.slot,c.action) for c in result.changes]==[('weapon_main','equip'),('weapon_off','unequip')]
        assert result.calculation.result.equipment_validity=='pass'
        assert result.calculation.result.equip_order==['weapon_off','weapon_main']
        assert all(e.slot!='weapon_off' for e in result.calculation.result.equipped)
        receipt=client.receipts.page(DiagnosticRequest(calculation_id=result.calculation.calculation_id,section='candidates',limit=20))
        assert any(c.selected and any(v.action=='unequip' for v in c.changes) for c in receipt.candidates)
    finally:
        await client.close();await trade.close()
