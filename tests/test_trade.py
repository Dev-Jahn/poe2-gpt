import asyncio
import json
from pathlib import Path

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from poe2_companion.equipment import EquipmentService
from poe2_companion.scout import Scout
from poe2_companion.server import build_server
from poe2_companion.trade import (Gate, TradeClient, TradeError, TradePageRequest, TradeSearchRequest,
    TradeStatFilter, StatSearchRequest, TradeUpgradeRequest, parse_listing, STAT_SOURCE_EN, STAT_SOURCE_KO)
from test_equipment import NOW, example, imported, optimizer, stats
from test_scout import Backend


def filters():
    path=Path(__file__).parent/"fixtures/trade_filters.json"
    if path.exists():return json.loads(path.read_text())
    def field(id,options=()):return {"id":id,"option":{"options":[{"id":v} for v in options]}}
    return {"result":[
        {"id":"status_filters","filters":[field("status",["any","online","available","securable"])]},
        {"id":"type_filters","filters":[field("category",["accessory.ring","armour.helmet","weapon.bow"]),field("rarity",["rare","normal","magic","unique","nonunique"])]},
        {"id":"trade_filters","filters":[field("price",["exalted","chaos","divine"])]},
        {"id":"req_filters","filters":[field("lvl")]},
        {"id":"misc_filters","filters":[field("corrupted",["true","false"])]},
        {"id":"equipment_filters","filters":[field("pdps"),field("es")]},
    ]}


def listing(index,life=100,fire=30,amount=10):
    return {"id":f"{index:064x}","item":{"identified":True,"frameType":2,"baseType":"Gold Ring","corrupted":False,
        "requirements":[{"name":"Level","values":[["60",0]]}],
        "explicitMods":[f"+{life} to maximum Life",f"+{fire}% to Fire Resistance"]},
        "listing":{"price":{"amount":amount,"currency":"exalted"},"indexed":"2026-09-06T13:00:00Z",
            "whisper":"PRIVATE_WHISPER_DO_NOT_FORWARD","account":{"name":"PRIVATE_ACCOUNT_DO_NOT_FORWARD"}}}


class TradeBackend:
    def __init__(self,rows=None):
        self.rows=rows or [listing(i) for i in range(1,13)]
        self.requests=[]

    def __call__(self,r):
        self.requests.append(r)
        assert "cookie" not in r.headers and "authorization" not in r.headers
        if r.url.path.endswith("/data/leagues"):
            return httpx.Response(200,json={"result":[{"id":"Forbidden Rites","realm":"poe2"}]})
        if r.url.path.endswith("/data/filters"):
            return httpx.Response(200,json=filters())
        if r.url.path.endswith("/data/stats"):
            return httpx.Response(200,json={"result":[{"id":"pseudo","entries":[{"id":"pseudo.pseudo_total_life","text":"+# total maximum Life"}]}]})
        if "/search/" in r.url.path:
            return httpx.Response(200,json={"id":"testQ12","result":[v["id"] for v in self.rows],"total":len(self.rows)})
        if "/fetch/" in r.url.path:
            ids=r.url.path.split("/fetch/")[1].split(",")
            assert len(ids)<=10
            return httpx.Response(200,json={"result":[v for v in self.rows if v["id"] in ids]})
        raise AssertionError("unexpected endpoint")


async def test_search_metadata_query_fetch_cache_and_paging():
    backend=TradeBackend()
    client=TradeClient("test",transport=httpx.MockTransport(backend),interval=0,clock=lambda:NOW)
    try:
        found=await client.search_stats(StatSearchRequest(query="maximum Life"))
        assert found.entries[0].stat_id=="pseudo.pseudo_total_life"
        request=TradeSearchRequest(category="accessory.ring",stats=[TradeStatFilter(stat_id=found.entries[0].stat_id,minimum=80)])
        first=await client.search(request)
        assert len(first.items)==5 and first.next_offset==5 and first.total_matches==12
        search=[r for r in backend.requests if r.method=="POST"][0]
        body=json.loads(search.content)
        assert search.url.path=="/api/trade2/search/Forbidden Rites"
        assert body["query"]["filters"]["type_filters"]["filters"]["category"]=={"option":"accessory.ring"}
        assert body["query"]["stats"][0]["filters"]==[{"id":"pseudo.pseudo_total_life","value":{"min":80}}]
        previous=len(backend.requests)
        again=await client.search(request)
        assert again.search_id==first.search_id and len(backend.requests)==previous
        second=await client.page(TradePageRequest(search_id=first.search_id,offset=5))
        assert len(second.items)==5 and second.next_offset==10
        text=first.model_dump_json()
        assert "PRIVATE_" not in text and "explicitMods" not in text
    finally:await client.close()


async def test_unknown_league_or_stat_rejected_before_post():
    backend=TradeBackend()
    client=TradeClient("test",transport=httpx.MockTransport(backend),interval=0)
    try:
        with pytest.raises(TradeError,match="trade_unknown_league"):
            await client.search(TradeSearchRequest(category="accessory.ring",league="Bogus"))
        with pytest.raises(TradeError,match="trade_unknown_stat"):
            await client.search(TradeSearchRequest(category="accessory.ring",stats=[TradeStatFilter(stat_id="pseudo.fake",minimum=1)]))
        assert not any(r.method=="POST" for r in backend.requests)
    finally:await client.close()


async def test_concurrent_identical_searches_share_one_upstream_query():
    backend=TradeBackend()
    async def respond(r):
        await asyncio.sleep(0)
        return backend(r)
    client=TradeClient("test",transport=httpx.MockTransport(respond),interval=0)
    try:
        request=TradeSearchRequest(category="accessory.ring")
        a,b=await asyncio.gather(client.search(request),client.search(request))
        assert a.search_id==b.search_id
        assert len([r for r in backend.requests if r.method=="POST"])==1
    finally:await client.close()


async def test_long_url_safe_search_tokens_are_retained_opaque():
    backend=TradeBackend()
    token="H4sI_"+"aB0-"*70+"="
    def respond(r):
        response=backend(r)
        if r.method=="POST":
            data=response.json();data["id"]=token
            return httpx.Response(200,json=data)
        if "/fetch/" in r.url.path:
            assert r.url.params["query"]==token
        return response
    client=TradeClient("test",transport=httpx.MockTransport(respond),interval=0)
    try:
        result=await client.search(TradeSearchRequest(category="accessory.ring"))
        assert result.items and result.search_id.startswith("ts_")
        assert result.website_url.endswith("%3D")
    finally:await client.close()


async def test_fetch_batches_and_bounded_page_do_not_skip_candidates():
    backend=TradeBackend([listing(i) for i in range(1,28)])
    client=TradeClient("test",transport=httpx.MockTransport(backend),interval=0)
    try:
        result=await client.search(TradeSearchRequest(category="accessory.ring",max_results=27))
        entry=client.retained(result.search_id)
        await client.fetch(entry,entry["ids"])
        lengths=[len(r.url.path.split("/fetch/")[1].split(",")) for r in backend.requests if "/fetch/" in r.url.path]
        assert lengths==[5,10,10,2]
        assert len(entry["rows"])==27
    finally:await client.close()


@pytest.mark.parametrize("status,body,expected",[(403,"captcha","trade_interactive_verification_required"),(401,"login","trade_authentication_required"),(200,"<html>challenge</html>","trade_interactive_verification_required")])
async def test_challenges_stop_future_calls_without_bypass(status,body,expected):
    calls=[]
    def respond(r):
        calls.append(r)
        return httpx.Response(status,text=body)
    client=TradeClient("test",transport=httpx.MockTransport(respond),interval=0)
    try:
        for _ in range(2):
            with pytest.raises(TradeError,match=expected):await client.data("leagues")
        assert len(calls)==1
    finally:await client.close()


async def test_429_honors_retry_after_without_repeat_request():
    calls=[]
    def respond(r):
        calls.append(r)
        return httpx.Response(429,headers={"retry-after":"120"},json={"error":{"code":3}})
    client=TradeClient("test",transport=httpx.MockTransport(respond),interval=0)
    try:
        with pytest.raises(TradeError) as error:await client.data("leagues")
        assert error.value.code=="trade_rate_limited" and error.value.retry_after>=119
        with pytest.raises(TradeError,match="trade_rate_limited"):await client.data("leagues")
        assert len(calls)==1
    finally:await client.close()


def test_dynamic_rate_limits_include_server_consumption_and_all_windows():
    t=[100.0]
    gate=Gate(interval=0,clock=lambda:t[0])
    gate.observe(httpx.Headers({"X-Rate-Limit-Policy":"trade-search","X-Rate-Limit-Rules":"ip,account",
        "X-Rate-Limit-Ip":"3:5:10,10:60:120","X-Rate-Limit-Ip-State":"2:5:0,9:60:0",
        "X-Rate-Limit-Account":"5:10:20","X-Rate-Limit-Account-State":"4:10:0"}))
    assert gate.delay()==0
    gate.consume()
    assert gate.delay()==60
    t[0]=161
    assert gate.delay()==0


def test_item_parser_recognizes_basic_sums_but_excludes_unknown_effects():
    raw=listing(1)
    raw["item"]["implicitMods"]=["+10% to all Elemental Resistances","+5 to all Attributes"]
    row=parse_listing(raw,NOW)
    values={s.metric:s.value for s in row.item_stats}
    assert values["fire_resistance"]==40 and values["cold_resistance"]==10 and values["strength"]==5
    assert row.optimization_eligible
    raw["item"]["explicitMods"].append("PRIVATE_UNSUPPORTED_EFFECT_DO_NOT_FORWARD")
    row=parse_listing(raw,NOW)
    assert not row.optimization_eligible and row.unknown_modifier_count==1
    assert not row.proxy_optimization_eligible and not row.item_stats_complete
    assert row.item_stats  # Known contributions survive an unrelated unknown mod.
    assert "PRIVATE_" not in row.model_dump_json()
    raw["gone"]=True
    assert parse_listing(raw,NOW) is None


def test_real_rich_text_fixture_and_conditional_rune_exclusion():
    path=Path(__file__).parent/"fixtures/trade_listing_sanitized.json"
    rows=json.loads(path.read_text())["result"]
    conditional=parse_listing(rows[0],NOW)
    supported=parse_listing(rows[1],NOW)
    assert not conditional.optimization_eligible
    assert supported.optimization_eligible and supported.unscored_modifier_count==1
    assert {v.metric:v.value for v in supported.item_stats}["flat_life"]==150
    assert {v.metric:v.value for v in supported.item_stats}["cold_resistance"]==27


async def test_live_candidate_bridge_reuses_baseline_and_deduplicates(tmp_path):
    data=example();data["candidates"]=[]
    dataset_id,directory=imported(tmp_path,data)
    scout=Scout(user_agent="test",transport=httpx.MockTransport(Backend()),interval=0)
    service=EquipmentService(directory,scout,clock=lambda:NOW)
    client=TradeClient("test",transport=httpx.MockTransport(TradeBackend([listing(1,120,0,10),listing(2,60,60,12)])),interval=0,clock=lambda:NOW)
    try:
        search=await client.search(TradeSearchRequest(category="accessory.ring"))
        result=await client.recommend(TradeUpgradeRequest(optimization=optimizer(dataset_id),search_ids=[search.search_id]),service)
        assert result.optimization.plans[0].score_gain==80 and result.optimization.plans[0].cost==22
        assert result.optimization.origin=="trade_snapshot"
        assert result.baseline_origin=="synthetic_example"
        assert service.load(dataset_id).origin=="synthetic_example" and service.load(dataset_id).candidates==[]
    finally:
        await client.close();await scout.close()


async def test_full_mcp_trade_and_upgrade_path_with_sanitized_errors(tmp_path,caplog):
    dataset_id,directory=imported(tmp_path)
    scout=Scout(user_agent="test",transport=httpx.MockTransport(Backend()),interval=0)
    service=EquipmentService(directory,scout,clock=lambda:NOW)
    client=TradeClient("test",transport=httpx.MockTransport(TradeBackend()),interval=0,clock=lambda:NOW)
    server=build_server(scout,equipment=service,trade=client)
    try:
        async with create_connected_server_and_client_session(server) as session:
            status=await session.call_tool("get_trade_integration_status",{})
            assert status.structuredContent["direct_equipment_api"]
            found=await session.call_tool("search_trade_equipment",{"request":{"category":"accessory.ring"}})
            assert not found.isError
            request=TradeUpgradeRequest(optimization=optimizer(dataset_id),search_ids=[found.structuredContent["search_id"]])
            best=await session.call_tool("recommend_trade_upgrades",{"request":request.model_dump()})
            assert not best.isError and best.structuredContent["optimization"]["plans"]
            for arguments in [{"request":{"category":"accessory.ring","pob_code":"PRIVATE_POB_PAYLOAD"}},
                              {"request":{"category":"PRIVATE_POB_PAYLOAD"}}]:
                bad=await session.call_tool("search_trade_equipment",arguments)
                assert bad.isError and "PRIVATE_POB_PAYLOAD" not in bad.model_dump_json()
            assert "PRIVATE_POB_PAYLOAD" not in caplog.text
    finally:
        await client.close();await scout.close()


def stat_catalog(rows):
    return {"result":[{"id":"pseudo","entries":rows}]}


async def test_bilingual_stats_join_exact_ids_and_refresh_metadata_cache():
    import unicodedata
    now=[NOW]
    calls=[]
    canonical={"id":"pseudo.pseudo_total_life","text":"+# total maximum Life"}
    korean={"id":canonical["id"],"text":"최대 생명력 총 +#"}
    backend=TradeBackend()
    def respond(request):
        calls.append(request)
        assert "cookie" not in request.headers and "authorization" not in request.headers
        if str(request.url) in {STAT_SOURCE_EN,STAT_SOURCE_KO}:
            row=korean if request.url.host=="poe.kakaogames.com" else canonical
            return httpx.Response(200,json=stat_catalog([row]),headers={"set-cookie":"session=not-forwarded; Path=/"})
        return backend(request)
    client=TradeClient("test",transport=httpx.MockTransport(respond),interval=0,clock=lambda:now[0])
    try:
        found=await client.search_stats(StatSearchRequest(query="생명력"))
        assert [(e.stat_id,e.text,e.text_ko) for e in found.entries]==[(canonical["id"],canonical["text"],korean["text"])]
        assert found.text_source_en==STAT_SOURCE_EN and found.text_source_ko==STAT_SOURCE_KO
        assert found.translation_status=="available" and found.translation_retrieved_at_epoch==NOW
        body=await client.query(TradeSearchRequest(category="accessory.ring",stats=[TradeStatFilter(stat_id=found.entries[0].stat_id,minimum=80)]))
        assert body["query"]["stats"][0]["filters"]==[{"id":canonical["id"],"value":{"min":80}}]
        mixed=await client.search_stats(StatSearchRequest(query="Life 생명력"))
        assert mixed.entries==found.entries
        decomposed=await client.search_stats(StatSearchRequest(query=unicodedata.normalize("NFD","생명력")))
        assert decomposed.entries==found.entries
        assert len([r for r in calls if r.url.path.endswith("/data/stats")])==2
        now[0]+=21601
        refreshed=await client.search_stats(StatSearchRequest(query="maximum Life"))
        assert refreshed.translation_retrieved_at_epoch==now[0]
        assert len([r for r in calls if r.url.path.endswith("/data/stats")])==4
    finally:
        await client.close()


async def test_bilingual_stats_exclude_options_conflicts_and_unmatched_ids():
    def row(i,text="Life",**extra):return {"id":"explicit.stat_"+str(i),"text":text,**extra}
    english=[row(1),row(2,option={"options":[]}),row(3),row(3,"Mana"),row(4),row(5),row(6),row(6)]
    korean=[row(1,"생명력"),row(4,"생명력"),row(4,"마나"),row(5,"생명력",option={}),row(6,"최대 생명력"),row(99,"가짜 생명력")]
    def respond(request):
        return httpx.Response(200,json=stat_catalog(korean if request.url.host=="poe.kakaogames.com" else english))
    client=TradeClient("test",transport=httpx.MockTransport(respond),interval=0)
    try:
        assert set(await client.stats())=={"explicit.stat_1","explicit.stat_4","explicit.stat_5","explicit.stat_6"}
        found=await client.search_stats(StatSearchRequest(query="Life",group="any"))
        assert found.translation_status=="partial"
        assert {e.stat_id:e.text_ko for e in found.entries}=={
            "explicit.stat_1":"생명력","explicit.stat_4":None,"explicit.stat_5":None,"explicit.stat_6":"최대 생명력"}
        assert (await client.search_stats(StatSearchRequest(query="가짜",group="any"))).entries==[]
        assert [e.stat_id for e in (await client.search_stats(StatSearchRequest(query="생명력",group="any"))).entries]==["explicit.stat_1","explicit.stat_6"]
    finally:
        await client.close()


@pytest.mark.parametrize("has_translation",[False,True])
async def test_korean_provider_english_fallback_is_not_marked_translated(has_translation):
    english=[{"id":"pseudo.pseudo_total_life","text":"Life"},{"id":"pseudo.pseudo_total_mana","text":"Mana"}]
    korean=[english[0],{"id":"pseudo.pseudo_total_mana","text":"마나" if has_translation else "Mana"}]
    def respond(request):
        return httpx.Response(200,json=stat_catalog(korean if request.url.host=="poe.kakaogames.com" else english))
    client=TradeClient("test",transport=httpx.MockTransport(respond),interval=0)
    try:
        found=await client.search_stats(StatSearchRequest(query="Life"))
        assert found.entries[0].text_ko is None
        assert found.translation_status==("partial" if has_translation else "unavailable")
        assert found.translation_error_code is None and found.text_source_ko==STAT_SOURCE_KO
    finally:
        await client.close()


@pytest.mark.parametrize("status,error,attempts",[(403,"trade_interactive_verification_required",1),
    (401,"trade_authentication_required",1),(429,"trade_rate_limited",1),(500,"trade_unavailable",2)])
async def test_korean_stat_failures_never_block_english_requests(status,error,attempts):
    calls=[]
    now=[NOW]
    backend=TradeBackend()
    def respond(request):
        calls.append(request)
        if request.url.host=="poe.kakaogames.com":
            return httpx.Response(status,headers={"retry-after":"120"} if status==429 else {},text="upstream blocked")
        return backend(request)
    client=TradeClient("test",transport=httpx.MockTransport(respond),interval=0,clock=lambda:now[0])
    try:
        for query in ("Life","생명력"):
            found=await client.search_stats(StatSearchRequest(query=query))
            if query=="Life":
                assert found.entries and found.entries[0].text_ko is None
            else:
                assert found.entries==[]
            assert found.translation_status=="unavailable" and found.translation_error_code==error
            assert found.text_source_ko is None and found.translation_retrieved_at_epoch is None
        assert await client.data("leagues")
        assert client.blocked is None and client.gate.delay()==0
        assert len([r for r in calls if r.url.host=="poe.kakaogames.com"])==attempts
        if status in (401,403):
            now[0]+=61
            assert (await client.search_stats(StatSearchRequest(query="Life"))).translation_error_code==error
            assert len([r for r in calls if r.url.host=="poe.kakaogames.com"])==1
    finally:
        await client.close()


async def test_korean_metadata_lock_does_not_delay_english_requests():
    started,release=asyncio.Event(),asyncio.Event()
    backend=TradeBackend()
    async def respond(request):
        if request.url.host=="poe.kakaogames.com":
            started.set()
            await release.wait()
            return httpx.Response(200,json=stat_catalog([{"id":"pseudo.pseudo_total_life","text":"최대 생명력 총 +#"}]))
        return backend(request)
    client=TradeClient("test",transport=httpx.MockTransport(respond),interval=0)
    pending=asyncio.create_task(client.search_stats(StatSearchRequest(query="생명력")))
    try:
        await asyncio.wait_for(started.wait(),1)
        assert await asyncio.wait_for(client.data("leagues"),1)
        release.set()
        assert (await pending).entries
    finally:
        release.set()
        await pending
        await client.close()


async def test_bilingual_stat_pages_remain_bounded_without_skipping_ids():
    english=[{"id":f"explicit.stat_{i:02}","text":"Life "+"a"*235} for i in range(15)]
    korean=[{"id":r["id"],"text":"생명력"+"가"*237} for r in english]
    def respond(request):
        return httpx.Response(200,json=stat_catalog(korean if request.url.host=="poe.kakaogames.com" else english))
    client=TradeClient("test",transport=httpx.MockTransport(respond),interval=0)
    try:
        ids=[];offset=0
        while offset is not None:
            found=await client.search_stats(StatSearchRequest(query="생명력",group="explicit",offset=offset,limit=10))
            assert len(found.model_dump_json().encode())<=8192
            assert found.entries and found.matched_total==15
            ids.extend(e.stat_id for e in found.entries)
            if found.next_offset is not None:
                assert found.next_offset==offset+len(found.entries)
            offset=found.next_offset
        assert ids==[r["id"] for r in english]
    finally:
        await client.close()


@pytest.mark.parametrize("rarity,expected",[("Normal","normal"),("Magic","magic"),("Rare","rare"),("Unique","unique")])
def test_current_official_rarity_without_deprecated_frame_type(monkeypatch,rarity,expected):
    # Isolate item-schema compatibility from the independent names catalog.
    monkeypatch.setattr("poe2_companion.trade.name_fields",lambda *_:{})
    raw=listing(1)
    del raw["item"]["frameType"]
    raw["item"]["rarity"]=rarity
    assert parse_listing(raw,NOW).rarity==expected


def test_rarity_fallback_does_not_hide_invalid_legacy_values(monkeypatch):
    monkeypatch.setattr("poe2_companion.trade.name_fields",lambda *_:{})
    for frame in [None,True,"2",7]:
        raw=listing(1);raw["item"].update(frameType=frame,rarity="Rare")
        assert parse_listing(raw,NOW) is None
    for rarity in [None,"rare","Currency"]:
        raw=listing(1);del raw["item"]["frameType"];raw["item"]["rarity"]=rarity
        assert parse_listing(raw,NOW) is None
    raw=listing(1);raw["item"]["rarity"]="Unique"
    assert parse_listing(raw,NOW).rarity=="rare"
