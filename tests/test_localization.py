from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from poe2_companion.localization import Catalog, NameRecord, catalog, name_key

ROOT = Path(__file__).resolve().parents[1]


def sample(tmp_path, records):
    path = tmp_path / "names.json"
    path.write_text(json.dumps({"schema_version": 1, "snapshot_date": "2026-09-08", "game_version": "0.5.5",
                                "sources": [], "records": records}))
    return Catalog(path)


def row(key, en, ko):
    return {"key": key, "en": en, "ko": ko, "categories": ["currency"]}


def test_exact_bilingual_identity_and_ambiguity(tmp_path):
    db = sample(tmp_path, [row("Orb_of_Annulment", "Orb of Annulment", "소멸의 오브"),
                           row("A", "Same Name", "가"), row("B", "Same Name", "나")])
    assert db.english_query("소멸의오브") == "Orb of Annulment"
    assert db.lookup("Orb_of_Annulment").ko == "소멸의 오브"
    assert db.lookup("Same Name") is None
    assert db.english_query("Same Name") == "Same Name"
    assert len(db.search("same name")) == 2
    assert db.lookup("소멸") is None
    assert db.english_query("없는 오브") == "없는 오브"
    assert db.lookup("소멸의 오브").to_dict()["source_ko"] == "https://poe2db.tw/kr/Orb_of_Annulment"


@pytest.mark.parametrize("query", ["", " " * 5, "a" * 161, "x\n", "\x00", "\u200b", "!!!"])
def test_query_bounds_and_controls(tmp_path, query):
    db = sample(tmp_path, [])
    with pytest.raises(ValueError, match="localization_query_invalid"):
        db.search(query)


def test_unicode_normalization_search_and_limits(tmp_path):
    db = sample(tmp_path, [row("A", "An Orb", "소멸의 오브"), row("B", "Another Orb", "다른 오브")])
    assert name_key("소멸의 오브") == name_key("소멸의 오브")
    assert len(db.search("orb", 1)) == 1
    assert not db.search("orb", category="runes")
    for limit in (-1, 0, 21, True, "10"):
        with pytest.raises(ValueError, match="localization_limit_invalid"):
            db.search("orb", limit)


def test_catalog_refuses_duplicate_ids_paths_and_prose(tmp_path):
    for records in ([row("A", "A", "가"), row("A", "B", "나")],
                    [row("../x", "A", "가")], [dict(row("A", "A", "가"), description="not a name")]):
        with pytest.raises(ValueError):
            sample(tmp_path, records)


def updater():
    spec = importlib.util.spec_from_file_location("update_localization", ROOT / "scripts/update_localization.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_updater_joins_stable_values_rejects_conflicts_and_untranslated(tmp_path):
    import hashlib
    mod = updater()
    sources = []
    for lang, records in {
        "us": [{"value": "Orb_of_Annulment", "label": "Orb of Annulment"},
               {"value": "Conflict", "label": "One"}, {"value": "Conflict", "label": "Two"},
               {"value": "Untranslated", "label": "Placeholder"}],
        "kr": [{"value": "Untranslated", "label": "Placeholder"},
               {"value": "Orb_of_Annulment", "label": "<span>소멸의 오브</span>"},
               {"value": "Conflict", "label": "충돌"}],
    }.items():
        data = json.dumps(records).encode()
        (tmp_path / f"{lang}.json").write_bytes(data)
        sources.append({"language": "en" if lang == "us" else "ko", "url": f"https://poe2db.tw/json/autocompletecb_{lang}.aabb.json",
                        "sha256": hashlib.sha256(data).hexdigest()})
    (tmp_path / "provenance.json").write_text(json.dumps({"snapshot_date": "2026-09-08", "sources": sources}))
    output = tmp_path / "result.json"
    assert mod.build(tmp_path, output, "0.5.5")["record_count"] == 1
    result = json.loads(output.read_bytes())
    assert result["diagnostics"]["en"]["conflicting_keys"] == 1
    assert result["diagnostics"]["untranslated"] == 1
    assert Catalog(output).english_query("소멸의 오브") == "Orb of Annulment"
    (tmp_path / "kr.json").write_text("[]")
    with pytest.raises(ValueError, match="source_hash_mismatch"):
        mod.build(tmp_path, output, "0.5.5")


def test_updater_source_allowlist_and_no_description_copy():
    mod = updater()
    for url in ("http://poe2db.tw/us/", "https://evil.test/x", "https://poe2db.tw.evil.test/x", "https://user:pass@poe2db.tw/x"):
        with pytest.raises(ValueError, match="unexpected_source_url"):
            mod.valid_asset(url)
    records, _ = mod.index_rows([{"value": "Divine_Orb", "label": "신성한 오브", "description": "Never copied"}])
    assert records == {"Divine_Orb": "신성한 오브"}


def test_packaged_snapshot_has_verified_currency_and_current_league_names():
    db = catalog()
    assert db.lookup("Orb of Annulment").ko == "소멸의 오브"
    assert db.lookup("Exalted Orb").ko == "엑잘티드 오브"
    assert db.lookup("Divine Orb").ko == "신성한 오브"
    assert db.lookup("Jiquani's Soul Core of Automation") is not None
    assert db.lookup("Martial Artist") is not None
    assert db.metadata()["game_version"] == "0.5.5"
    assert db.metadata()["complete"] is False


def test_html_catalog_joins_actual_links_not_navigation_or_row_order(tmp_path):
    import hashlib
    mod = updater()
    pages = {
        "us": '<a href="Orb_of_Annulment">Orb of Annulment</a>'
              '<a href="Devotion_to_the_King">Item</a>'
              '<a href="https://evil.test/us/Bad">Bad</a>'
              '<a href="Divine_Orb"><span>Divine Orb</span></a>',
        "kr": '<a href="Divine_Orb">신성한 오브</a><a href="Orb_of_Annulment">소멸의 오브</a>'
              '<a href="Orb_of_Annulment">Orb of Annulment</a>'
              '<a href="Devotion_to_the_King">아이템</a>',
    }
    sources = []
    for i, (language, html) in enumerate(pages.items()):
        raw = html.encode()
        filename = f"page-{i:02}-{language}.html"
        (tmp_path / filename).write_bytes(raw)
        sources.append({"language": "en" if language == "us" else "ko", "url": f"https://poe2db.tw/{language}/Currency",
                        "sha256": hashlib.sha256(raw).hexdigest(), "file": filename})
    (tmp_path / "html-provenance.json").write_text(json.dumps({"snapshot_date": "2026-09-08", "sources": sources,
                                                            "requested_pages_not_found": []}))
    output = tmp_path / "html-result.json"
    assert mod.build_html(tmp_path, output, "0.5.5")["record_count"] == 2
    db = Catalog(output)
    assert db.lookup("Orb of Annulment").ko == "소멸의 오브"
    assert db.lookup("Divine Orb").ko == "신성한 오브"
    assert db.lookup("Item") is None
    assert "Devotion_to_the_King" not in output.read_text()
    (tmp_path / "page-00-us.html").write_text("changed")
    with pytest.raises(ValueError, match="source_hash_mismatch"):
        mod.build_html(tmp_path, output, "0.5.5")


def test_html_redirects_stay_on_same_language_origin_and_record_chain():
    import io
    import urllib.error
    from email.message import Message
    mod = updater()
    calls = []

    def open_request(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith("/Omens"):
            headers = Message()
            headers["Location"] = "/us/Omen"
            raise urllib.error.HTTPError(request.full_url, 301, "Moved", headers, None)
        return io.BytesIO(b'<a href="Divine_Orb">Divine Orb</a>')

    body, final_url, chain = mod.fetch_html("https://poe2db.tw/us/Omens", open_request=open_request)
    assert final_url == "https://poe2db.tw/us/Omen"
    assert len(calls) == 2 and b"Divine Orb" in body
    assert chain == [{"from": "https://poe2db.tw/us/Omens", "to": final_url, "status": 301}]
    for target in ("https://evil.test/us/Omen", "http://poe2db.tw/us/Omen", "/kr/Omen", "/us/Omen?token=x",
                   "/us/Omen#data", "https://x:y@poe2db.tw/us/Omen", "https://poe2db.tw:444/us/Omen", "/us/%2e%2e/login"):
        with pytest.raises(ValueError, match="html_redirect_refused"):
            mod.html_destination("https://poe2db.tw/us/Omens", target)


def test_html_redirect_loop_and_denial_do_not_retry():
    import urllib.error
    from email.message import Message
    mod = updater()
    calls = []

    def denied(request, timeout):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 403, "Denied", Message(), None)

    with pytest.raises(urllib.error.HTTPError):
        mod.fetch_html("https://poe2db.tw/us/Omens", open_request=denied)
    assert len(calls) == 1

    def loop(request, timeout):
        headers = Message()
        headers["Location"] = request.full_url
        raise urllib.error.HTTPError(request.full_url, 302, "Moved", headers, None)

    with pytest.raises(ValueError, match="html_redirect_loop"):
        mod.fetch_html("https://poe2db.tw/us/Omens", open_request=loop)


def test_html_currency_pair_survives_missing_homepage_link_and_resumes(tmp_path, monkeypatch):
    mod = updater()
    calls = []
    pages = {
        "https://poe2db.tw/us/": '<a href="Rune">Runes</a>',
        "https://poe2db.tw/kr/": '<a href="Rune">룬</a>',
        "https://poe2db.tw/us/Rune": '<a href="Example_Rune">Example Rune</a>',
        "https://poe2db.tw/kr/Rune": '<a href="Example_Rune">예제 룬</a>',
        "https://poe2db.tw/us/Currency": '<a href="Divine_Orb">Divine Orb</a>',
        "https://poe2db.tw/kr/Currency": '<a href="Divine_Orb">신성한 오브</a>',
    }

    def fetch_html(url):
        calls.append(url)
        return pages[url].encode(), url, []

    monkeypatch.setattr(mod, "fetch_html", fetch_html)
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    mod.download_html(tmp_path, ["Currency", "Runes"])
    assert len(calls) == 6
    assert calls[-2:] == ["https://poe2db.tw/us/Currency", "https://poe2db.tw/kr/Currency"]
    output = tmp_path / "result.json"
    assert mod.build_html(tmp_path, output, "0.5.5")["record_count"] == 2
    assert Catalog(output).lookup("Divine Orb").ko == "신성한 오브"
    mod.download_html(tmp_path, ["Currency", "Runes"], resume=True)
    assert len(calls) == 6  # The verified checkpoint avoids repeating completed requests.


def test_canonical_page_title_adds_verified_class_name_without_anchor():
    mod = updater()
    en = mod.anchors(b'<title>Monk - PoE2DB, Path of Exile Wiki us</title>', 'https://poe2db.tw/us/Monk', 'us')
    ko = mod.anchors('<title>몽크 - PoE2DB, Path of Exile Wiki kr</title>'.encode(), 'https://poe2db.tw/kr/Monk', 'kr')
    assert en == [{"value": "Monk", "label": "Monk", "url": "https://poe2db.tw/us/Monk"}]
    assert ko == [{"value": "Monk", "label": "몽크", "url": "https://poe2db.tw/kr/Monk"}]
