import itertools
import json
import random
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from poe2_companion.builds import BuildError
from poe2_companion.equipment import (DatasetRequest, EquipmentInput, EquipmentService, OptimizeRequest,
    SearchPlanRequest, SnapshotQuery, prepare_search)
from poe2_companion.equipment_io import import_equipment
from poe2_companion.scout import Scout
from test_scout import Backend

NOW=1788700000


def stats(life,fire=30):
    return [{"metric":"flat_life","value":life},{"metric":"fire_resistance","value":fire}]


def candidate(key,life,fire,price):
    return {"key":key,"eligible_slots":["ring_left","ring_right"],"stats":stats(life,fire),
        "price":{"amount":price,"currency":"exalted"},"observed_at_epoch":NOW}


def example():
    return {"league":"Forbidden Rites","origin":"synthetic_example",
        "current":[{"key":"old_left","slot":"ring_left","stats":stats(50)},
                   {"key":"old_right","slot":"ring_right","stats":stats(50)}],
        "candidates":[candidate("life_ring",120,0,10),candidate("resist_ring",60,60,12),candidate("balanced_ring",90,30,9)]}


def imported(tmp_path,payload=None):
    source=tmp_path/"input.json"
    source.write_text(json.dumps(example() if payload is None else payload))
    directory=tmp_path/"equipment"
    return import_equipment(source,directory,clock=lambda:NOW),directory


def optimizer(dataset_id,**kwargs):
    return OptimizeRequest.model_validate({"dataset_id":dataset_id,"budget":{"amount":22,"currency":"exalted"},
        "weights":[{"metric":"flat_life","weight":1}],"constraints":[{"metric":"fire_resistance","minimum_total":60}],**kwargs})


@pytest.fixture
def scout():
    client=Scout(user_agent="test",transport=httpx.MockTransport(Backend()),interval=0)
    return client


async def test_combinations_restore_resistance_and_choose_global_best(tmp_path,scout):
    key,directory=imported(tmp_path)
    service=EquipmentService(directory,scout,clock=lambda:NOW)
    try:
        result=await service.optimize(optimizer(key))
        best=result.plans[0]
        assert best.cost==22 and best.score_gain==80
        assert {x.candidate_key for x in best.changes}=={"life_ring","resist_ring"}
        assert {x.metric:x.value for x in best.item_totals}=={"flat_life":180,"fire_resistance":60}
        single=await service.optimize(optimizer(key,max_changes=1))
        assert single.plans[0].cost==9 and single.plans[0].score_gain==40
        assert result.exact_within_eligible_candidates and not result.character_recalculated
    finally:
        await scout.close()


async def test_minimum_cost_target_and_infeasible_budget(tmp_path,scout):
    key,directory=imported(tmp_path)
    service=EquipmentService(directory,scout,clock=lambda:NOW)
    constraints=[{"metric":"flat_life","minimum_gain":60},{"metric":"fire_resistance","minimum_total":60}]
    try:
        result=await service.optimize(optimizer(key,mode="minimize_cost",constraints=constraints))
        assert result.plans[0].cost==22
        result=await service.optimize(optimizer(key,mode="minimize_cost",constraints=constraints,budget={"amount":21,"currency":"exalted"}))
        assert result.plans==[] and result.feasible_combinations==0
    finally:
        await scout.close()


async def test_unique_physical_ring_reserve_and_keep_option(tmp_path,scout):
    data=example();data["candidates"]=data["candidates"][:1]
    key,directory=imported(tmp_path,data)
    service=EquipmentService(directory,scout,clock=lambda:NOW)
    try:
        result=await service.optimize(optimizer(key,constraints=[]))
        assert result.plans[0].score_gain==70 and len(result.plans[0].changes)==1
        assert len({v.candidate_key for v in result.plans[0].changes})==1
        kept=await service.optimize(optimizer(key,max_changes=0))
        assert kept.plans[0].no_change and kept.plans[0].cost==0
        reserved=await service.optimize(optimizer(key,constraints=[],reserve_percent=60))
        assert reserved.budget_available==8.8 and reserved.plans[0].no_change
    finally:
        await scout.close()


async def test_missing_and_stale_values_never_become_zero(tmp_path,scout):
    data=example()
    data["candidates"][0]["price"]=None
    data["candidates"][1]["observed_at_epoch"]=NOW-4000
    data["candidates"][2]["stats"]=stats(90)[:1]
    key,directory=imported(tmp_path,data)
    service=EquipmentService(directory,scout,clock=lambda:NOW)
    try:
        result=await service.optimize(optimizer(key))
        assert result.excluded_counts=={"missing_price":1,"stale":1,"missing_metrics":1}
        assert result.plans[0].no_change
        path=directory/(key+".json")
        stored=json.loads(path.read_text());stored["current"][0]["stats"]=[]
        path.write_text(json.dumps(stored))
        with pytest.raises(BuildError,match="current_equipment_metrics_incomplete"):
            await service.optimize(optimizer(key))
    finally:
        await scout.close()


async def test_filters_paging_and_scout_currency_conversion(tmp_path,scout):
    data=example();data["candidates"][0]["price"]={"amount":0.1,"currency":"divine"}
    key,directory=imported(tmp_path,data)
    service=EquipmentService(directory,scout,clock=lambda:NOW)
    try:
        request=SnapshotQuery.model_validate({"dataset_id":key,"filters":{"slot":"ring_left","stats":[{"metric":"flat_life","minimum":80}]},"limit":1})
        result=await service.search(request)
        assert result.matched_total==2 and result.next_offset==1
        assert result.items[0].key=="life_ring"
        assert result.fx.source=="poe2scout_reference_currencies" and result.fx.retrieved_at
        expected=json.loads((Path(__file__).parent/"fixtures/references.json").read_text())[2]["RelativePrice"]*0.1
        assert result.items[0].normalized_price==pytest.approx(expected)
        second=await service.search(request.model_copy(update={"offset":1}))
        assert second.items[0].key=="balanced_ring" and second.next_offset is None
    finally:
        await scout.close()


async def test_exact_optimizer_matches_independent_bruteforce(tmp_path,scout):
    rng=random.Random(314159)
    try:
        for _ in range(20):
            data=example()
            for c in data["candidates"]:
                c["stats"]=stats(rng.randrange(20,180),rng.randrange(0,80))
                c["price"]["amount"]=rng.randrange(1,20)
            key,directory=imported(tmp_path,data)
            service=EquipmentService(directory,scout,clock=lambda:NOW)
            result=await service.optimize(optimizer(key,top_k=1))
            oracle=[]
            for left,right in itertools.product([None,*range(3)],repeat=2):
                if left is not None and left==right:
                    continue
                picked=[data["current"][i] if v is None else data["candidates"][v] for i,v in enumerate([left,right])]
                life=sum(p["stats"][0]["value"] for p in picked)
                fire=sum(p["stats"][1]["value"] for p in picked)
                cost=sum(p.get("price",{}).get("amount",0) for p in picked)
                if fire>=60 and cost<=22:
                    oracle.append((-(life-100),cost))
            expected=min(oracle)
            assert (-result.plans[0].score_gain,result.plans[0].cost)==expected
    finally:
        await scout.close()


async def test_large_search_space_rejected_without_silent_pruning(tmp_path,scout,monkeypatch):
    key,directory=imported(tmp_path)
    monkeypatch.setattr("poe2_companion.equipment.MAX_COMBINATIONS",2)
    try:
        with pytest.raises(BuildError,match="candidate_space_too_large"):
            await EquipmentService(directory,scout,clock=lambda:NOW).optimize(optimizer(key))
    finally:
        await scout.close()


@pytest.mark.parametrize("change",["extra_payload","duplicate_listing","wrong_league_url","future_observation"])
def test_import_rejects_poisoned_or_inconsistent_snapshots(tmp_path,change):
    data=example()
    if change=="extra_payload":data["pob_code"]="PRIVATE_CODE_DO_NOT_ECHO"
    elif change=="duplicate_listing":
        for c in data["candidates"]:c["listing_ref"]="a"*64
    elif change=="wrong_league_url":data["candidates"][0]["source_search_url"]="https://www.pathofexile.com/trade2/search/Standard/abc123"
    else:data["candidates"][0]["observed_at_epoch"]=NOW+10000
    with pytest.raises(BuildError) as error:
        imported(tmp_path,data)
    assert "PRIVATE_CODE" not in str(error.value)


def test_manual_plan_is_explicitly_not_an_executed_search():
    result=prepare_search(SearchPlanRequest.model_validate({"filters":{"slot":"boots","stats":[{"metric":"movement_speed","minimum":30}]}}))
    assert not result.search_executed and not result.url_contains_filters
    with pytest.raises(ValidationError):
        OptimizeRequest.model_validate({"dataset_id":"gear_"+"0"*32,"budget":{"amount":1,"currency":"exalted"}})
