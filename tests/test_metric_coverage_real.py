"""Metric dependency and invalid-baseline repair regressions on the real engine."""
import base64
import time
import zlib
from xml.etree import ElementTree as ET

import httpx
import pytest

from poe2_companion.engine import EngineClient
from poe2_companion.engine_models import EngineTradeRequest, EngineError
from poe2_companion.engine_protocol import WorkerRequest
from poe2_companion.engine_worker import worker_app
from poe2_companion.trade import TradeClient, TradeSearchRequest, parse_listing
from test_engine_real import real_engine, FIXTURE, BID, item, change


def save(engine, *, ring_mods=(), helmet=None):
    root=ET.fromstring(FIXTURE.read_bytes())
    group=ET.SubElement(root.find('./Skills/SkillSet'), 'Skill', {'enabled':'true','mainActiveSkill':'1'})
    ET.SubElement(group,'Gem',{'skillId':'MeleeAtAnimationSpeed','level':'1','quality':'0','enabled':'true'})
    items=root.find('Items')
    for identifier, base, slot, mods in [(1,'Sapphire Ring','Ring 1',ring_mods),
            *([(2,'Soldier Greathelm','Helmet',helmet)] if helmet is not None else [])]:
        ET.SubElement(items,'Item',{'id':str(identifier)}).text='\n'.join([
            'Rarity: RARE','Synthetic',base,'Item Level: 80','Implicits: 0',*mods])
        target=next(s for s in items.find('ItemSet').findall('Slot') if s.get('name')==slot)
        target.set('itemId',str(identifier))
    (engine.private_dir/(BID+'.pob')).write_bytes(base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))))


async def test_leech_uncertainty_allows_proven_resource_but_blocks_damage_and_unknown(real_engine):
    save(real_engine,ring_mods=['Leech 10% of Physical Attack Damage as Life'])
    result=await real_engine.calculate(WorkerRequest(build_id=BID,scenarios=[
        [change('ring_right',mods=['+100 to maximum Life'])],
        [change('ring_right',mods=['100% increased maximum Life while on Full Life'])],
        [change('ring_right',mods=['An unrecognized effect'])],
    ]))
    assert result.baseline.validation=='indeterminate'
    assert result.baseline.equipment_validity=='pass', result.baseline.issues
    coverage={r.stat:r.status for r in result.baseline.metric_coverage}
    assert coverage['Life']=='pass' and coverage['EnergyShield']=='pass'
    assert coverage['TotalDPS']=='indeterminate'
    assert next(r for r in result.results[0].metric_coverage if r.stat=='Life').status=='pass'
    assert all(next(r for r in s.metric_coverage if r.stat=='Life').status=='indeterminate' for s in result.results[1:])


async def test_repair_workflow_and_league_provenance(real_engine):
    save(real_engine,helmet=[])
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://pob-worker'))
    trade=TradeClient('test')
    sid='ts_'+'2'*32
    rows={};private={}
    for ref,strength,cost in [('a',10,2),('b',20,5)]:
        raw=item(mods=[f'+{strength} to Strength'],ref=ref)
        rows[ref*64]=parse_listing({'id':ref*64,'item':raw,'listing':{'price':{'amount':cost,'currency':'divine'}}},int(time.time()))
        private[ref*64]=raw
    trade.searches[sid]={'request':TradeSearchRequest(category='accessory.ring'),'created':int(time.time()),'ids':list(rows),'rows':rows,'engine_items':private}
    request=EngineTradeRequest(build_id=BID,search_ids=[sid],budget={'amount':5.0,'currency':'divine'},mode='restore_validity',declared_character_league='Forbidden Rites')
    try:
        result=await client.recommend(request,trade,None)
        assert result.calculation.baseline.equipment_validity=='fail'
        assert result.feasible and result.cost==2 and not result.baseline_comparison_valid
        assert result.calculation.result.equipment_validity=='pass'
        assert not result.calculation.deltas and result.score_gain==0
        with pytest.raises(EngineError,match='character_league_unverified'):
            await client.recommend(request.model_copy(update={'declared_character_league':None}),trade,None)
        (real_engine.private_dir/(BID+'.origin.json')).write_text('{"league_name":"Standard","league_slug":"standard","source":"poe.ninja"}')
        with pytest.raises(EngineError,match='character_league_mismatch'):
            await client.recommend(request,trade,None)
    finally:
        await client.close();await trade.close()
