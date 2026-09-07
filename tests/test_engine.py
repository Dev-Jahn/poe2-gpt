import asyncio
import json
import logging
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from poe2_companion.engine import EngineClient
from poe2_companion.engine_models import EngineRequest, CompareRequest, EngineTradeRequest, EngineError, ENGINE_COMMIT
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


def test_private_trade_projection_no_seller_encoded_or_url():
    v=item(mods=[{'description':'+100 to maximum [Life]','flags':{}}])
    v.update({'note':MARKER,'icon':'https://example.invalid/'+MARKER,'extended':{'text':MARKER}})
    out=private_trade_item(v)
    assert MARKER not in json.dumps(out) and out['explicitMods'][0]['description']=='+100 to maximum Life'
    v['socketedItems']=[{'id':'a'}]
    with pytest.raises(EngineError):private_trade_item(v)


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
    slow=tmp_path/'slow';slow.write_text('#!/bin/sh\nexec /bin/sleep 10\n');slow.chmod(0o700)
    engine=PrivateEngine(tmp_path/'private',source,str(slow),timeout=.05)
    with pytest.raises(EngineError,match='engine_timeout'):await engine.calculate(WorkerRequest(build_id=bid))
    (source/'COMPANION_COMMIT').write_text('wrong')
    with pytest.raises(EngineError,match='engine_version_mismatch'):await engine.calculate(WorkerRequest(build_id=bid))
