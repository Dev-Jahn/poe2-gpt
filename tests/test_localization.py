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
