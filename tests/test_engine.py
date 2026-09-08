import asyncio
import json
import logging
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from poe2_companion.engine import EngineClient
from poe2_companion.engine_models import EngineRequest, CompareRequest, EngineTradeRequest, EngineError, ENGINE_COMMIT, ENGINE_DATA_COMMIT, ENGINE_COMPATIBILITY
from poe2_companion.engine_worker import PrivateEngine, worker_app
from poe2_companion.engine_protocol import WorkerRequest, WorkerResult, private_trade_item
from poe2_companion.server import build_server
from poe2_companion.scout import Scout
from test_engine_real import BID, MARKER, item
from test_scout import Backend


@pytest.mark.parametrize('dto,data',[
    (EngineRequest,{'build_id':MARKER}),
    (EngineRequest,{'build_id':BID,'code':MARKER}),
    (EngineRequest,{'build_id':BID,'path':'/private-builds/'+MARKER}),
    (CompareRequest,{'build_id':BID,'replacements':[{'slot':'helmet','saved_item_id':1},{'slot':'helmet','saved_item_id':2}]}),
    (CompareRequest,{'build_id':BID,'replacements':[{'slot':'ring_left','saved_item_id':1},{'slot':'ring_right','saved_item_id':1}]}),
    (EngineTradeRequest,{'build_id':BID,'search_ids':['ts_'+'1'*32],'budget':{'amount':5.,'currency':'divine'}}),
])
def test_closed_engine_inputs(dto,data):
    with pytest.raises(ValidationError) as err:dto.model_validate(data)
    assert MARKER not in str(err.value)


def test_public_engine_metadata_schema_is_stable_across_pin_updates(monkeypatch):
    from poe2_companion import engine_models as models
    classes=(models.EngineStatus,models.EngineCalculation,models.EngineTradeResult)
    before={cls:cls.model_json_schema(mode='serialization') for cls in classes}
    old_status=models.EngineStatus(enabled=True,reachable=True)
    expected={'engine_commit':'a'*40, 'engine_data_commit':'b'*40,
              'engine_compatibility':'next-league-0.6.0-v2'}
    for field,value in expected.items():
        monkeypatch.setattr(models,field.upper(),value)
    snapshot=models.EngineSnapshot(stats=[],equipped=[],issues=[],issue_count=0,
        validation='pass',active_weapon_set=1,main_skill_group=0)
    outputs=(models.EngineStatus(enabled=True,reachable=True),
        models.EngineCalculation(build_id=BID,calculated_at_epoch=1,baseline=snapshot))
    for result in outputs:
        assert {field:getattr(result,field) for field in expected}==expected
    assert old_status.engine_commit!=outputs[0].engine_commit
    for cls in classes:
        assert cls.model_json_schema(mode='serialization')==before[cls]
    for cls in classes[:2]:
        for field in expected:
            schema=before[cls]['properties'][field]
            assert 'const' not in schema and 'default' not in schema


def test_mechanics_are_closed_and_truncation_preserves_uncertainty():
    from poe2_companion.engine import bounded_engine_dto
    from poe2_companion.engine_models import EngineSnapshot, EngineCalculation, MechanicResult
    row = MechanicResult(mechanic='charge_consumption',status='partial',
        metrics=[{'name':name,'value':1.23456789012345} for name in (
            'charge_retention_chance','expected_removed_fraction',
            'power_charges_configured','frenzy_charges_configured','endurance_charges_configured',
            'power_charges_counted_for_consumption','frenzy_charges_counted_for_consumption','endurance_charges_counted_for_consumption')],
        required_inputs=['charge_gain_events','charge_consumption_events'])
    snapshot=EngineSnapshot(stats=[],equipped=[],issues=[{'code':'charge_sustain_unverified'}],
        issue_count=1,validation='indeterminate',active_weapon_set=1,main_skill_group=1,
        mechanics=[row.model_copy(deep=True) for _ in range(16)],mechanic_count=16)
    value=EngineCalculation(build_id=BID,calculated_at_epoch=1,baseline=snapshot,result=snapshot)
    result=bounded_engine_dto(value)
    assert len(result.model_dump_json().encode())<=8192
    for s in (result.baseline,result.result):
        assert s.validation=='indeterminate' and s.issue_count==1 and s.mechanic_count==16
        assert s.mechanics_truncated
    assert len(value.baseline.mechanics)==16
    with pytest.raises(ValidationError):
        MechanicResult(mechanic='charge_gain',status='calculated',metrics=[{'name':MARKER,'value':1}])


@pytest.mark.parametrize('field,value',[
    ('engine_commit','a'*39), ('engine_commit','A'*40),
    ('engine_data_commit','g'*40), ('engine_data_commit','a'*40+'\n'),
    ('engine_compatibility',''), ('engine_compatibility','invalid version'),
    ('engine_compatibility','x'*65), ('engine_compatibility','../invalid'),
])
def test_public_engine_metadata_rejects_malformed_values(field,value):
    from poe2_companion.engine_models import EngineStatus
    with pytest.raises(ValidationError):
        EngineStatus(enabled=True,reachable=True,**{field:value})


@pytest.mark.parametrize('changed', [None,'engine_commit','engine_data_commit','engine_compatibility'])
async def test_client_health_still_requires_exact_runtime_pins(changed):
    health={'engine_commit':ENGINE_COMMIT,'engine_data_commit':ENGINE_DATA_COMMIT,
            'engine_compatibility':ENGINE_COMPATIBILITY}
    if changed:
        health[changed]='different-v1' if changed=='engine_compatibility' else '0'*40
    http=httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=health)),
                           base_url='http://worker')
    client=EngineClient('/unused',http=http)
    try:
        status=await client.status()
        assert status.reachable is (changed is None)
        assert status.engine_commit==ENGINE_COMMIT
        assert status.engine_data_commit==ENGINE_DATA_COMMIT
        assert status.engine_compatibility==ENGINE_COMPATIBILITY
    finally:
        await client.close()


@pytest.mark.parametrize('mode,field',[
    ('current',None), ('legacy',None),
    ('missing','engine_commit'), ('missing','engine_data_commit'), ('missing','engine_compatibility'),
    ('mismatch','engine_commit'), ('mismatch','engine_data_commit'), ('mismatch','engine_compatibility'),
])
async def test_every_calculation_verifies_worker_provenance_without_health_call(mode,field):
    from poe2_companion.engine_models import EngineSnapshot
    snapshot=EngineSnapshot(stats=[],equipped=[],issues=[],issue_count=0,
        validation='pass',active_weapon_set=1,main_skill_group=0)
    payload=WorkerResult(baseline=snapshot,results=[]).model_dump()
    if mode=='legacy':
        for key in ('engine_commit','engine_data_commit','engine_compatibility'):
            payload.pop(key)
    elif mode=='missing':
        payload.pop(field)
    elif mode=='mismatch':
        payload[field]='old-v1' if field=='engine_compatibility' else '0'*40
    seen=[]
    def respond(request):
        seen.append(request.url.path)
        return httpx.Response(200,json=payload)
    http=httpx.AsyncClient(transport=httpx.MockTransport(respond),base_url='http://worker')
    client=EngineClient('/unused',http=http)
    try:
        if mode=='current':
            result=await client.calculate(EngineRequest(build_id=BID))
            assert result.engine_commit==ENGINE_COMMIT
            assert result.engine_data_commit==ENGINE_DATA_COMMIT
            assert result.engine_compatibility==ENGINE_COMPATIBILITY
        else:
            with pytest.raises(EngineError,match='^engine_version_mismatch$'):
                await client.calculate(EngineRequest(build_id=BID))
        assert seen==['/batch']
    finally:
        await client.close()


def test_private_trade_projection_no_seller_encoded_or_url():
    v=item(mods=[{'description':'+100 to maximum [Life]','flags':{}}])
    v.update({'note':MARKER,'icon':'https://example.invalid/'+MARKER,'extended':{'text':MARKER}})
    out=private_trade_item(v)
    assert MARKER not in json.dumps(out) and out['explicitMods'][0]['description']=='+100 to maximum Life'
    v['socketedItems']=[{'id':'a'}]
    with pytest.raises(EngineError):private_trade_item(v)


@pytest.mark.parametrize('sockets,index', [([],0),([{'type':'rune'}],9),([{'type':'jewel'}],0)])
def test_socketed_rune_must_reference_a_real_rune_socket(sockets,index):
    v=item('Rusted Cuirass')
    v.update(sockets=sockets,socketedItems=[{'baseType':'Soul Core of Jiquani','socket':index}])
    with pytest.raises(EngineError):
        private_trade_item(v)


def test_current_rarity_maps_to_pinned_importer_without_legacy_frame_type():
    v=item()
    v.pop('frameType')
    v['rarity']='Rare'
    assert private_trade_item(v)['frameType']==2
    v['rarity']='Unknown'
    with pytest.raises(EngineError):
        private_trade_item(v)


async def test_mcp_arguments_and_errors_never_echo_private_text(tmp_path,caplog):
    scout=Scout(user_agent='test',transport=httpx.MockTransport(Backend()),cache_path=str(tmp_path/'cache.db'),interval=0)
    class Unavailable:
        async def calculate(self,request):raise EngineError('engine_unavailable')
        async def status(self):raise EngineError('engine_unavailable')
    server=build_server(scout,engine=Unavailable())
    try:
        for name in ['recalculate_build','validate_build_equipment','compare_build_equipment','recommend_pob_trade_upgrades']:
            result=await server.call_tool(name,{'request':{'build_id':BID,'code':MARKER}})
            assert result.isError and MARKER not in str(result)
        result=await server.call_tool('recalculate_build',{'request':{'build_id':BID}})
        assert result.isError and 'engine_unavailable' in str(result)
        assert MARKER not in caplog.text
        tools=await server.list_tools()
        for t in tools:
            if t.name in ['recalculate_build','validate_build_equipment','compare_build_equipment']:
                assert 'saved_item_id' in str(t.inputSchema) or 'build_id' in str(t.inputSchema)
                assert 'xml' not in json.dumps(t.inputSchema)
    finally:await scout.close()


@pytest.mark.parametrize('body,status',[
    ({'code':'engine_timeout'},400),
    ({'code':MARKER},400),
    ({'baseline':{'raw':MARKER},'results':[]},200),
])
async def test_client_discards_untrusted_worker_errors(body,status):
    http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(status,json=body)),base_url='http://worker')
    client=EngineClient('/unused',http=http)
    try:
        with pytest.raises(EngineError) as err:await client.batch(WorkerRequest(build_id=BID))
        assert MARKER not in str(err.value)
    finally:await client.close()


async def test_worker_rejects_payloads_and_oversize_without_engine_access(tmp_path):
    class Never:
        async def calculate(self,request):raise AssertionError('must not calculate')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(Never())),base_url='http://worker') as http:
        for data in [json.dumps({'build_id':BID,'xml':MARKER}),MARKER*10000]:
            r=await http.post('/batch',content=data)
            assert r.status_code==400 and r.json()=={'code':'engine_invalid_request'}


async def test_private_worker_resource_timeout_and_version(tmp_path):
    from test_engine_real import FIXTURE
    from poe2_companion.pob_io import import_file
    import base64,zlib,sys
    raw=tmp_path/'input';raw.write_bytes(base64.urlsafe_b64encode(zlib.compress(FIXTURE.read_bytes())))
    bid=import_file(raw,tmp_path/'private',tmp_path/'projection')
    source=tmp_path/'source';source.mkdir();(source/'src').mkdir()
    (source/'COMPANION_COMMIT').write_text(ENGINE_COMMIT)
    (source/'COMPANION_DATA_COMMIT').write_text(ENGINE_DATA_COMMIT)
    (source/'COMPANION_COMPATIBILITY').write_text(ENGINE_COMPATIBILITY)
    slow=tmp_path/'slow';slow.write_text('#!/bin/sh\nexec /bin/sleep 10\n');slow.chmod(0o700)
    engine=PrivateEngine(tmp_path/'private',source,str(slow),timeout=.05)
    with pytest.raises(EngineError,match='engine_timeout'):await engine.calculate(WorkerRequest(build_id=bid))
    (source/'COMPANION_COMMIT').write_text('wrong')
    with pytest.raises(EngineError,match='engine_version_mismatch'):await engine.calculate(WorkerRequest(build_id=bid))


def test_engine_comparison_bounds_diagnostics_without_losing_status_or_counts():
    from typing import get_args
    from poe2_companion.engine import bounded_engine_dto
    from poe2_companion.engine_models import (EngineSnapshot,EngineCalculation,RequirementIssue,EquippedItem,SelectedSkill,EngineSlot)
    from poe2_companion.builds import STAT_NAMES,PlayerStat
    stats=[PlayerStat(name=s,value=1e15) for s in sorted(STAT_NAMES)]
    issues=[RequirementIssue(code='attribute_requirement',slot='body_armour',stat='Int',required=1e15,available=-1e15,passive_node_id=2147483647-i) for i in range(16)]
    equipped=[EquippedItem(slot=s,saved_item_id=1000000,level_required=100) for s in get_args(EngineSlot)]
    skill=SelectedSkill(skill_id='A'*120,name='B'*120,gem_name='C'*120,actor='minion')
    snapshot=EngineSnapshot(stats=stats,issues=issues,issue_count=1000,validation='fail',equipped=equipped,selected_skill=skill,active_weapon_set=2,main_skill_group=10000)
    value=EngineCalculation(build_id=BID,calculated_at_epoch=1788888888,baseline=snapshot,result=snapshot,deltas=stats)
    assert len(value.model_dump_json().encode())>8192
    result=bounded_engine_dto(value)
    assert len(result.model_dump_json().encode())<=8192
    for s in (result.baseline,result.result):
        assert s.issue_count==1000 and s.validation=='fail' and s.issues_truncated
        assert s.stats==stats and s.equipped==equipped and s.selected_skill==skill
    assert len(value.baseline.issues)==16  # Don't mutate the private calculation.
