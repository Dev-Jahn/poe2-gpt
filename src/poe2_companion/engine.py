"""MCP-side numeric client. No PoB file decoding or filesystem import here."""
from __future__ import annotations
import asyncio
import json
import time
from typing import cast
from decimal import Decimal
from pathlib import Path
from datetime import datetime
import httpx

from .builds import bounded_dto, PlayerStat, MAX_TOOL_JSON_BYTES
from .engine_models import (ENGINE_COMMIT, ENGINE_DATA_COMMIT, ENGINE_COMPATIBILITY, EngineError, SAFE_ENGINE_ERRORS, EngineStatus, EngineRequest, CompareRequest,
    EngineCalculation, EngineTradeRequest, EngineTradeResult, TradeChange, EngineSlot)
from .engine_protocol import WorkerRequest, WorkerResult, private_trade_item
from .trade import TradeError, CATEGORY_SLOTS
from .equipment import EquipmentService
from .diagnostics import CalculationReceipts, CandidateEvaluation, ConstraintViolation, ExcludedListing, ExclusionReason
from .recommendation import Option, enumerate_plans
from .engine_protocol import WorkerChange
from .scout import ScoutError


async def verify_character_league(origin, requested, declared, scout):
    if origin is None:
        if declared != requested:
            raise EngineError('character_league_unverified')
        return
    if scout is None:
        raise EngineError('character_league_unverified')
    try:
        league = await scout.league(requested)
    except ScoutError:
        raise EngineError('character_league_unverified') from None
    # Use the catalog's explicit name/slug pair. Slug spelling cannot safely
    # be guessed: historical leagues and hardcore variants use abbreviations.
    if (league.value != requested or origin.league_slug != league.short_name
            or origin.league_name not in (None, league.value, league.short_name)):
        raise EngineError('character_league_mismatch')


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
    primary={'Life','LifeUnreserved','Mana','ManaUnreserved','EnergyShield','Armour','Evasion','DeflectionRating','FireResist','ColdResist','LightningResist','ChaosResist','BlockChance','SpellBlockChance','Str','Dex','Int','TotalDPS','CombinedDPS','FullDPS','Speed','CritChance','CritMultiplier','MinionTotalDPS','MinionCombinedDPS','MinionSpeed'}
    primary.update(calculation.requested_metrics)
    while len(value.model_dump_json().encode('utf-8'))>MAX_TOOL_JSON_BYTES:
        expanded=[s for s in snapshots if any(v.name not in primary for v in s.stats)]
        if expanded:
            snapshot=max(expanded,key=lambda s:len(s.stats))
            snapshot.stat_count=snapshot.stat_count or len(snapshot.stats)
            index=next(i for i in range(len(snapshot.stats)-1,-1,-1) if snapshot.stats[i].name not in primary)
            snapshot.stats.pop(index);snapshot.stats_truncated=True
            continue
        optional_deltas=[i for i,v in enumerate(calculation.deltas) if v.name not in primary]
        if optional_deltas:
            calculation.deltas.pop(optional_deltas[-1]);calculation.deltas_truncated=True
            continue
        coverage=[s for s in snapshots if s.metric_coverage]
        if coverage:
            snapshot=max(coverage,key=lambda s:len(s.metric_coverage))
            snapshot.metric_coverage.pop()
            snapshot.metric_coverage_truncated=True
            continue
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
                    # Dense requests prioritize every requested metric. Other
                    # core values remain losslessly available in receipt pages.
                    essential=set(calculation.requested_metrics)|{'Life','Mana','EnergyShield','FullDPS','TotalDPS','CombinedDPS'}
                    optional=[s for s in snapshots if any(v.name not in essential for v in s.stats)]
                    if optional:
                        snapshot=max(optional,key=lambda s:len(s.stats))
                        snapshot.stat_count=snapshot.stat_count or len(snapshot.stats)
                        index=next(i for i in range(len(snapshot.stats)-1,-1,-1) if snapshot.stats[i].name not in essential)
                        snapshot.stats.pop(index);snapshot.stats_truncated=True
                        continue
                    optional_delta=next((i for i in range(len(calculation.deltas)-1,-1,-1) if calculation.deltas[i].name not in essential),None)
                    if optional_delta is not None:
                        calculation.deltas.pop(optional_delta);calculation.deltas_truncated=True
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
        self.receipts=CalculationReceipts()

    async def close(self):
        await self.http.aclose()

    async def inspect(self, request):
        result = await self.batch(WorkerRequest(build_id=request.build_id,
            configuration=request.configuration, inspection=request))
        page = result.inspection
        if page is None:
            raise EngineError('engine_protocol_error')
        while len(page.model_dump_json(exclude_none=True).encode()) > MAX_TOOL_JSON_BYTES and len(page.records) > 1:
            page.records.pop()
            page.next_offset = request.offset + len(page.records)
        if len(page.model_dump_json(exclude_none=True).encode()) > MAX_TOOL_JSON_BYTES:
            raise EngineError('engine_protocol_error')
        return page

    async def equipment(self, build_id, slot=None, saved_item_id=None, offset=0, limit=5):
        from .inspection import InspectionRequest
        return await self.inspect(InspectionRequest(build_id=build_id,section='equipment',
            slot=slot,saved_item_id=saved_item_id,offset=offset,limit=limit))

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
                        if len(data)>16*1024*1024:
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
        result=await self.batch(WorkerRequest.model_validate(dict(build_id=request.build_id,scenarios=scenarios,
            configuration=request.configuration,combat_scenario=request.combat_scenario)))
        after=result.results[0] if result.results else None
        calculation=EngineCalculation(build_id=request.build_id,calculated_at_epoch=int(time.time()),baseline=result.baseline,
            result=after,deltas=deltas(result.baseline,after) if after else [],**calculation_context(request))
        return bounded_engine_dto(self.receipts.retain(calculation, request))

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
        # Resolve occupied slots from the same immutable build/configuration.
        # Empty-slot removals are no-ops and must not consume the plan budget.
        initial=await self.batch(WorkerRequest(build_id=request.build_id,
            configuration=request.configuration,combat_scenario=request.combat_scenario))
        await verify_character_league(initial.baseline.origin, request.league, request.declared_character_league, scout)
        occupied={item.slot for item in initial.baseline.equipped}
        removable=occupied if request.unequip_slots is None else occupied & set(request.unequip_slots)
        candidates=[];seen=set();exclusions=[]
        for entry in entries:
            ids=[i for i in entry['ids'] if i in refs]
            await trade.fetch(entry,ids)
            category=entry['request'].category
            slots: list[EngineSlot]=[cast(EngineSlot,s) for s in CATEGORY_SLOTS.get(category,[])]
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
                reason: ExclusionReason | None = ('unavailable_or_unparsed' if not row else
                    'private_item_unavailable' if not raw else 'unsupported_slot' if not slots else
                    'missing_price' if not row.price else
                    'stale' if time.time()-row.observed_at_epoch>request.max_listing_age_seconds else None)
                if reason is not None:
                    exclusions.append(ExcludedListing(listing_ref=ref,reason=reason,
                        original_price=row.price if row else None))
                    continue
                try:
                    raw=private_trade_item(raw)
                except EngineError:
                    exclusions.append(ExcludedListing(listing_ref=ref,reason='private_import_rejected',original_price=row.price))
                    continue
                candidates.append((ref,slots,raw,row.price))
        fxservice=EquipmentService(Path('/unused'),scout)
        try:
            fx=await fxservice.fx(request.league,{c[3].currency for c in candidates},request.budget.currency)
        except Exception:
            raise EngineError('engine_currency_unavailable') from None
        budget=Decimal(str(request.budget.amount))
        spend=budget*(Decimal(100)-Decimal(str(request.reserve_percent)))/Decimal(100)
        pool: dict[EngineSlot,list[Option]]={}
        for ref,slots,raw,price in candidates:
            cost=Decimal(str(price.amount))*Decimal(str(fx.rates[price.currency]))
            if cost>spend:
                exclusions.append(ExcludedListing(listing_ref=ref,reason='over_budget',original_price=price,normalized_cost=float(cost)))
                continue
            for slot in slots:
                pool.setdefault(slot,[]).append(Option(WorkerChange(slot=slot,item=raw),
                    TradeChange(slot=slot,listing_ref=ref,normalized_cost=float(cost),original_price=price),cost))
        plans=enumerate_plans(pool,removable,request.max_changes,spend)
        result=(await self.batch(WorkerRequest(build_id=request.build_id,scenarios=[p.changes for p in plans[1:]],
            configuration=request.configuration,combat_scenario=request.combat_scenario))) if len(plans)>1 else initial
        snapshots=[result.baseline,*result.results]
        origin=result.baseline.origin
        await verify_character_league(origin, request.league, request.declared_character_league, scout)
        need={w.stat for w in request.weights}|{c.stat for c in request.constraints}
        def values(snapshot):
            return {s.name:s.value for s in snapshot.stats}
        baseline=values(result.baseline)
        if request.mode!='restore_validity' and not need<=baseline.keys():
            raise EngineError('engine_missing_metric')
        def score(v):
            return sum((min(v[w.stat],w.cap) if w.cap is not None else v[w.stat])*w.weight for w in request.weights)
        base_score=score(baseline) if request.mode!='restore_validity' else 0.0
        def covered(snapshot):
            if snapshot.metric_coverage:
                verified={c.stat for c in snapshot.metric_coverage if c.status=='pass'}
                return need <= verified
            return snapshot.validation=='pass'
        repair=request.mode=='restore_validity'
        eligible=[];failed=unknown=0;evaluations=[]
        for i,(snapshot,plan) in enumerate(zip(snapshots,plans)):
            v=values(snapshot)
            evaluation=CandidateEvaluation(index=i,status='eligible',cost=float(plan.cost),changes=plan.public,
                constraint_violations=[ConstraintViolation(stat=c.stat,minimum=c.minimum,actual=v[c.stat])
                    for c in request.constraints if c.stat in v and v[c.stat]<c.minimum])
            evaluations.append(evaluation)
            if (snapshot.equipment_validity or snapshot.validation)=='fail':
                evaluation.status='invalid_equipment'
                failed+=1;continue
            if (snapshot.equipment_validity or snapshot.validation)!='pass' or not covered(snapshot) or (not repair and not covered(result.baseline)) or not need<=v.keys():
                evaluation.status='unresolved_dependencies';unknown+=1;continue
            if any(v[c.stat]<c.minimum for c in request.constraints):
                evaluation.status='constraints_not_met'
                continue
            gain=0.0 if repair else score(v)-base_score
            evaluation.score_gain=gain
            eligible.append((i,gain))
        if eligible:
            ranked=sorted(eligible,key=lambda v:(-v[1],plans[v[0]].cost,len(plans[v[0]].public),v[0]) if request.mode=='maximize_score'
                          else (plans[v[0]].cost,-v[1],len(plans[v[0]].public),v[0]))
            best,gain=ranked[0]
            for rank,(index,_) in enumerate(ranked,1):
                evaluations[index].rank=rank
                evaluations[index].selected=index==best
        else:
            best,gain=0,0.0
        snapshot,cost,best_changes=snapshots[best],plans[best].cost,plans[best].public
        calc=EngineCalculation(build_id=request.build_id,calculated_at_epoch=int(time.time()),baseline=result.baseline,
            result=snapshot if best else None,deltas=deltas(result.baseline,snapshot) if best and not repair else [],
            character_league_verified=origin is not None,league_match='verified' if origin else 'user_declared',requested_metrics=sorted(need),**calculation_context(request))
        self.receipts.retain(calc, request, snapshots, evaluations, exclusions, fx)
        # Return just the best plan; all bounded combinations were still evaluated.
        return bounded_engine_dto(EngineTradeResult(calculation=calc,changes=best_changes,cost=float(cost),currency=request.budget.currency,
            objective=request.mode,baseline_comparison_valid=not repair,
            remaining_budget=float(budget-cost),score_gain=float(gain),feasible=bool(eligible),evaluated_combinations=len(plans),
            failed_requirements=failed,indeterminate_combinations=unknown,excluded_listings=len(exclusions),
            fx_retrieved_at_epoch=int(datetime.fromisoformat(fx.retrieved_at.replace('Z','+00:00')).timestamp()) if fx.retrieved_at else None))
