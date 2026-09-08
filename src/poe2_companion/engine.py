"""MCP-side numeric client. No PoB file decoding or filesystem import here."""
from __future__ import annotations
import asyncio
import itertools
import json
import time
from decimal import Decimal
from pathlib import Path
from datetime import datetime
import httpx

from .builds import bounded_dto, PlayerStat, MAX_TOOL_JSON_BYTES
from .engine_models import (ENGINE_COMMIT, ENGINE_DATA_COMMIT, ENGINE_COMPATIBILITY, EngineError, SAFE_ENGINE_ERRORS, EngineStatus, EngineRequest, CompareRequest,
    EngineCalculation, EngineTradeRequest, EngineTradeResult, TradeChange)
from .engine_protocol import WorkerRequest, WorkerResult, private_trade_item
from .trade import TradeError, CATEGORY_SLOTS
from .equipment import EquipmentService


def deltas(before,after):
    b={s.name:s.value for s in before.stats}
    return [PlayerStat(name=s.name,value=s.value-b[s.name]) for s in after.stats if s.name in b]


def calculation_context(request):
    fields=list(request.configuration.model_dump(exclude_none=True)) if request.configuration else []
    return {'scope':'explicit_configuration_active_weapon_set' if fields else 'saved_configuration_active_weapon_set',
            'configuration_fields':fields}


def bounded_engine_dto(value):
    """Preserve stats/status/counts while bounding repeated diagnostic details."""
    value=value.model_copy(deep=True)
    calculation=value.calculation if isinstance(value,EngineTradeResult) else value
    snapshots=[calculation.baseline]+([calculation.result] if calculation.result else [])
    while len(value.model_dump_json().encode('utf-8'))>MAX_TOOL_JSON_BYTES:
        candidates=[s for s in snapshots if s.issues]
        if not candidates:
            candidates=[s for s in snapshots if s.mechanics]
            if not candidates:
                candidates=[s for s in snapshots if s.combat_scenario is not None]
                if not candidates:
                    candidates=[s for s in snapshots if s.selected_skill and
                                (s.selected_skill.name_ko or s.selected_skill.name_source_ko)]
                    if candidates:
                        snapshot=max(candidates,key=lambda s:len(s.selected_skill.model_dump_json()))
                        snapshot.selected_skill.name_ko=None
                        snapshot.selected_skill.name_source_ko=None
                        snapshot.selected_skill_labels_truncated=True
                        continue
                    candidates=[s for s in snapshots if s.selected_skill and s.selected_skill.gem_name]
                    if candidates:
                        snapshot=max(candidates,key=lambda s:len(s.selected_skill.gem_name))
                        snapshot.selected_skill.gem_name=None
                        snapshot.selected_skill_labels_truncated=True
                        continue
                    candidates=[s for s in snapshots if s.selected_skill and s.selected_skill.name]
                    if candidates:
                        snapshot=max(candidates,key=lambda s:len(s.selected_skill.name.encode('utf-8')))
                        snapshot.selected_skill.name=None
                        snapshot.selected_skill_labels_truncated=True
                        continue
                    return bounded_dto(value)
                snapshot=max(candidates,key=lambda s:len(s.combat_scenario.model_dump_json()))
                snapshot.combat_scenario_status=snapshot.combat_scenario.status
                snapshot.combat_scenario=None
                snapshot.combat_scenario_truncated=True
                continue
            snapshot=max(candidates,key=lambda s:len(s.mechanics))
            snapshot.mechanics.pop()
            snapshot.mechanics_truncated=True
            continue
        snapshot=max(candidates,key=lambda s:len(s.issues))
        snapshot.issues.pop()
        snapshot.issues_truncated=True
    return bounded_dto(value)


class EngineClient:
    def __init__(self, socket: str, *, http=None):
        self.http=http or httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=socket),base_url='http://pob-worker',
                                           timeout=90,trust_env=False,follow_redirects=False)
        self.lock=asyncio.Lock()

    async def close(self):
        await self.http.aclose()

    async def status(self):
        try:
            r=await self.http.get('/health')
            available=r.status_code==200 and r.json()=={'engine_commit':ENGINE_COMMIT,
                'engine_data_commit':ENGINE_DATA_COMMIT,'engine_compatibility':ENGINE_COMPATIBILITY}
        except Exception:
            available=False
        return EngineStatus(enabled=True,reachable=available)

    async def batch(self, request: WorkerRequest):
        # Prevent an agent spawning concurrent expensive PoB calculations.
        if self.lock.locked():
            raise EngineError('engine_busy')
        async with self.lock:
            try:
                async with self.http.stream('POST','/batch',content=request.model_dump_json(exclude_none=True),headers={'content-type':'application/json'}) as r:
                    data=bytearray()
                    async for chunk in r.aiter_bytes():
                        data.extend(chunk)
                        if len(data)>512*1024:
                            raise EngineError('engine_protocol_error')
                    if r.status_code!=200:
                        code=json.loads(data).get('code')
                        raise EngineError(code if code in SAFE_ENGINE_ERRORS else 'engine_unavailable')
                    payload=json.loads(data)
                    if not isinstance(payload,dict):
                        raise EngineError('engine_protocol_error')
                    # Never default an old worker's missing provenance to the
                    # new server's pins, even if status() was not called first.
                    expected={'engine_commit':ENGINE_COMMIT,'engine_data_commit':ENGINE_DATA_COMMIT,
                              'engine_compatibility':ENGINE_COMPATIBILITY}
                    if any(payload.get(key)!=pin for key,pin in expected.items()):
                        raise EngineError('engine_version_mismatch')
                    result=WorkerResult.model_validate(payload)
                    if len(result.results)!=len(request.scenarios):
                        raise EngineError('engine_protocol_error')
                    return result
            except httpx.TimeoutException:
                raise EngineError('engine_timeout') from None
            except EngineError:
                raise
            except Exception:
                raise EngineError('engine_unavailable') from None

    async def calculate(self, request: EngineRequest | CompareRequest):
        scenarios=[[v.model_dump() for v in request.replacements]] if isinstance(request,CompareRequest) else []
        result=await self.batch(WorkerRequest(build_id=request.build_id,scenarios=scenarios,
            configuration=request.configuration,combat_scenario=request.combat_scenario))
        after=result.results[0] if result.results else None
        return bounded_engine_dto(EngineCalculation(build_id=request.build_id,calculated_at_epoch=int(time.time()),baseline=result.baseline,
            result=after,deltas=deltas(result.baseline,after) if after else [],**calculation_context(request)))

    async def recommend(self, request: EngineTradeRequest, trade, scout):
        entries=[trade.retained(s) for s in request.search_ids]
        if any(e['request'].league!=request.league for e in entries):
            raise TradeError('trade_wrong_league')
        retained={i for e in entries for i in e['ids']}
        refs=set(request.candidate_refs) if request.candidate_refs is not None else retained
        if not refs<=retained:
            raise EngineError('engine_unknown_candidate')
        if len(refs)>32:
            raise EngineError('engine_candidate_space_too_large')
        candidates=[];seen=set();excluded=0
        for entry in entries:
            ids=[i for i in entry['ids'] if i in refs]
            await trade.fetch(entry,ids)
            category=entry['request'].category
            slots=CATEGORY_SLOTS.get(category,[])
            if category.startswith('weapon.'):
                slots=['weapon_main','weapon_off'] # PoB validates actual subtype/hand/keystone.
            elif category in {'armour.shield','armour.focus','armour.buckler','armour.quiver'}:
                slots=['weapon_off']
            for ref in ids:
                if ref in seen:
                    continue
                seen.add(ref)
                row=entry['rows'].get(ref)
                raw=entry.get('engine_items',{}).get(ref)
                if not row or not raw or not slots or not row.price or time.time()-row.observed_at_epoch>request.max_listing_age_seconds:
                    excluded+=1;continue
                try:
                    raw=private_trade_item(raw)
                except EngineError:
                    excluded+=1;continue
                candidates.append((ref,slots,raw,row.price))
        if not candidates:
            raise EngineError('engine_no_candidates')
        fxservice=EquipmentService(Path('/unused'),scout)
        try:
            fx=await fxservice.fx(request.league,{c[3].currency for c in candidates},request.budget.currency)
        except Exception:
            raise EngineError('engine_currency_unavailable') from None
        budget=Decimal(str(request.budget.amount))
        spend=budget*(Decimal(100)-Decimal(str(request.reserve_percent)))/Decimal(100)
        pool={}
        for ref,slots,raw,price in candidates:
            cost=Decimal(str(price.amount))*Decimal(str(fx.rates[price.currency]))
            if cost>spend:
                excluded+=1;continue
            for slot in slots:
                pool.setdefault(slot,[]).append((ref,raw,cost))
        # Enumerate the complete retained candidate set; include keeping gear.
        # Reject excess work before any PoB run, with no silent proxy pruning.
        plans=[([],Decimal(0),[])]
        for n in range(1,min(request.max_changes,len(pool))+1):
            for chosen in itertools.combinations(sorted(pool),n):
                for combination in itertools.product(*(pool[s] for s in chosen)):
                    ids=[c[0] for c in combination]
                    if len(ids)!=len(set(ids)):
                        continue
                    cost=sum((c[2] for c in combination),Decimal(0))
                    if cost>spend:
                        continue
                    changes=[{'slot':slot,'item':v[1]} for slot,v in zip(chosen,combination)]
                    public=[TradeChange(slot=slot,listing_ref=v[0]) for slot,v in zip(chosen,combination)]
                    plans.append((changes,cost,public))
                    if len(plans)>64:
                        raise EngineError('engine_candidate_space_too_large')
        result=await self.batch(WorkerRequest(build_id=request.build_id,scenarios=[p[0] for p in plans[1:]],
            configuration=request.configuration,combat_scenario=request.combat_scenario))
        snapshots=[result.baseline,*result.results]
        need={w.stat for w in request.weights}|{c.stat for c in request.constraints}
        def values(snapshot):
            return {s.name:s.value for s in snapshot.stats}
        baseline=values(result.baseline)
        if not need<=baseline.keys():
            raise EngineError('engine_missing_metric')
        def score(v):
            return sum((min(v[w.stat],w.cap) if w.cap is not None else v[w.stat])*w.weight for w in request.weights)
        base_score=score(baseline)
        eligible=[];failed=unknown=0
        for i,(snapshot,plan) in enumerate(zip(snapshots,plans)):
            v=values(snapshot)
            if snapshot.validation=='fail':
                failed+=1;continue
            if result.baseline.validation!='pass' or snapshot.validation!='pass' or not need<=v.keys():
                unknown+=1;continue
            if any(v[c.stat]<c.minimum for c in request.constraints):
                continue
            gain=score(v)-base_score
            eligible.append((i,gain))
        if eligible:
            best,gain=min(eligible,key=lambda v:(-v[1],plans[v[0]][1],len(plans[v[0]][2]),v[0]) if request.mode=='maximize_score'
                          else (plans[v[0]][1],-v[1],len(plans[v[0]][2]),v[0]))
        else:
            best,gain=0,0.0
        snapshot,cost,changes=snapshots[best],plans[best][1],plans[best][2]
        calc=EngineCalculation(build_id=request.build_id,calculated_at_epoch=int(time.time()),baseline=result.baseline,
            result=snapshot if best else None,deltas=deltas(result.baseline,snapshot) if best else [],**calculation_context(request))
        # Return just the best plan; all bounded combinations were still evaluated.
        return bounded_engine_dto(EngineTradeResult(calculation=calc,changes=changes,cost=float(cost),currency=request.budget.currency,
            remaining_budget=float(budget-cost),score_gain=float(gain),feasible=bool(eligible),evaluated_combinations=len(plans),
            failed_requirements=failed,indeterminate_combinations=unknown,excluded_listings=excluded,
            fx_retrieved_at_epoch=int(datetime.fromisoformat(fx.retrieved_at.replace('Z','+00:00')).timestamp()) if fx.retrieved_at else None))
