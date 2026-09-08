import json

import httpx
import pytest

from poe2_companion import localization
from poe2_companion.game_terms import TermRequest, search_terms, name_fields
from poe2_companion.scout import Scout
from poe2_companion.server import build_server
from poe2_companion.trade import parse_listing
from test_scout import Backend
from test_trade import listing


@pytest.fixture
def names(tmp_path, monkeypatch):
    # Synthetic catalog for the integration contract, independent of upstream
    # changes. The bundled real catalog has separate provenance/sample checks.
    entries = [("Divine_Orb", "Divine Orb", "신성한 오브"),
               ("Exalted_Orb", "Exalted Orb", "고귀한 오브"),
               ("Gold_Ring", "Gold Ring", "테스트 반지")]
    data = {"schema_version": 1, "snapshot_date": "2026-09-08", "game_version": "0.5.5",
            "sources": [], "records": [{"key": key, "en": en, "ko": ko, "categories": ["game_term"]}
                for key, en, ko in entries]}
    path = tmp_path / "names.json"
    path.write_text(json.dumps(data))
    catalog = localization.Catalog(path)
    monkeypatch.setattr(localization, "catalog", lambda: catalog)
    return catalog


async def test_korean_currency_search_quotes_and_reference_preserve_identity(names):
    scout = Scout(user_agent="test", transport=httpx.MockTransport(Backend()), interval=0)
    try:
        en = await scout.search("Divine Orb", "forbiddenrites", category="currency")
        ko = await scout.search("신성한 오브", "forbiddenrites", category="currency")
        assert ko["items"] == en["items"]
        row = ko["items"][0]
        assert row["name"] == "Divine Orb" and row["name_ko"] == "신성한 오브"
        assert row["name_source_ko"] == "https://poe2db.tw/kr/Divine_Orb"
        partial = await scout.prices("currency", "forbiddenrites", query="신성한")
        assert partial["data"]["items"][0]["item_id"] == row["item_id"]
        quote = await scout.quote([{"category":"currency", "item_id":row["item_id"], "quantity":2}],
            "forbiddenrites", reference_currency="고귀한 오브")
        assert quote["reference_currency"]["name_ko"] == "고귀한 오브"
        assert quote["estimated_total"] == 2 * row["unit_price"]
    finally:
        await scout.close()


def test_unknown_names_stay_english_and_trade_base_has_verified_label(names):
    assert name_fields("Unknown new item") == {"name_ko": None, "name_source_ko": None}
    result = parse_listing(listing(1), 1000)
    assert result.base_type == "Gold Ring" and result.base_type_ko == "테스트 반지"
    assert result.base_type_source_ko == "https://poe2db.tw/kr/Gold_Ring"


async def test_term_tool_is_offline_bounded_and_rejects_payload_echo(names):
    scout = Scout(user_agent="test", transport=httpx.MockTransport(Backend()), interval=0)
    server = build_server(scout)
    try:
        tools = {t.name: t for t in await server.list_tools()}
        tool = tools["search_game_terms"]
        assert tool.annotations.readOnlyHint and not tool.annotations.openWorldHint
        result = search_terms(TermRequest(query="오브", limit=1))
        assert len(result.entries) == 1 and result.has_more and not result.catalog_complete
        assert len(result.model_dump_json().encode()) <= 8192
        marker = "DO_NOT_ECHO_RAW_PAYLOAD_" * 100
        result = await server.call_tool("search_game_terms", {"request":{"query":marker}})
        assert result.isError and marker not in str(result)
    finally:
        await scout.close()


def test_localized_worst_case_engine_result_preserves_numeric_budget(monkeypatch):
    from typing import get_args
    from poe2_companion import game_terms
    from poe2_companion.builds import STAT_NAMES, PlayerStat
    from poe2_companion.engine import bounded_engine_dto
    from poe2_companion.engine_models import (EngineCalculation, EngineSnapshot, EngineTradeResult,
        EngineSlot, EquippedItem, SelectedSkill, RequirementIssue, TradeChange)

    stats = [PlayerStat(name=name, value=1e15) for name in sorted(STAT_NAMES)]
    snapshot = EngineSnapshot(stats=stats, equipped=[EquippedItem(slot=slot,
        saved_item_id=1000000, level_required=100) for slot in get_args(EngineSlot)],
        issues=[RequirementIssue(code="attribute_requirement", slot="body_armour", stat="Int",
            required=1e15, available=-1e15, passive_node_id=2147483647-i) for i in range(16)],
        issue_count=1000, validation="fail", active_weapon_set=2, main_skill_group=10000,
        selected_skill=SelectedSkill(skill_id="A"*120, name="B"*120, gem_name="C"*120, actor="minion"))
    calculation = EngineCalculation(build_id="bld_"+"1"*32, calculated_at_epoch=1788888888,
        baseline=snapshot, result=snapshot.model_copy(deep=True), deltas=stats)
    value = EngineTradeResult(calculation=calculation,
        changes=[TradeChange(slot=slot, listing_ref="f"*64) for slot in ("body_armour", "weapon_main", "weapon_off")], cost=1e15, currency="exalted",
        remaining_budget=1e15, score_gain=1e15, feasible=False, evaluated_combinations=64,
        failed_requirements=64, indeterminate_combinations=0, excluded_listings=32)
    value = bounded_engine_dto(value)
    before = value.model_dump()
    monkeypatch.setattr(game_terms, "name_fields", lambda _: {
        "name_ko":"한"*160, "name_source_ko":"https://poe2db.tw/kr/"+"a"*1000})
    result = game_terms.localize_engine_result(value)
    assert len(result.model_dump_json().encode()) <= 8192
    after = result.model_dump()
    for side in ("baseline", "result"):
        assert after["calculation"][side]["selected_skill"]["name_source_ko"] is None
        for label in ("name_ko", "name_source_ko"):
            after["calculation"][side]["selected_skill"][label] = None
    assert after == before


async def test_localized_character_pages_keep_all_entries_across_byte_limit(tmp_path, monkeypatch):
    from poe2_companion import game_terms
    from poe2_companion.characters import AccountRequest
    from test_characters import NinjaBackend, provider, TAG

    backend = NinjaBackend()
    backend.rows = [{**backend.rows[0], "name":"긴캐릭터이름"*8+str(i)} for i in range(20)]
    monkeypatch.setattr(game_terms, "name_fields", lambda name, prefix: {
        prefix+"_ko":"한"*160, prefix+"_source_ko":"https://poe2db.tw/kr/"+"a"*1000})
    p = provider(tmp_path, backend)
    names = []
    offset = 0
    try:
        while True:
            page = await p.list_account_characters(AccountRequest(account_tag=TAG, offset=offset))
            assert len(page.model_dump_json().encode()) <= 8192
            assert page.total == 20
            names.extend(c.name for c in page.characters)
            if page.next_offset is None:
                break
            assert page.next_offset > offset
            offset = page.next_offset
        assert names == [row["name"] for row in backend.rows]
    finally:
        await p.close()
