import asyncio
import json
from pathlib import Path

import httpx
import pytest

from poe2_companion.scout import Scout, ScoutError, Page, validate

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())


class Backend:
    def __init__(self):
        self.calls = []
        self.status = 200
        self.mode = "normal"

    def __call__(self, req):
        self.calls.append(req)
        if req.url.path.endswith("/Leagues"):
            return httpx.Response(200, json=fixture("leagues"))
        if req.url.path.endswith("/Categories"):
            return httpx.Response(200, json=fixture("categories"))
        if req.url.path.endswith("/ReferenceCurrencies"):
            return httpx.Response(200, json=fixture("references"))
        if self.status != 200:
            return httpx.Response(self.status, headers={"Retry-After": "60"})
        if self.mode == "html":
            return httpx.Response(200, text="<html>challenge</html>", headers={"Content-Type":"text/html"})
        raw = fixture("currency")
        cat = req.url.params["category"]
        if cat != "currency":
            return httpx.Response(200, json={"CurrentPage":1,"Pages":0,"Total":0,"Items":[]})
        if self.mode in ("pages", "duplicate", "changed"):
            page = int(req.url.params["page"])
            raw["CurrentPage"], raw["Pages"] = page, 3
            raw["Items"] = [raw["Items"][0 if self.mode == "duplicate" else page-1]]
            if self.mode == "changed" and page == 2:
                raw["Total"] += 1
        if self.mode == "missing_price":
            raw["Items"][0]["CurrentPrice"] = None
        if self.mode == "missing_field":
            del raw["Items"][0]["CurrentPrice"]
        if self.mode == "zero_price":
            raw["Items"][0]["CurrentPrice"] = 0
        if req.url.params["referenceCurrency"] == "divine":
            reference = next(v for v in fixture("currency")["Items"] if v["ApiId"] == "divine")
            divine = reference['CurrentPrice']
            for row in raw["Items"]:
                if row["CurrentPrice"] is not None:
                    row["CurrentPrice"] /= divine
                # Independent upstream EconomyCache.ConvertPriceLogMatrixFromBase:
                # historical conversion uses each matching bucket, not today's FX.
                for index,log in enumerate(row['PriceLogs']):
                    ref=reference['PriceLogs'][index]
                    if log is not None and ref is not None:log['Price']/=ref['Price']
        return httpx.Response(200, json=raw)


@pytest.fixture
async def client():
    backend = Backend()
    now = [10000.0]
    scout = Scout(user_agent="poe2-companion/test", transport=httpx.MockTransport(backend), interval=0,
                  clock=lambda: now[0], ttl=5, stale_limit=60)
    yield scout, backend, now
    await scout.close()


async def test_slug_resolution_alias_and_unit_direction(client):
    scout, backend, _ = client
    r = await scout.search("디바인", "forbiddenrites", category="currency")
    assert len(r["items"]) == 1
    item = r["items"][0]
    assert item["api_id"] == "divine"
    q = await scout.quote([{"item_id":item["item_id"],"category":"currency","quantity":2}], "Forbidden Rites")
    assert q["estimated_total"] == pytest.approx(2 * item["unit_price"])
    assert q["source_updated_at"] is None
    d = await scout.search("Divine Orb", "Forbidden Rites", reference_currency="divine", category="currency")
    assert d["items"][0]["unit_price"] == pytest.approx(1)
    assert all("Forbidden Rites" in req.url.path for req in backend.calls if "ByCategory" in req.url.path)


async def test_cache_and_concurrent_coalescing(client):
    scout, backend, _ = client
    await asyncio.gather(*(scout.prices("currency", "forbiddenrites") for _ in range(8)))
    assert sum("ByCategory" in req.url.path for req in backend.calls) == 1
    r = await scout.prices("currency", "Forbidden Rites")
    assert r["delivery"] == "cache" and not r["stale"]


async def test_reference_currency_has_separate_cache_key(client):
    scout, backend, _ = client
    await scout.prices("currency", "forbiddenrites", "exalted")
    await scout.prices("currency", "forbiddenrites", "divine")
    assert sum("ByCategory" in req.url.path for req in backend.calls) == 2


async def test_wrong_league_never_falls_back(client):
    scout, backend, _ = client
    with pytest.raises(ScoutError, match="exact match"):
        await scout.prices("currency", "Totally Unknown Season")
    assert not any("ByCategory" in req.url.path for req in backend.calls)


async def test_missing_category_is_explicit(client):
    scout, _, _ = client
    with pytest.raises(ScoutError) as e:
        await scout.prices("nonexistent", "forbiddenrites")
    assert e.value.code == "category_unavailable"


async def test_full_pagination_and_output_offset(client):
    scout, backend, _ = client
    backend.mode = "pages"
    r = await scout.prices("currency", "forbiddenrites", limit=1)
    assert r["data"]["matched_total"] == 3 and r["data"]["next_offset"] == 1
    assert sum("ByCategory" in req.url.path for req in backend.calls) == 3
    r2 = await scout.prices("currency", "forbiddenrites", limit=1, offset=1)
    assert r2["data"]["items"][0]["item_id"] != r["data"]["items"][0]["item_id"]


@pytest.mark.parametrize("mode", ["duplicate", "changed", "missing_field", "html"])
async def test_bad_snapshots_never_enter_cache(client, mode):
    scout, backend, _ = client
    backend.mode = mode
    with pytest.raises(ScoutError):
        await scout.prices("currency", "forbiddenrites")
    backend.mode = "normal"
    r = await scout.prices("currency", "forbiddenrites")
    assert r["delivery"] == "network"


async def test_stale_only_with_opt_in_and_bounded_age(client, monkeypatch):
    scout, backend, now = client
    await scout.prices("currency", "forbiddenrites")
    now[0] += 6
    backend.status = 503
    async def no_sleep(_): pass
    monkeypatch.setattr("poe2_companion.scout.asyncio.sleep", no_sleep)
    with pytest.raises(ScoutError):
        await scout.prices("currency", "forbiddenrites")
    r = await scout.prices("currency", "forbiddenrites", allow_stale=True)
    assert r["stale"] and r["delivery"] == "stale_cache" and r["cache_age_seconds"] == 6
    now[0] += 100
    with pytest.raises(ScoutError):
        await scout.prices("currency", "forbiddenrites", allow_stale=True)


async def test_schema_failures_cannot_be_hidden_by_stale_cache(client):
    scout, backend, now = client
    await scout.prices("currency", "forbiddenrites")
    now[0] += 6
    backend.mode = "html"
    with pytest.raises(ScoutError) as e:
        await scout.prices("currency", "forbiddenrites", allow_stale=True)
    assert e.value.code == "non_json"


async def test_429_cooldown_prevents_retry_storm(client):
    scout, backend, _ = client
    backend.status = 429
    for _ in range(3):
        with pytest.raises(ScoutError) as e:
            await scout.prices("currency", "forbiddenrites")
        assert e.value.code == "rate_limited"
    assert sum("ByCategory" in req.url.path for req in backend.calls) == 1


@pytest.mark.parametrize("mode", ["missing_price", "zero_price"])
async def test_unknown_price_is_not_free(client, mode):
    scout, backend, _ = client
    backend.mode = mode
    raw = fixture("currency")["Items"][0]
    r = await scout.quote([{"item_id":raw["ItemId"],"category":"currency","quantity":1}], "forbiddenrites")
    assert r["estimated_total"] is None and not r["complete"]


async def test_cross_category_search_and_unknown_alias(client):
    scout, _, _ = client
    r = await scout.search("div", "forbiddenrites")
    assert r["complete"] and len(r["items"]) == 1
    assert (await scout.search("알수없는룬", "forbiddenrites", category="currency"))["items"] == []


async def test_403_not_retried(client):
    scout, backend, _ = client
    backend.status = 403
    with pytest.raises(ScoutError):
        await scout.prices("currency", "forbiddenrites")
    assert sum("ByCategory" in req.url.path for req in backend.calls) == 1


def test_invalid_numeric_prices_and_casing_conflicts():
    for value in [float("nan"), float("inf"), -1, "82.5"]:
        data = fixture("currency")
        data["Items"][0]["CurrentPrice"] = value
        with pytest.raises(ScoutError):
            validate(data, Page)
    data = fixture("currency")
    data["total"] = 5
    with pytest.raises(ScoutError):
        validate(data, Page)


async def test_persistent_cache_survives_restart(tmp_path):
    backend = Backend()
    path = str(tmp_path / "prices.sqlite3")
    first = Scout(user_agent="test", cache_path=path, transport=httpx.MockTransport(backend), interval=0)
    await first.prices("currency", "forbiddenrites")
    await first.close()
    calls = len(backend.calls)
    second = Scout(user_agent="test", cache_path=path, transport=httpx.MockTransport(backend), interval=0)
    try:
        r = await second.prices("currency", "forbiddenrites")
        assert r["delivery"] == "cache" and len(backend.calls) == calls
    finally:
        await second.close()


async def test_stale_during_whole_upstream_outage(client, monkeypatch):
    scout, backend, now = client
    scout.stale_limit = 3600
    await scout.prices("currency", "forbiddenrites")
    now[0] += 301
    original = scout._request
    async def failed(*args, **kwargs):
        raise ScoutError("network_error", "Simulated complete outage", True)
    monkeypatch.setattr(scout, "_request", failed)
    result = await scout.prices("currency", "forbiddenrites", allow_stale=True)
    assert result["stale"] and result["metadata_snapshot"]["stale"]
    assert result["cache_age_seconds"] == 301
    with pytest.raises(ScoutError):
        await scout.prices("currency", "forbiddenrites")


async def test_transient_server_error_recovery(client, monkeypatch):
    scout, backend, _ = client
    await scout.catalog("forbiddenrites")
    backend.status = 503
    async def recover(_):
        backend.status = 200
    monkeypatch.setattr("poe2_companion.scout.asyncio.sleep", recover)
    result = await scout.prices("currency", "forbiddenrites")
    assert result["delivery"] == "network"
    assert sum("ByCategory" in req.url.path for req in backend.calls) == 2
