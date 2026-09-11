"""Private timing/cache headers cross the actual worker contract only on opt-in."""
import httpx
from poe2_companion.engine import EngineClient
from poe2_companion.engine_worker import worker_app
from poe2_companion.profiles import ProfileRequest
from poe2_companion.workflow_metrics import CURRENT,Measurements
from test_engine_real import real_engine,BID


async def test_private_static_metrics_are_opt_in_and_hot_cache_survives_busy_loader(real_engine):
    http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://pob-worker')
    client=EngineClient('/unused',http=http)
    try:
        metrics=Measurements();token=CURRENT.set(metrics)
        try:
            await client.profile(ProfileRequest(build_id=BID))
            assert metrics.counts['cache_miss']==1 and metrics.milliseconds['worker_execution']>0
            assert metrics.milliseconds['worker_round_trip']>=metrics.milliseconds['worker_execution']
            async with real_engine.inspector.lock:
                await client.profile(ProfileRequest(build_id=BID))
            assert metrics.counts['cache_hit']==1
        finally: CURRENT.reset(token)
        plain=await http.post('/profile',json={'build_id':BID})
        assert plain.status_code==200 and 'x-poe2-workflow-timing' not in plain.headers
    finally: await client.close()
