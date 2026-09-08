"""Experimental trade2 website client, following observable open-source clients.

This is not GGG's documented OAuth developer API. Read-only user-requested
searches only; no challenge solving, cookies, arbitrary URLs or game actions.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import secrets
import time
from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Annotated, Literal
from urllib.parse import quote

import httpx
from pydantic import Field, model_validator

from .builds import DTO, BuildError, bounded_dto
from .game_terms import name_fields
from .equipment import (Currency, DatasetID, LeagueName, Number, OptimizeRequest, Price, Stat,
                        Candidate, Dataset, EquipmentService, UpgradeResult, unique)

BASE = "https://www.pathofexile.com"
TRADE_API = BASE+"/api/trade2"
MAX_BYTES = 8*1024*1024
Category = Literal["armour.helmet", "armour.chest", "armour.gloves", "armour.boots", "armour.shield", "armour.focus",
    "armour.buckler", "armour.quiver", "accessory.ring", "accessory.amulet", "accessory.belt", "jewel",
    "weapon.bow", "weapon.crossbow", "weapon.wand", "weapon.staff", "weapon.warstaff", "weapon.sceptre",
    "weapon.spear", "weapon.onemace", "weapon.twomace", "weapon.oneaxe", "weapon.twoaxe", "weapon.onesword",
    "weapon.twosword", "weapon.dagger", "weapon.claw", "weapon.flail", "weapon.talisman"]
Property = Literal["ar", "ev", "es", "dps", "pdps", "edps", "aps", "crit", "block", "spirit", "rune_sockets"]
STAT_ID = r"^(?:explicit|implicit|pseudo|crafted|enchant|rune|fractured|desecrated|mutated)\.[A-Za-z0-9_]{1,70}$"
StatID = Annotated[str, Field(pattern=STAT_ID,max_length=90)]
SearchID = Annotated[str, Field(pattern=r"^ts_[0-9a-f]{32}$",max_length=35)]
SAFE_ERRORS = {"trade_rate_limited", "trade_interactive_verification_required", "trade_authentication_required",
    "trade_schema_changed", "trade_invalid_query", "trade_unavailable", "trade_response_too_large",
    "trade_unknown_filter", "trade_unknown_league", "trade_search_expired", "trade_wrong_league",
    "trade_search_not_found", "trade_no_optimizable_candidates", "trade_unknown_stat"}


class TradeError(Exception):
    def __init__(self, code: str, retry_after: int | None = None):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


class Range(DTO):
    minimum: Number | None = None
    maximum: Number | None = None

    @model_validator(mode="after")
    def bounds(self):
        if self.minimum is None and self.maximum is None or self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("invalid_trade_range")
        return self

    def upstream(self):
        return {k:v for k,v in (("min",self.minimum),("max",self.maximum)) if v is not None}


class TradeStatFilter(Range):
    stat_id: StatID


class PropertyFilter(Range):
    property: Property


class TradeSearchRequest(DTO):
    league: LeagueName = "Forbidden Rites"
    category: Category
    status: Literal["online", "available", "securable", "any"] = "online"
    rarity: Literal["any", "normal", "magic", "rare", "unique", "nonunique"] = "any"
    corrupted: bool | None = None
    price_max: Price | None = None
    required_level_max: Annotated[int, Field(ge=0,le=100)] = 100
    stats: Annotated[list[TradeStatFilter], Field(max_length=12)] = Field(default_factory=list)
    properties: Annotated[list[PropertyFilter], Field(max_length=11)] = Field(default_factory=list)
    max_results: Annotated[int, Field(ge=1,le=50)] = 20

    @model_validator(mode="after")
    def consistent(self):
        unique(self.stats,"stat_id")
        unique(self.properties,"property")
        return self


class TradePageRequest(DTO):
    search_id: SearchID
    offset: Annotated[int, Field(ge=0,le=49)] = 0
    limit: Annotated[int, Field(ge=1,le=5)] = 5


class StatSearchRequest(DTO):
    query: Annotated[str, Field(min_length=1,max_length=80,pattern=r"^[A-Za-z0-9 +#%,'()\-]+$")]
    group: Literal["any", "pseudo", "explicit", "implicit", "rune"] = "pseudo"
    limit: Annotated[int, Field(ge=1,le=10)] = 10
    offset: Annotated[int, Field(ge=0,le=20000)] = 0


class StatEntry(DTO):
    stat_id: StatID
    text: Annotated[str, Field(max_length=240)]


class StatSearchResult(DTO):
    entries: list[StatEntry]
    matched_total: int
    next_offset: int | None


class EquipmentValue(DTO):
    property: Property
    value: Annotated[float, Field(ge=0,le=1e9,allow_inf_nan=False)]


class TradeListing(DTO):
    key: Annotated[str, Field(pattern=r"^i_[0-9a-f]{24}$")]
    listing_ref: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    base_type: Annotated[str, Field(max_length=100)]
    base_type_ko: Annotated[str, Field(max_length=160)] | None = None
    base_type_source_ko: Annotated[str, Field(max_length=1024)] | None = None
    rarity: Literal["normal", "magic", "rare", "unique"]
    corrupted: bool
    required_level: Annotated[int, Field(ge=0,le=100)] | None
    price: Price | None
    price_status: Literal["available", "missing_or_unsupported_currency"]
    observed_at_epoch: int
    listing_indexed_at: Annotated[str, Field(max_length=40)] | None
    item_stats: list[Stat]
    equipment_values: list[EquipmentValue]
    unknown_modifier_count: int
    unscored_modifier_count: int
    optimization_eligible: bool
    character_recalculated: Literal[False] = False
    availability_guaranteed: Literal[False] = False


class TradeSearchResult(DTO):
    search_id: SearchID
    league: LeagueName
    category: Category
    website_url: str
    search_retrieved_at_epoch: int
    total_matches: int
    retained_ids: int
    query_results_fully_retained: bool
    items: list[TradeListing]
    next_offset: int | None
    unavailable_or_unparsed_in_page: int
    direct_website_api: Literal[True] = True
    documented_developer_api: Literal[False] = False


class TradeUpgradeRequest(DTO):
    optimization: OptimizeRequest
    search_ids: Annotated[list[SearchID], Field(min_length=1,max_length=8)]

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.search_ids)) != len(self.search_ids):
            raise ValueError("duplicate_search_id")
        return self


class TradeUpgradeResult(DTO):
    search_ids: list[SearchID]
    baseline_origin: Literal["user_snapshot", "synthetic_example", "trade_snapshot"]
    listings_considered: int
    rejected_for_missing_or_unsupported_data: int
    optimization: UpgradeResult


class Gate:
    """Conservative shared gate, synchronized from every GGG response.

    Across policies we deliberately over-count requests; this can delay calls
    but cannot expand an allowance. Unobserved activity by other apps may still
    cause 429, which is handled without immediate retry.
    """
    def __init__(self, interval=1.0, clock=time.monotonic):
        self.interval, self.clock = interval, clock
        self.until = self.next_at = 0.0
        self.rules = {}

    def delay(self):
        now = self.clock()
        until = max(self.until,self.next_at)
        for key,(used,cap,reset) in list(self.rules.items()):
            if reset <= now:
                del self.rules[key]
            elif used >= cap:
                until = max(until,reset)
        return max(0.0,until-now)

    def consume(self):
        now = self.clock()
        self.next_at = now+self.interval
        for key,(used,cap,reset) in list(self.rules.items()):
            self.rules[key] = (used+1,cap,reset)

    def observe(self, headers: httpx.Headers):
        now = self.clock()
        policy = headers.get("x-rate-limit-policy","default")[:80]
        for rule in headers.get("x-rate-limit-rules","").split(","):
            rule = rule.strip().lower()
            if not rule:
                continue
            definitions = headers.get("x-rate-limit-"+rule,"").split(",")
            states = headers.get("x-rate-limit-"+rule+"-state","").split(",")
            try:
                if len(definitions)!=len(states):
                    raise ValueError()
                for d,s in zip(definitions,states):
                    cap,window,_ = map(int,d.split(":"))
                    used,server_window,blocked = map(int,s.split(":"))
                    if not (1<=cap<=100000 and 1<=window<=86400 and server_window==window and 0<=used<=100000 and 0<=blocked<=86400):
                        raise ValueError()
                    self.rules[(policy,rule,window)] = (used,cap,now+window)
                    self.until = max(self.until,now+blocked)
            except ValueError:
                self.until = max(self.until,now+60)
                raise TradeError("trade_schema_changed") from None
        retry = headers.get("retry-after")
        if retry:
            try:
                seconds = float(retry)
            except ValueError:
                try:
                    seconds = parsedate_to_datetime(retry).timestamp()-time.time()
                except (ValueError,TypeError,OverflowError):
                    seconds = 60
            if not math.isfinite(seconds):
                seconds = 60
            self.until = max(self.until,now+max(0,seconds))


def valid_number(value, lo=0, hi=1e9):
    return type(value) in (int,float) and math.isfinite(value) and lo<=value<=hi


class TradeClient:
    def __init__(self, user_agent: str, transport=None, interval=1.0, clock=time.time):
        self.client = httpx.AsyncClient(headers={"User-Agent":user_agent,"Accept":"application/json"},
            timeout=httpx.Timeout(20), follow_redirects=False, transport=transport)
        self.clock, self.gate, self.lock = clock, Gate(interval), asyncio.Lock()
        self.search_lock = asyncio.Lock()
        self.metadata, self.searches, self.query_cache = {}, OrderedDict(), OrderedDict()
        self.blocked = None

    async def close(self):
        await self.client.aclose()

    async def request(self, method: str, path: str, body=None):
        # All paths are constructed by this module; there is no URL-taking MCP tool.
        async with self.lock:
            if self.blocked:
                raise TradeError(self.blocked)
            for attempt in range(2):
                delay = self.gate.delay()
                if delay > 5:
                    raise TradeError("trade_rate_limited",math.ceil(delay))
                if delay:
                    await asyncio.sleep(delay)
                self.gate.consume()
                try:
                    async with self.client.stream(method,TRADE_API+path,json=body) as response:
                        self.gate.observe(response.headers)
                        if response.status_code in (401,403):
                            self.blocked = "trade_authentication_required" if response.status_code==401 else "trade_interactive_verification_required"
                            raise TradeError(self.blocked)
                        if response.status_code==429:
                            self.gate.until = max(self.gate.until,self.gate.clock()+1)
                            raise TradeError("trade_rate_limited",max(1,math.ceil(self.gate.delay())))
                        if response.status_code==400:
                            raise TradeError("trade_invalid_query")
                        if response.status_code in (500,502,503,504) and attempt==0:
                            continue
                        if response.status_code!=200:
                            raise TradeError("trade_unavailable")
                        if "application/json" not in response.headers.get("content-type","").lower():
                            self.blocked = "trade_interactive_verification_required"
                            raise TradeError(self.blocked)
                        chunks, size = [],0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size>MAX_BYTES:
                                raise TradeError("trade_response_too_large")
                            chunks.append(chunk)
                        try:
                            data = json.loads(b"".join(chunks))
                        except (ValueError,RecursionError):
                            raise TradeError("trade_schema_changed") from None
                        if isinstance(data,dict) and isinstance(data.get("error"),dict):
                            code=data["error"].get("code")
                            if code in (6,8):
                                self.blocked="trade_authentication_required" if code==8 else "trade_interactive_verification_required"
                                raise TradeError(self.blocked)
                            if code==3:
                                self.gate.until=max(self.gate.until,self.gate.clock()+60)
                                raise TradeError("trade_rate_limited",math.ceil(self.gate.delay()))
                            raise TradeError("trade_invalid_query" if code==2 else "trade_unavailable")
                        if not isinstance(data,dict) or "error" in data:
                            raise TradeError("trade_schema_changed")
                        return data
                except httpx.HTTPError:
                    if attempt:
                        raise TradeError("trade_unavailable") from None
            raise TradeError("trade_unavailable")

    async def data(self, name: str):
        if name not in {"leagues","stats","filters"}:
            raise TradeError("trade_unknown_filter")
        entry = self.metadata.get(name)
        if entry and self.clock()-entry[0]<21600:
            return entry[1]
        raw = await self.request("GET","/data/"+name)
        rows = raw.get("result")
        if not isinstance(rows,list):
            raise TradeError("trade_schema_changed")
        self.metadata[name]=(self.clock(),rows)
        return rows

    async def stats(self):
        groups = await self.data("stats")
        rows = [e for g in groups if isinstance(g,dict) for e in g.get("entries",[]) if isinstance(e,dict)]
        return {r["id"]:r["text"] for r in rows if not r.get("option") and isinstance(r.get("id"),str) and re.fullmatch(STAT_ID,r["id"]) and isinstance(r.get("text"),str) and len(r["text"])<=240}

    async def search_stats(self, request: StatSearchRequest):
        rows = await self.stats()
        tokens = request.query.casefold().split()
        matches = sorted((i,t) for i,t in rows.items() if all(s in t.casefold() for s in tokens) and (request.group=="any" or i.startswith(request.group+".")))
        return bounded_dto(StatSearchResult(entries=[StatEntry(stat_id=i,text=t) for i,t in matches[request.offset:request.offset+request.limit]],
            matched_total=len(matches), next_offset=request.offset+request.limit if request.offset+request.limit<len(matches) else None))

    async def query(self, request: TradeSearchRequest):
        leagues = await self.data("leagues")
        if not any(isinstance(l,dict) and l.get("id")==request.league and l.get("realm")=="poe2" for l in leagues):
            raise TradeError("trade_unknown_league")
        groups = await self.data("filters")
        definitions = {g.get("id"):{f.get("id"):f for f in g.get("filters",[]) if isinstance(f,dict)} for g in groups if isinstance(g,dict)}
        def option(group,field,value):
            f = definitions.get(group,{}).get(field)
            options = f.get("option",{}).get("options",[]) if f else []
            if not any(v.get("id")==value for v in options):
                raise TradeError("trade_unknown_filter")
        option("type_filters","category",request.category)
        option("status_filters","status",request.status)
        filters = {"type_filters":{"filters":{"category":{"option":request.category}}},
                   "req_filters":{"filters":{"lvl":{"max":request.required_level_max}}}}
        if "lvl" not in definitions.get("req_filters",{}):
            raise TradeError("trade_unknown_filter")
        if request.rarity!="any":
            option("type_filters","rarity",request.rarity)
            filters["type_filters"]["filters"]["rarity"]={"option":request.rarity}
        if request.corrupted is not None:
            value=str(request.corrupted).lower()
            option("misc_filters","corrupted",value)
            filters["misc_filters"]={"filters":{"corrupted":{"option":value}}}
        if request.price_max:
            option("trade_filters","price",request.price_max.currency)
            filters["trade_filters"]={"filters":{"price":{"option":request.price_max.currency,"max":request.price_max.amount}}}
        if request.properties:
            if any(p.property not in definitions.get("equipment_filters",{}) for p in request.properties):
                raise TradeError("trade_unknown_filter")
            filters["equipment_filters"]={"filters":{p.property:p.upstream() for p in request.properties}}
        known = await self.stats() if request.stats else {}
        if any(s.stat_id not in known for s in request.stats):
            raise TradeError("trade_unknown_stat")
        return {"query":{"status":{"option":request.status},"stats":[{"type":"and","filters":[{"id":s.stat_id,"value":s.upstream()} for s in request.stats]}],"filters":filters},"sort":{"price":"asc"}}

    async def search(self, request: TradeSearchRequest):
        async with self.search_lock:
            return await self._search(request)

    async def _search(self, request: TradeSearchRequest):
        body = await self.query(request)
        cache_key=json.dumps(request.model_dump(),sort_keys=True)
        cached=self.query_cache.get(cache_key)
        if cached and cached in self.searches and self.clock()-self.searches[cached]["created"]<60:
            return await self.page(TradePageRequest(search_id=cached))
        raw = await self.request("POST","/search/"+quote(request.league,safe=""),body)
        query_id, ids, total=raw.get("id"),raw.get("result"),raw.get("total")
        # Current trade2 can return a long URL-safe compressed SEARCH token.
        # Keep it opaque; this is not a PoB payload and must never be decoded.
        if not isinstance(query_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,2048}={0,2}",query_id) or not isinstance(ids,list) or len(ids)>10000 or type(total) is not int or total<0 or total<len(ids) or any(not isinstance(i,str) or not re.fullmatch(r"[0-9a-f]{64}",i) for i in ids) or len(set(ids))!=len(ids):
            raise TradeError("trade_schema_changed")
        search_id="ts_"+secrets.token_hex(16)
        self.searches[search_id]={"created":int(self.clock()),"request":request,"query_id":query_id,"ids":ids[:request.max_results],"total":total,"rows":{},"exhaustive":total==len(ids[:request.max_results]) and not raw.get("inexact",False)}
        self.query_cache[cache_key]=search_id
        while len(self.searches)>64:
            self.searches.popitem(last=False)
        while len(self.query_cache)>64:
            self.query_cache.popitem(last=False)
        return await self.page(TradePageRequest(search_id=search_id))

    def retained(self, search_id):
        entry=self.searches.get(search_id)
        if not entry:
            raise TradeError("trade_search_not_found")
        if self.clock()-entry["created"]>600:
            raise TradeError("trade_search_expired")
        return entry

    async def fetch(self, entry, ids):
        missing=[i for i in ids if i not in entry["rows"]]
        for start in range(0,len(missing),10):
            group=missing[start:start+10]
            raw=await self.request("GET","/fetch/"+",".join(group)+"?query="+quote(entry["query_id"],safe=""))
            rows=raw.get("result")
            if not isinstance(rows,list) or len(rows)>len(group):
                raise TradeError("trade_schema_changed")
            parsed={}
            for row in rows:
                if row is None:
                    continue
                if not isinstance(row,dict) or row.get("id") not in group or row["id"] in parsed:
                    raise TradeError("trade_schema_changed")
                parsed[row["id"]]=parse_listing(row,int(self.clock()))
                # A separate private cache feeds the PoB worker. This data is
                # never part of TradeListing or an MCP response.
                from .engine_protocol import private_trade_item
                try:
                    raw_item=private_trade_item(row["item"])
                    raw_item["id"]=row["id"]
                    entry.setdefault("engine_items",{})[row["id"]]=raw_item
                except Exception:
                    entry.setdefault("engine_items",{}).pop(row["id"],None)
            for i in group:
                entry["rows"][i]=parsed.get(i)

    async def page(self, request: TradePageRequest):
        entry=self.retained(request.search_id)
        ids=entry["ids"][request.offset:request.offset+request.limit]
        await self.fetch(entry,ids)
        for count in range(len(ids),-1,-1):
            selected_ids=ids[:count]
            rows=[entry["rows"][i] for i in selected_ids if entry["rows"][i] is not None]
            result=TradeSearchResult(search_id=request.search_id,league=entry["request"].league,category=entry["request"].category,
                website_url=search_url(entry),search_retrieved_at_epoch=entry["created"],total_matches=entry["total"],retained_ids=len(entry["ids"]),query_results_fully_retained=entry["exhaustive"],
                items=rows,next_offset=request.offset+count if request.offset+count<len(entry["ids"]) else None,unavailable_or_unparsed_in_page=len(selected_ids)-len(rows))
            try:
                return bounded_dto(result)
            except BuildError:
                if count<=1:
                    raise
        raise TradeError("trade_schema_changed")

    async def recommend(self, request: TradeUpgradeRequest, equipment: EquipmentService):
        baseline=equipment.load(request.optimization.dataset_id)
        candidates, seen, considered, rejected=[],set(),0,0
        entries=[self.retained(search_id) for search_id in request.search_ids]
        if any(entry["request"].league!=baseline.league for entry in entries):
            raise TradeError("trade_wrong_league")
        if len({i for entry in entries for i in entry["ids"]})>160:
            raise TradeError("trade_invalid_query")
        for entry in entries:
            await self.fetch(entry,entry["ids"])
            slots=CATEGORY_SLOTS.get(entry["request"].category,[])
            slots=[s for s in slots if s in {c.slot for c in baseline.current}]
            for listing in entry["rows"].values():
                if listing is None:
                    rejected+=1
                    continue
                if listing.listing_ref in seen:
                    continue
                seen.add(listing.listing_ref)
                considered+=1
                if not slots or not listing.optimization_eligible:
                    rejected+=1
                    continue
                candidates.append(Candidate(key=listing.key,eligible_slots=slots,rarity=listing.rarity,corrupted=listing.corrupted,
                    required_level=listing.required_level,stats=listing.item_stats,price=listing.price,observed_at_epoch=listing.observed_at_epoch,
                    listing_ref=listing.listing_ref,source_search_url=None,unscored_modifier_count=listing.unscored_modifier_count))
        if not candidates:
            raise TradeError("trade_no_optimizable_candidates")
        if len(candidates)>160:
            raise TradeError("trade_invalid_query")
        data=Dataset(**{**baseline.model_dump(),"origin":"trade_snapshot","candidates":[c.model_dump() for c in candidates]})
        result=await equipment.optimize_data(data,request.optimization)
        return bounded_dto(TradeUpgradeResult(search_ids=request.search_ids,baseline_origin=baseline.origin,listings_considered=considered,rejected_for_missing_or_unsupported_data=rejected,optimization=result))


CATEGORY_SLOTS={"armour.helmet":["helmet"],"armour.chest":["body_armour"],"armour.gloves":["gloves"],"armour.boots":["boots"],
    "accessory.belt":["belt"],"accessory.amulet":["amulet"],"accessory.ring":["ring_left","ring_right"]}


def search_url(entry):
    return BASE+"/trade2/search/"+quote(entry["request"].league,safe="")+"/"+quote(entry["query_id"],safe="")


SIMPLE_MODS={
    "flat_life":r"([+-]?\d+(?:\.\d+)?) to maximum Life",
    "flat_mana":r"([+-]?\d+(?:\.\d+)?) to maximum Mana",
    "strength":r"([+-]?\d+(?:\.\d+)?) to Strength",
    "dexterity":r"([+-]?\d+(?:\.\d+)?) to Dexterity",
    "intelligence":r"([+-]?\d+(?:\.\d+)?) to Intelligence",
    "fire_resistance":r"([+-]?\d+(?:\.\d+)?)% to Fire Resistance",
    "cold_resistance":r"([+-]?\d+(?:\.\d+)?)% to Cold Resistance",
    "lightning_resistance":r"([+-]?\d+(?:\.\d+)?)% to Lightning Resistance",
    "chaos_resistance":r"([+-]?\d+(?:\.\d+)?)% to Chaos Resistance",
    "movement_speed":r"([+-]?\d+(?:\.\d+)?)% increased Movement Speed",
}


def plain_mod(text):
    # GGG rich-text references: [Resistances|Cold Resistance], [Evasion].
    return re.sub(r"\[([^\[\]|]+)(?:\|([^\[\]]+))?\]",lambda m:m[2] or m[1],text)


def parse_listing(row: dict, observed: int) -> TradeListing | None:
    """Only simple unconditional item mods and explicit extended properties.

    Unknown mod text never crosses MCP. Unknown mechanics disable optimization
    for that item; the listing can still be shown and opened on official trade.
    """
    try:
        item,listing=row["item"],row["listing"]
        if row.get("gone") or not isinstance(item,dict) or not isinstance(listing,dict):
            return None
        ref=row["id"]
        if not isinstance(ref,str) or not re.fullmatch(r"[0-9a-f]{64}",ref):
            return None
        rarity={0:"normal",1:"magic",2:"rare",3:"unique"}.get(item.get("frameType"))
        if rarity is None:
            return None
        base=item.get("baseType",item.get("typeLine",""))
        if not isinstance(base,str) or len(base)>100 or any(ord(c)<32 for c in base):
            return None
        p=listing.get("price") or {}
        price=Price(amount=float(p["amount"]),currency=p["currency"]) if valid_number(p.get("amount"),0.000000001,1e9) and p.get("currency") in {"exalted","chaos","divine"} else None
        indexed=listing.get("indexed")
        if not isinstance(indexed,str) or len(indexed)>40:
            indexed=None
        else:
            try:
                datetime.fromisoformat(indexed.replace("Z","+00:00"))
            except ValueError:
                indexed=None
        level=None
        for r in item.get("requirements",[]):
            if r.get("name")=="Level" and len(r.get("values",[]))==1:
                text=r["values"][0][0]
                if isinstance(text,str) and re.fullmatch(r"\d{1,3}",text) and 0<=int(text)<=100:
                    level=int(text)
        values={k:0.0 for k in SIMPLE_MODS}
        unknown=unscored=0
        for field in ("implicitMods","explicitMods","craftedMods","enchantMods","runeMods","fracturedMods","desecratedMods","mutatedMods"):
            mods=item.get(field,[])
            if not isinstance(mods,list) or len(mods)>100:
                return None
            for mod in mods:
                text=mod if isinstance(mod,str) else mod.get("description") if isinstance(mod,dict) else None
                if not isinstance(text,str) or len(text)>1000:
                    unknown+=1
                    continue
                text=plain_mod(text)
                matched=False
                for metric,pattern in SIMPLE_MODS.items():
                    m=re.fullmatch(pattern,text)
                    if m:
                        values[metric]+=float(m[1]);matched=True;break
                if matched:
                    continue
                m=re.fullmatch(r"([+-]?\d+)% to all Elemental Resistances",text)
                if m:
                    for k in ("fire_resistance","cold_resistance","lightning_resistance"):
                        values[k]+=int(m[1])
                    continue
                m=re.fullmatch(r"([+-]?\d+) to all Attributes",text)
                if m:
                    for k in ("strength","dexterity","intelligence"):
                        values[k]+=int(m[1])
                    continue
                # Local defence mods are already included in the extended value.
                if re.fullmatch(r"[+]?[0-9]+(?:% increased| to) (?:Armour|Evasion(?: Rating)?|maximum Energy Shield|Energy Shield)(?: and (?:Armour|Evasion(?: Rating)?|Energy Shield))?",text):
                    continue
                m=re.fullmatch(r"([+-]?\d+)% to (Fire|Cold|Lightning|Chaos) and (Fire|Cold|Lightning|Chaos) Resistances",text)
                if m:
                    values[m[2].lower()+"_resistance"]+=int(m[1])
                    values[m[3].lower()+"_resistance"]+=int(m[1])
                    continue
                if re.fullmatch(r"\d+(?:\.\d+)?% (?:increased|reduced) (?:Rarity of Items found|Critical Hit Chance|Stun Threshold|Stun Buildup|Light Radius|Attribute Requirements|Mana Regeneration Rate|Life Regeneration Rate)",text) or re.fullmatch(r"[+]?\d+ to Accuracy Rating",text):
                    # Known unconditional modifiers outside this scoring model.
                    # Count them explicitly; never call the score a whole-build gain.
                    unscored+=1
                    continue
                unknown+=1
        props=[]
        extended=item.get("extended") or {}
        if not isinstance(extended,dict):
            return None
        for key in Property.__args__:
            if valid_number(extended.get(key)):
                props.append(EquipmentValue(property=key,value=float(extended[key])))
        for key,metric in (("ar","item_armour"),("ev","item_evasion"),("es","item_energy_shield")):
            if valid_number(extended.get(key),0,1e7):
                values[metric]=float(extended[key])
        # Non-identified items and alternate effect-bearing components require a
        # broader semantic evaluator even if the few visible lines look simple.
        complete=item.get("identified") is True and not unknown and rarity!="unique" and not any(item.get(k) for k in ("grantedSkills","socketedItems","veiledMods","sanctified","mirrored"))
        return TradeListing(key="i_"+hashlib.sha256(ref.encode()).hexdigest()[:24],listing_ref=ref,base_type=base,**name_fields(base, "base_type"),rarity=rarity,corrupted=item.get("corrupted",False),required_level=level,
            price=price,price_status="available" if price else "missing_or_unsupported_currency",observed_at_epoch=observed,listing_indexed_at=indexed,
            item_stats=[Stat(metric=k,value=v) for k,v in values.items()] if complete else [],equipment_values=props,unknown_modifier_count=unknown,unscored_modifier_count=unscored,
            optimization_eligible=complete and price is not None and level is not None)
    except (KeyError,TypeError,ValueError,IndexError,AttributeError):
        return None
