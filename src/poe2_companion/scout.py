from __future__ import annotations

import asyncio
import json
import math
import random
import sqlite3
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Annotated, Any, Callable
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel
from .game_terms import english_query, name_fields
from .workflow_metrics import measured, span, count

API = "https://api.poe2scout.com"
CATEGORIES = tuple("currency fragments runes essences ultimatum expedition ritual vaultkeys breach abyss uncutgems lineagesupportgems delirium incursion idol verisium vaal".split())
ALIASES = {
    "디바인": "Divine Orb", "딥": "Divine Orb", "div": "Divine Orb",
    "엑잘": "Exalted Orb", "엑잘티드 오브": "Exalted Orb", "ex": "Exalted Orb",
    "카오스": "Chaos Orb", "카오스 오브": "Chaos Orb",
    "신성한 오브": "Divine Orb", "고귀한 오브": "Exalted Orb",
}


class ScoutError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore", strict=True)


NonnegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
NonnegativeInt = Annotated[int, Field(ge=0)]


class League(Model):
    value: str
    short_name: str
    is_current: bool
    base_currency_api_id: str | None
    base_currency_base_item_type_id: str | None
    base_currency_text: str


class Reference(Model):
    api_id: str | None
    base_item_type_id: str | None
    text: str
    relative_price: NonnegativeFloat


class Category(Model):
    api_id: str
    label: str


class CategoryList(Model):
    currency_categories: list[Category]


class Log(Model):
    price: NonnegativeFloat
    time: str
    quantity: NonnegativeInt


class Item(Model):
    currency_item_id: int
    item_id: int
    api_id: str | None
    base_item_type_id: str | None
    text: str
    category_api_id: str
    current_price: NonnegativeFloat | None
    current_quantity: NonnegativeInt | None
    price_logs: list[Log | None]


class Page(Model):
    current_page: Annotated[int, Field(ge=1)]
    pages: NonnegativeInt
    total: NonnegativeInt
    items: list[Item]


def canonical(data: Any) -> Any:
    """Production emits PascalCase; some frontend contracts use camelCase."""
    if isinstance(data, dict):
        output = {}
        for key, value in data.items():
            normalized = key[:1].lower() + key[1:]
            if normalized in output:
                raise ScoutError("schema_changed", "Conflicting JSON property casing.")
            output[normalized] = canonical(value)
        return output
    if isinstance(data, list):
        return [canonical(v) for v in data]
    return data


def validate(data: Any, schema: Any) -> Any:
    try:
        return TypeAdapter(schema).validate_python(canonical(data))
    except ValidationError as exc:
        raise ScoutError("schema_changed", "Scout response no longer matches the verified API schema.") from exc


def utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def name_key(value: str) -> str:
    return "".join(c for c in value.casefold() if c.isalnum())


def resolve(rows: list[Any], query: str, fields: tuple[str, ...]) -> Any:
    query = english_query(ALIASES.get(query.casefold(), query))
    matches = [r for r in rows if any(name_key(str(getattr(r, f) or "")) == name_key(query) for f in fields)]
    if len(matches) != 1:
        raise ScoutError("ambiguous_or_missing", f"Expected one exact match for {query!r}; found {len(matches)}. List or search candidates first.")
    return matches[0]


class Cache:
    """Only complete, validated snapshots enter the bounded persistent cache."""
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(path).expanduser()) if path != ":memory:" else path)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, saved REAL, body TEXT)")

    def get(self, key: str):
        row = self.db.execute("SELECT saved, body FROM cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        try:
            return row[0], json.loads(row[1])
        except (ValueError, TypeError):
            self.db.execute("DELETE FROM cache WHERE key=?", (key,))
            self.db.commit()
            return None

    def put(self, key: str, saved: float, body: Any):
        self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (key, saved, json.dumps(body, allow_nan=False)))
        self.db.execute("DELETE FROM cache WHERE key NOT IN (SELECT key FROM cache ORDER BY saved DESC LIMIT 256)")
        self.db.commit()

    def close(self):
        self.db.close()


class Scout:
    def __init__(self, *, user_agent: str, cache_path: str = ":memory:", transport=None,
                 ttl: float = 300, stale_limit: float = 3600, interval: float = 0.5,
                 clock: Callable[[], float] = time.time):
        self.client = httpx.AsyncClient(base_url=API, timeout=httpx.Timeout(15, connect=5),
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            follow_redirects=False, transport=transport, limits=httpx.Limits(max_connections=3))
        self.cache, self.ttl, self.stale_limit = Cache(cache_path), ttl, stale_limit
        self.clock, self.interval = clock, interval
        self.locks = [asyncio.Lock() for _ in range(64)]
        self.rate_lock = asyncio.Lock()
        self.next_request = 0.0
        self.cooldown = 0.0

    async def close(self):
        await self.client.aclose()
        self.cache.close()

    @measured('network')
    async def _request(self, path: str, params: dict | None = None):
        url = str(httpx.URL(API + path, params=params))
        for attempt in range(3):
            async with self.rate_lock:
                if self.clock() < self.cooldown:
                    raise ScoutError("rate_limited", "Scout requested a cooldown; try again later.", True)
                delay = self.next_request - time.monotonic()
                if delay > 0:
                    with span('rate_wait'):
                        await asyncio.sleep(delay)
                self.next_request = time.monotonic() + self.interval
            try:
                count('upstream_request')
                async with self.client.stream("GET", path, params=params) as response:
                    if response.status_code == 429:
                        header = response.headers.get("Retry-After", "30")
                        try:
                            seconds = float(header)
                        except ValueError:
                            try:
                                seconds = parsedate_to_datetime(header).timestamp() - self.clock()
                            except (ValueError, TypeError, OverflowError):
                                seconds = 30
                        if not math.isfinite(seconds):
                            seconds = 30
                        self.cooldown = self.clock() + max(1, seconds)
                        raise ScoutError("rate_limited", "Scout returned HTTP 429; Retry-After cooldown applied.", True)
                    if response.status_code in (500, 502, 503, 504):
                        raise ScoutError("upstream_unavailable", f"Scout returned HTTP {response.status_code}.", True)
                    if response.status_code != 200:
                        raise ScoutError("upstream_http", f"Scout returned HTTP {response.status_code}; no alternate league or scraping fallback was used.")
                    if "json" not in response.headers.get("Content-Type", "").lower():
                        raise ScoutError("non_json", "Scout returned HTML or another non-JSON response.")
                    chunks, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > 8 * 1024 * 1024:
                            raise ScoutError("response_too_large", "Scout response exceeded 8 MiB.")
                        chunks.append(part)
                    try:
                        with span('parse'):
                            return json.loads(b"".join(chunks)), url
                    except ValueError as exc:
                        raise ScoutError("invalid_json", "Scout returned invalid JSON.") from exc
            except httpx.TransportError as exc:
                error = ScoutError("network_error", f"Scout transport failed ({type(exc).__name__}).", True)
            except ScoutError as exc:
                if not exc.retryable or exc.code == "rate_limited":
                    raise
                error = exc
            if attempt == 2:
                raise error
            await asyncio.sleep(0.5 * (2 ** attempt) + random.uniform(0, 0.2))

    async def _cached(self, key: str, loader, *, allow_stale: bool = False, ttl: float | None = None):
        ttl = self.ttl if ttl is None else ttl
        async with self.locks[hash(key) % len(self.locks)]:
            old = self.cache.get(key)
            now = self.clock()
            if old and 0 <= now - old[0] <= ttl:
                count('cache_hit')
                return self._envelope(old[1], old[0], "cache", False)
            count('cache_miss')
            try:
                body = await loader()
                saved = self.clock()
                self.cache.put(key, saved, body)
                return self._envelope(body, saved, "network", False)
            except ScoutError as exc:
                if allow_stale and exc.retryable and old and 0 <= self.clock() - old[0] <= self.stale_limit:
                    result = self._envelope(old[1], old[0], "stale_cache", True)
                    result["warning"] = {"code": exc.code, "message": str(exc)}
                    return result
                raise

    def _envelope(self, body, saved, delivery, stale):
        return {"data": body, "retrieved_at": utc(saved), "cache_age_seconds": round(max(0, self.clock()-saved), 1),
                "delivery": delivery, "stale": stale}

    async def leagues(self):
        async def loader():
            data, url = await self._request("/poe2/Leagues")
            rows = validate(data, list[League])
            if not rows:
                raise ScoutError("empty_league_catalog", "Scout returned no PoE2 leagues.")
            return {"leagues": [r.model_dump() for r in rows], "source_url": url}
        return await self._cached("v1:leagues", loader, ttl=3600)

    async def league(self, query: str) -> League:
        data = await self.leagues()
        return resolve([League(**v) for v in data["data"]["leagues"]], query, ("value", "short_name"))

    async def catalog(self, league: str, allow_stale: bool = False):
        selected = await self.league(league)
        base = self._base(selected)
        async def loader():
            raw, category_url = await self._request(base + "/Items/Categories")
            categories = validate(raw, CategoryList)
            raw, reference_url = await self._request(base + "/ReferenceCurrencies")
            references = validate(raw, list[Reference])
            return {"league": selected.model_dump(),
                    "categories": [v.model_dump() for v in categories.currency_categories],
                    "reference_currencies": [v.model_dump() for v in references],
                    "source_urls": [category_url, reference_url]}
        return await self._cached("v1:catalog:" + selected.value, loader, ttl=300, allow_stale=allow_stale)

    @staticmethod
    def _base(league: League):
        return "/poe2/Leagues/" + quote(league.value, safe="")

    async def _context(self, league: str, reference_currency: str, allow_stale: bool = False):
        catalog = await self.catalog(league, allow_stale)
        league_row = League(**catalog["data"]["league"])
        refs = [Reference(**v) for v in catalog["data"]["reference_currencies"]]
        if reference_currency == "base":
            reference_currency = league_row.base_currency_api_id or league_row.base_currency_base_item_type_id or ""
        reference = resolve(refs, reference_currency, ("api_id", "base_item_type_id", "text"))
        if reference.relative_price <= 0:
            raise ScoutError("unpriced_reference", "Reference currency has no positive price; conversion is unavailable.")
        return league_row, reference, catalog

    async def category(self, category: str, league: str, reference_currency: str = "exalted", allow_stale=False):
        league_row, reference, catalog = await self._context(league, reference_currency, allow_stale)
        available = [r["api_id"] for r in catalog["data"]["categories"]]
        if category not in available:
            raise ScoutError("category_unavailable", f"Category {category!r} has no priced entries in this league. Available: {', '.join(available)}")
        identifier = reference.api_id or reference.base_item_type_id
        if not identifier:
            raise ScoutError("schema_changed", "Reference currency lacks an identifier.")
        key = json.dumps(["v1:category", league_row.value, category, identifier])
        async def loader():
            items, urls, expected_total, expected_pages = [], [], None, None
            for page_number in range(1, 21):
                data, url = await self._request(self._base(league_row) + "/Currencies/ByCategory", {
                    "category": category, "page": page_number, "perPage": 250,
                    "dataPoints": 8, "frequencyHours": 1, "referenceCurrency": identifier})
                page = validate(data, Page)
                if page.current_page != page_number or page.pages > 20:
                    raise ScoutError("pagination_changed", "Unexpected or excessive pagination; no partial quote is returned.")
                if expected_total is None:
                    expected_total, expected_pages = page.total, page.pages
                if (page.total, page.pages) != (expected_total, expected_pages):
                    raise ScoutError("snapshot_changed", "Category changed while paging; retry to obtain a complete snapshot.", True)
                items.extend(page.items)
                urls.append(url)
                if page_number >= page.pages:
                    break
            if len(items) != expected_total or len({v.item_id for v in items}) != len(items):
                raise ScoutError("incomplete_snapshot", "Missing or duplicate page entries; no partial quote is returned.")
            if any(v.category_api_id != category for v in items):
                raise ScoutError("schema_changed", "Category response contains a different category.")
            return {"league": league_row.value, "league_slug": league_row.short_name, "realm": "poe2",
                    "category": category, "reference_currency": {"id": identifier, "name": reference.text},
                    "price_semantics": "reference currency per one item; Scout aggregated estimate, not an executable bid/ask",
                    "source_updated_at": None,
                    "source_time_note": "API currentPrice has no observation timestamp. History times are hourly bucket labels, not currentPrice timestamps.",
                    "source_urls": urls, "items": [v.model_dump() for v in items]}
        result = await self._cached(key, loader, allow_stale=allow_stale)
        unit = result["data"]["reference_currency"]
        unit.update(name_fields(unit["name"]))
        result["metadata_snapshot"] = {k: catalog[k] for k in ("retrieved_at", "cache_age_seconds", "delivery", "stale")}
        result["stale"] = result["stale"] or catalog["stale"]
        return result

    def _row(self, item, data):
        price = item["current_price"]
        logs = [v for v in item["price_logs"] if v is not None]
        return {"item_id": item["item_id"], "api_id": item["api_id"], "base_item_type_id": item["base_item_type_id"],
                "name": item["text"], **name_fields(item["text"]), "category": item["category_api_id"],
                "unit_price": price if price is not None and price > 0 else None,
                "price_status": "available" if price is not None and price > 0 else "unavailable",
                "source_quantity": item["current_quantity"],
                "latest_history_bucket_at": max((v["time"] for v in logs), default=None),
                "source_url": "https://poe2scout.com/poe2/" + quote(data["league_slug"], safe="") + "/economy/currencies/" + quote(item["category_api_id"], safe="")}

    async def prices(self, category: str, league: str, reference_currency="exalted", query="", limit=50, offset=0, allow_stale=False):
        if not 1 <= limit <= 100 or offset < 0 or offset > 5000:
            raise ScoutError("invalid_input", "limit must be 1..100 and offset 0..5000.")
        result = await self.category(category, league, reference_currency, allow_stale)
        data = result["data"]
        items = data["items"]
        if query:
            term = name_key(english_query(ALIASES.get(query.casefold(), query)))
            items = [r for r in items if any(term in name_key(str(v or "")) for v in
                (r["text"], r["api_id"], r["base_item_type_id"], name_fields(r["text"])["name_ko"]))]
        exact = name_key(english_query(ALIASES.get(query.casefold(), query))) if query else None
        items = sorted(items, key=lambda r: (exact is not None and all(name_key(str(r[k] or "")) != exact for k in ("text", "api_id", "base_item_type_id")), -(r["current_price"] or 0), r["text"]))
        return {**result, "data": {**{k:v for k,v in data.items() if k != "items"},
            "items": [self._row(r, data) for r in items[offset:offset+limit]], "matched_total": len(items),
            "offset": offset, "next_offset": offset+limit if offset+limit < len(items) else None}}

    async def search(self, query: str, league: str, reference_currency="exalted", category: str | None = None, limit=20):
        if not query.strip() or not 1 <= limit <= 100:
            raise ScoutError("invalid_input", "Supply a nonempty item name and limit 1..100.")
        catalog = await self.catalog(league)
        categories = [category] if category else [v["api_id"] for v in catalog["data"]["categories"]]
        if len(categories) > 40:
            raise ScoutError("catalog_changed", "Too many categories; specify one explicitly.")
        semaphore = asyncio.Semaphore(3)
        async def read(cat):
            async with semaphore:
                return await self.prices(cat, league, reference_currency, query=query, limit=limit)
        results = await asyncio.gather(*(read(cat) for cat in categories), return_exceptions=True)
        matches, errors, snapshots = [], [], []
        total = 0
        for cat, result in zip(categories, results):
            if isinstance(result, ScoutError):
                errors.append({"category": cat, "code": result.code, "message": str(result)})
            elif isinstance(result, BaseException):
                raise result
            else:
                total += result["data"]["matched_total"]
                matches.extend(result["data"]["items"])
                snapshots.append({"category": cat, **{k:result[k] for k in ("retrieved_at", "cache_age_seconds", "delivery", "stale")}})
        if not snapshots and errors:
            raise ScoutError("search_unavailable", "All category requests failed: " + json.dumps(errors))
        term = name_key(english_query(ALIASES.get(query.casefold(), query)))
        matches.sort(key=lambda r: (name_key(r["name"]) != term, -(r["unit_price"] or 0), r["name"]))
        return {"league": catalog["data"]["league"]["value"], "reference_currency": reference_currency,
            "query": query, "items": matches[:limit], "matched_total": total,
            "truncated": total > limit, "complete": not errors, "failed_categories": errors,
            "snapshots": snapshots, "source_updated_at": None,
            "note": "Partial search results do not establish absence. Specify a category to narrow results. Prices are reference currency per item; current-price observation time is not provided by Scout."}

    async def quote(self, requests: list[dict], league: str, reference_currency="exalted", allow_stale=False):
        if not 1 <= len(requests) <= 30:
            raise ScoutError("invalid_input", "Supply 1..30 items.")
        snapshots = {}
        rows, total, unresolved = [], 0.0, False
        for request in requests:
            category, item_id, quantity = request["category"], request["item_id"], request["quantity"]
            if not math.isfinite(quantity) or not 0 < quantity <= 1e9:
                raise ScoutError("invalid_input", "Quantity must be finite and in (0, 1e9].")
            if category not in snapshots:
                snapshots[category] = await self.category(category, league, reference_currency, allow_stale)
            snapshot = snapshots[category]
            matches = [r for r in snapshot["data"]["items"] if r["item_id"] == item_id]
            if len(matches) != 1:
                raise ScoutError("item_not_found", f"item_id {item_id} is not present in {category}; search again.")
            row = self._row(matches[0], snapshot["data"])
            subtotal = row["unit_price"] * quantity if row["unit_price"] is not None else None
            unresolved |= subtotal is None
            total += subtotal or 0
            rows.append({**row, "quantity": quantity, "estimated_total": subtotal})
        first = next(iter(snapshots.values()))["data"]
        return {"league": first["league"], "realm": "poe2", "reference_currency": first["reference_currency"],
            "items": rows, "estimated_total": None if unresolved else total, "complete": not unresolved,
            "stale": any(v["stale"] for v in snapshots.values()), "source_updated_at": None,
            "snapshots": [{"category": cat, **{k:v[k] for k in ("retrieved_at", "cache_age_seconds", "delivery", "stale")}} for cat,v in snapshots.items()],
            "note": "Arithmetic valuation using Scout category snapshots; categories can have different observation times. No guaranteed executable exchange rate or stock depth."}
