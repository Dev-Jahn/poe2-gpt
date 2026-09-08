"""Offline, provenance-backed game names. Never infer a missing translation."""
from __future__ import annotations

import json
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

MAX_QUERY = 160
MAX_RESULTS = 20
MAX_CATALOG_BYTES = 4 * 1024 * 1024


def name_key(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def checked_query(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_QUERY:
        raise ValueError("localization_query_invalid")
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise ValueError("localization_query_invalid")
    value = name_key(value)
    if not value:
        raise ValueError("localization_query_invalid")
    return value


@dataclass(frozen=True)
class NameRecord:
    """PoE2DB page key, not a GGG item/mod identifier; English stays canonical."""

    key: str
    en: str
    ko: str
    categories: tuple[str, ...]

    def to_dict(self) -> dict:
        suffix = quote(self.key, safe="_-'()")
        return {
            "key": self.key, "en": self.en, "ko": self.ko,
            "categories": list(self.categories),
            "source_en": f"https://poe2db.tw/us/{suffix}",
            "source_ko": f"https://poe2db.tw/kr/{suffix}",
        }


class Catalog:
    def __init__(self, path: Path | None = None):
        raw = path.read_bytes() if path else files("poe2_companion").joinpath("data/localization-ko.json").read_bytes()
        if len(raw) > MAX_CATALOG_BYTES:
            raise ValueError("localization_catalog_invalid")
        data = json.loads(raw)
        if data.get("schema_version") != 1 or not isinstance(data.get("records"), list):
            raise ValueError("localization_catalog_invalid")
        self._metadata = {k: data[k] for k in ("schema_version", "snapshot_date", "game_version", "sources")}
        by_key: dict[str, NameRecord] = {}
        by_name: dict[str, set[str]] = defaultdict(set)
        for row in data["records"]:
            if set(row) != {"key", "en", "ko", "categories"}:
                raise ValueError("localization_catalog_invalid")
            for field in ("key", "en", "ko"):
                checked_query(row[field])
            if (any(c in row["key"] for c in "/\\?#") or row["key"] in by_key
                    or len(quote(row["key"], safe="_-'()")) > 900):
                raise ValueError("localization_catalog_invalid")
            if not isinstance(row["categories"], list) or not row["categories"] or len(row["categories"]) > 20:
                raise ValueError("localization_catalog_invalid")
            if any(not isinstance(c, str) or not c.isascii() or not c.replace("_", "").isalnum() for c in row["categories"]):
                raise ValueError("localization_catalog_invalid")
            record = NameRecord(row["key"], row["en"], row["ko"], tuple(sorted(set(row["categories"]))))
            by_key[record.key] = record
            for label in (record.key, record.en, record.ko):
                by_name[name_key(label)].add(record.key)
        self._by_key = by_key
        self._by_name = by_name
        self._records = tuple(sorted(by_key.values(), key=lambda r: (r.en.casefold(), r.key)))

    def lookup(self, name_or_id: str) -> NameRecord | None:
        candidates = self._by_name.get(checked_query(name_or_id), ())
        return self._by_key[next(iter(candidates))] if len(candidates) == 1 else None

    def english_query(self, query: str) -> str:
        record = self.lookup(query)
        return record.en if record else query

    def search(self, query: str, limit: int = 10, *, category: str | None = None) -> list[NameRecord]:
        term = checked_query(query)
        if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
            raise ValueError("localization_limit_invalid")
        if category is not None and (not isinstance(category, str) or len(category) > 40):
            raise ValueError("localization_category_invalid")
        matches = [r for r in self._records if (category is None or category in r.categories)
                   and any(term in name_key(s) for s in (r.key, r.en, r.ko))]
        matches.sort(key=lambda r: (not any(term == name_key(s) for s in (r.key, r.en, r.ko)), r.en.casefold(), r.key))
        return matches[:limit]

    def metadata(self) -> dict:
        counts = Counter(c for r in self._records for c in r.categories)
        return {**json.loads(json.dumps(self._metadata)), "record_count": len(self._records), "categories": dict(sorted(counts.items())),
                "translation_policy": "verified_names_only", "complete": False}


@lru_cache(maxsize=1)
def catalog() -> Catalog:
    return Catalog()


def lookup(name_or_id: str) -> NameRecord | None:
    return catalog().lookup(name_or_id)


def english_query(query: str) -> str:
    return catalog().english_query(query)


def search(query: str, limit: int = 10, *, category: str | None = None) -> list[NameRecord]:
    return catalog().search(query, limit, category=category)


def metadata() -> dict:
    return catalog().metadata()
