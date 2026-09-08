#!/usr/bin/env python3
"""Refresh a minimal EN/KO name catalog from PoE2DB's public search indexes.

Four normal HTTPS GETs discover current hashed assets. Never send cookies or
browser impersonation headers; 403/429 abort without retries. --source-dir can
rebuild from separately downloaded public indexes plus provenance.json.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import unquote, urljoin, urlsplit
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from poe2_companion.localization import Catalog, checked_query, name_key

MAX_SOURCE_BYTES = 16 * 1024 * 1024


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, value):
        self.parts.append(value)


def plain(value: str) -> str:
    parser = Text()
    parser.feed(value)
    return " ".join("".join(parser.parts).split())


def valid_asset(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in {"poe2db.tw", "cdn.poe2db.tw"} or parts.username or parts.password or parts.port not in (None, 443) or parts.fragment:
        raise ValueError("unexpected_source_url")
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("source_redirect_refused")


def fetch(url: str) -> bytes:
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(valid_asset(url), headers={"User-Agent": "poe2-gpt-localization-updater/1 (+https://github.com/Dev-Jahn/poe2-gpt)"})
    with opener.open(request, timeout=30) as response:
        data = response.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("source_too_large")
    return data


def download(directory: Path) -> None:
    homepage = "https://poe2db.tw/us/"
    html = fetch(homepage).decode("utf-8")
    headers = re.findall(r'(?:https:)?//cdn\.poe2db\.tw/js/poedb_header\.[a-fA-F0-9]+\.js', html)
    if len(set(headers)) != 1:
        raise ValueError("header_asset_not_found")
    header_url = urljoin(homepage, headers[0])
    script = fetch(header_url).decode("utf-8").replace("\\/", "/")
    sources = []
    directory.mkdir(parents=True, exist_ok=True)
    for language in ("us", "kr"):
        pattern = rf'autocompletecb_{language}\.[a-fA-F0-9]+\.json'
        candidates = set(re.findall(pattern, script))
        if len(candidates) != 1:
            raise ValueError("autocomplete_asset_not_found")
        asset_url = urljoin(header_url, "../json/" + candidates.pop())
        content = fetch(asset_url)
        json.loads(content)  # Do not publish an HTML denial page as a catalog.
        (directory / f"{language}.json").write_bytes(content)
        sources.append({"language": "en" if language == "us" else "ko", "url": asset_url,
                        "sha256": hashlib.sha256(content).hexdigest()})
    metadata = {"snapshot_date": datetime.now(timezone.utc).date().isoformat(),
                "homepage": homepage, "header_url": header_url, "sources": sources}
    (directory / "provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")


def index_rows(data: object) -> tuple[dict[str, str], dict[str, int]]:
    """Join `value`, never localized row order or generated name slugs."""
    if not isinstance(data, list) or len(data) > 100000:
        raise ValueError("autocomplete_schema_changed")
    labels: dict[str, set[str]] = defaultdict(set)
    rejected = 0
    for row in data:
        if not isinstance(row, dict) or not isinstance(row.get("value"), str) or not isinstance(row.get("label"), str):
            raise ValueError("autocomplete_schema_changed")
        key = unquote(row["value"]).strip()
        # Some index revisions expose relative paths; reject nonentry routes.
        if key.startswith(("https://poe2db.tw/", "/us/", "/kr/")):
            path = urlsplit(key).path
            key = path.split("/", 2)[-1]
        label = plain(row["label"])
        try:
            checked_query(key)
            checked_query(label)
            if any(c in key for c in "/\\?#") or any(c in label for c in "<>") or "DNT" in label or "UNUSED" in label:
                raise ValueError("not_a_game_name")
        except ValueError:
            rejected += 1
            continue
        labels[key].add(label)
    conflicts = sum(len(v) > 1 for v in labels.values())
    return {k: next(iter(v)) for k, v in labels.items() if len(v) == 1}, {"rejected": rejected, "conflicting_keys": conflicts}


def categories(key: str, english: str) -> list[str]:
    """Search facets are heuristics over verified names, not gameplay claims."""
    term = english.casefold()
    result = []
    if any(x in term for x in (" orb", "shard", "whetstone", "scrap", "bauble", "etcher", "prism", "scroll", "hinekora's lock")):
        result.append("currency")
    for needle, category in (("rune", "runes"), ("soul core", "soul_cores"), ("essence", "essences"),
                             ("omen", "omens"), ("idol", "idols"), ("talisman", "talismans"),
                             ("catalyst", "catalysts"), ("verisium", "verisium"), ("uncut", "uncut_gems"),
                             ("waystone", "waystones"), ("splinter", "fragments"), ("key", "fragments")):
        if needle in term:
            result.append(category)
    # Generic index records include gems, bases, uniques, classes, passives and mechanics.
    # Do not claim a specific game category when the source does not identify it.
    return sorted(set(result)) or ["game_term"]


def build(directory: Path, output: Path, game_version: str) -> dict:
    provenance = json.loads((directory / "provenance.json").read_bytes())
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', provenance["snapshot_date"]):
        raise ValueError("invalid_snapshot_date")
    sources = provenance["sources"]
    if len(sources) != 2 or {s["language"] for s in sources} != {"en", "ko"}:
        raise ValueError("invalid_source_provenance")
    index, diagnostics = {}, {}
    for lang, label in (("us", "en"), ("kr", "ko")):
        raw = (directory / f"{lang}.json").read_bytes()
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError("source_too_large")
        source = next(s for s in sources if s["language"] == label)
        valid_asset(source["url"])
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("source_hash_mismatch")
        index[label], diagnostics[label] = index_rows(json.loads(raw))
    records = []
    untranslated = 0
    for key in sorted(index["en"].keys() & index["ko"].keys()):
        en, ko = index["en"][key], index["ko"][key]
        if not re.search(r'[가-힣]', ko) or name_key(en) == name_key(ko):
            untranslated += 1
            continue
        records.append({"key": key, "en": en, "ko": ko, "categories": categories(key, en)})
    if not records:
        raise ValueError("empty_bilingual_catalog")
    payload = {"schema_version": 1, "snapshot_date": provenance["snapshot_date"], "game_version": game_version,
               "sources": sources, "diagnostics": {**diagnostics, "untranslated": untranslated,
               "unpaired_en": len(index["en"].keys() - index["ko"].keys()),
               "unpaired_ko": len(index["ko"].keys() - index["en"].keys())}, "records": records}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    try:
        check = Catalog(temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return check.metadata()



DEFAULT_HTML_PAGES = (
    "Currency", "Runes", "Rune", "Essence", "Soul Core", "Omens",
    "Skill Gems", "Support Gems", "Lineage Supports", "Unique", "Items",
    "Classes", "Ascendancy", "Liquid Emotions", "Catalysts", "Runes of Aldur",
    "Verisium", "Idol", "Abyss", "Ritual", "Ultimatum", "Expedition",
    "Delirium", "Breach", "Uncut Skill Gem", "Uncut Support Gem", "Uncut Spirit Gem",
)


class Anchors(HTMLParser):
    """Extract anchor labels and actual page keys, without scraping prose."""
    def __init__(self, url: str, language: str):
        super().__init__(convert_charrefs=True)
        self.url, self.language = url, language
        self.active = None
        self.rows: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.active = [dict(attrs).get("href", ""), []]

    def handle_data(self, value):
        if self.active is not None:
            self.active[1].append(value)

    def handle_endtag(self, tag):
        if tag != "a" or self.active is None:
            return
        href, parts = self.active
        self.active = None
        label = " ".join("".join(parts).split())
        target = urlsplit(urljoin(self.url, href))
        prefix = "/" + self.language + "/"
        if (not href or href.startswith("#") or target.scheme != "https"
                or target.hostname != "poe2db.tw" or target.query or target.fragment
                or not target.path.startswith(prefix)):
            return
        key = unquote(target.path[len(prefix):])
        try:
            checked_query(key)
            checked_query(label)
            if any(c in key for c in "/\\?#") or "DNT" in label or "UNUSED" in label:
                return
        except ValueError:
            return
        self.rows.append({"value": key, "label": label, "url": target.geturl()})


def anchors(body: bytes, url: str, language: str) -> list[dict]:
    parser = Anchors(url, language)
    parser.feed(body.decode("utf-8"))
    return parser.rows


def download_html(directory: Path, requested_pages: list[str]) -> None:
    """Explicit alternative source, never an automatic retry of a denied CDN."""
    directory.mkdir(parents=True, exist_ok=True)
    sources = []
    homes = {}

    def save(url, language):
        content = fetch(url)
        number = len(sources)
        filename = f"page-{number:02}-{language}.html"
        (directory / filename).write_bytes(content)
        sources.append({"language": "en" if language == "us" else "ko", "url": url,
                        "sha256": hashlib.sha256(content).hexdigest(), "file": filename})
        time.sleep(0.5)
        return anchors(content, url, language)

    for language in ("us", "kr"):
        homes[language] = save(f"https://poe2db.tw/{language}/", language)
    requested = {name_key(p) for p in requested_pages}
    candidates = {r["value"]: r for r in homes["us"]
                  if name_key(r["label"]) in requested or name_key(r["value"]) in requested}
    korean = {r["value"]: r for r in homes["kr"]}
    keys = sorted(candidates.keys() & korean.keys())
    if len(keys) > 24:
        raise ValueError("too_many_html_pages")
    if not keys:
        raise ValueError("html_category_links_not_found")
    for key in keys:
        save(candidates[key]["url"], "us")
        save(korean[key]["url"], "kr")
    seen = {name_key(v) for key in keys for v in (key, candidates[key]["label"])}
    metadata = {"snapshot_date": datetime.now(timezone.utc).date().isoformat(),
                "source_kind": "html_anchors", "requested_pages_not_found": sorted(p for p in requested_pages if name_key(p) not in seen),
                "sources": sources}
    (directory / "html-provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")


def build_html(directory: Path, output: Path, game_version: str) -> dict:
    provenance = json.loads((directory / "html-provenance.json").read_bytes())
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', provenance["snapshot_date"]):
        raise ValueError("invalid_snapshot_date")
    if not 2 <= len(provenance["sources"]) <= 50:
        raise ValueError("invalid_source_provenance")
    rows = {"en": [], "ko": []}
    sources = []
    for source in provenance["sources"]:
        language = source["language"]
        if language not in rows or not re.fullmatch(r"page-\d{2}-(us|kr)\.html", source["file"]):
            raise ValueError("invalid_source_provenance")
        raw = (directory / source["file"]).read_bytes()
        if len(raw) > MAX_SOURCE_BYTES or hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("source_hash_mismatch")
        valid_asset(source["url"])
        parsed = anchors(raw, source["url"], "us" if language == "en" else "kr")
        for row in parsed:
            # Navigation labels like "Item" must not become item translations.
            # Both the English label and actual linked page key must agree.
            if language == "en" and name_key(row["label"]) != name_key(row["value"]):
                continue
            if language == "ko" and not re.search(r"[가-힣]", row["label"]):
                continue
            rows[language].append(row)
        sources.append({k: source[k] for k in ("language", "url", "sha256")})
    index, diagnostics = {}, {}
    for language in rows:
        index[language], diagnostics[language] = index_rows(rows[language])
    records = []
    untranslated = 0
    for key in sorted(index["en"].keys() & index["ko"].keys()):
        en, ko = index["en"][key], index["ko"][key]
        if not re.search(r'[가-힣]', ko) or name_key(en) == name_key(ko):
            untranslated += 1
            continue
        records.append({"key": key, "en": en, "ko": ko, "categories": categories(key, en)})
    if not records:
        raise ValueError("empty_bilingual_catalog")
    payload = {"schema_version": 1, "snapshot_date": provenance["snapshot_date"], "game_version": game_version,
               "source_kind": "html_anchors", "sources": sources,
               "diagnostics": {**diagnostics, "untranslated": untranslated,
               "requested_pages_not_found": provenance["requested_pages_not_found"],
               "unpaired_en": len(index["en"].keys() - index["ko"].keys()),
               "unpaired_ko": len(index["ko"].keys() - index["en"].keys())}, "records": records}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    try:
        check = Catalog(temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {"record_count": check.metadata()["record_count"], "source_pages": len(sources), "diagnostics": payload["diagnostics"]}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True, help="Local public-index cache, not a character/build directory")
    parser.add_argument("--fetch", action="store_true", help="Discover and download current public sources; abort on refusal")
    parser.add_argument("--html-pages", nargs="*", default=None, help="Explicit HTML anchor catalog mode; optional English category names discovered from homepage")
    parser.add_argument("--game-version", required=True, help="Game patch verified independently against PoE2DB homepage")
    parser.add_argument("--output", type=Path, default=ROOT / "src/poe2_companion/data/localization-ko.json")
    args = parser.parse_args()
    if args.html_pages is not None:
        if args.fetch:
            download_html(args.source_dir, args.html_pages or list(DEFAULT_HTML_PAGES))
        result = build_html(args.source_dir, args.output, args.game_version)
    else:
        if args.fetch:
            download(args.source_dir)
        result = build(args.source_dir, args.output, args.game_version)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
