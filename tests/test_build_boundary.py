import base64
import json
import logging
import os
import subprocess
import sys
import zlib
from pathlib import Path

import httpx
import pytest

from poe2_companion.builds import BuildError, BuildReader, MAX_TOOL_JSON_BYTES
from poe2_companion.pob_io import decode_pob, export_file, import_file, project_pob
from poe2_companion.scout import Scout
from poe2_companion.server import build_server
from test_scout import Backend

MARKER = "PRIVATE_POB_SENTINEL_DO_NOT_SEND_" * 30


def xml():
    return f'''<PathOfBuilding2>
<Build level="91" className="Witch" ascendClassName="{MARKER}" targetVersion="0_5">
  <PlayerStat stat="Life" value="2100"/><PlayerStat stat="EnergyShield" value="4300"/>
  <PlayerStat stat="CombinedDPS" value="125000.5"/>
  <PlayerStat stat="{MARKER}" value="1"/>
</Build>
<Notes>{MARKER}</Notes><Import importLink="{MARKER}"/>
<Items><Item id="1">{MARKER}</Item></Items>
<Skills activeSkillSet="1"><SkillSet id="1" title="{MARKER}">
  <Skill label="{MARKER}"><Gem nameSpec="{MARKER}" skillId="{MARKER}" level="20"/></Skill>
</SkillSet></Skills>
<Tree><Spec nodes="1,2,3,4,5" title="{MARKER}"><URL>{MARKER}</URL></Spec></Tree>
</PathOfBuilding2>'''.encode()


def code(xml_bytes=None):
    return base64.urlsafe_b64encode(zlib.compress(xml() if xml_bytes is None else xml_bytes))


def imported(tmp_path):
    source = tmp_path / "input.pob"
    source.write_bytes(code()+b"\n")
    private, projections = tmp_path/"private", tmp_path/"projections"
    build_id = import_file(source, private, projections)
    return build_id, private, projections, source


def test_projection_is_allowlist_only_and_bounded(tmp_path):
    build_id, private, projections, source = imported(tmp_path)
    reader = BuildReader(projections)
    summary = reader.summary(build_id)
    assert summary.class_name == "Witch" and summary.level == 91
    assert summary.stats[0].value == 2100
    assert summary.counts.saved_items == 1 and summary.counts.saved_gems == 1
    assert not summary.live_character
    body = summary.model_dump_json()
    assert len(body.encode()) <= MAX_TOOL_JSON_BYTES
    projected = (projections/(build_id+".json")).read_text()
    for forbidden in [MARKER, code().decode(), xml().decode(), "ascendClassName", "skillId", "nameSpec", "importLink"]:
        assert forbidden not in body and forbidden not in projected
    assert (private/(build_id+".pob")).read_bytes() == source.read_bytes()


def test_export_copies_exact_original_bytes_no_reencoding(tmp_path):
    build_id, private, _, source = imported(tmp_path)
    destination = tmp_path/"export.pob"
    export_file(build_id, private, destination)
    assert destination.read_bytes() == source.read_bytes()
    with pytest.raises(FileExistsError):
        export_file(build_id, private, destination)
    if os.name == "posix":
        assert destination.stat().st_mode & 0o777 == 0o600


def test_node_paging_returns_only_numeric_subset(tmp_path):
    build_id, _, projections, _ = imported(tmp_path)
    reader = BuildReader(projections)
    page = reader.nodes(build_id, 0, 1, 2)
    assert page.node_ids == [2,3] and page.next_offset == 3 and page.total == 5
    with pytest.raises(BuildError): reader.nodes(build_id, 0, 0, 101)
    with pytest.raises(BuildError): reader.summary("../../private/input.pob")


@pytest.mark.parametrize("body", [b"not-a-code", b"https://somewhere.example/pob/abc", b"<PathOfBuilding2/>", b"AAAA"])
def test_malformed_code_has_fixed_error(body):
    with pytest.raises(BuildError) as error:
        decode_pob(body)
    assert body.decode() not in str(error.value)


def test_bounded_inflate_rejects_bombs_and_trailing_streams(monkeypatch):
    monkeypatch.setattr("poe2_companion.pob_io.MAX_XML_BYTES", 256)
    with pytest.raises(BuildError, match="expanded_pob_too_large"):
        decode_pob(code(b"x" * 10000))
    with pytest.raises(BuildError, match="invalid_pob_stream"):
        decode_pob(base64.urlsafe_b64encode(zlib.compress(b"x") + b"secret trailing"))


def test_xml_entities_wrong_game_and_numeric_blobs_are_rejected():
    bad = b'<!DOCTYPE PathOfBuilding2 [<!ENTITY secret SYSTEM "file:///etc/passwd">]><PathOfBuilding2>&secret;</PathOfBuilding2>'
    with pytest.raises(BuildError, match="invalid_pob_xml"):
        project_pob(bad, "bld_"+"0"*32)
    with pytest.raises(BuildError, match="unsupported_pob_game"):
        project_pob(b'<PathOfBuilding><Build level="1"/></PathOfBuilding>', "bld_"+"0"*32)
    with pytest.raises(BuildError, match="invalid_numeric_field"):
        project_pob(xml().replace(b'value="2100"', b'value="'+code()+b'"'), "bld_"+"0"*32)


def test_raw_and_projection_roots_cannot_overlap(tmp_path):
    source = tmp_path/"input.pob";source.write_bytes(code())
    for private, projection in [(tmp_path, tmp_path), (tmp_path, tmp_path/"inner"), (tmp_path/"inner", tmp_path)]:
        with pytest.raises(BuildError, match="separate"):
            import_file(source, private, projection)


def test_projection_cannot_escape_via_symlink_or_extra_fields(tmp_path):
    build_id, private, projections, _ = imported(tmp_path)
    path = projections/(build_id+".json")
    reader = BuildReader(projections)
    data = json.loads(path.read_text())
    data["raw_code"] = code().decode()
    path.write_text(json.dumps(data))
    with pytest.raises(BuildError, match="invalid_build_projection"):
        reader.summary(build_id)
    path.unlink()
    path.symlink_to(private/(build_id+".pob"))
    with pytest.raises(BuildError, match="file_unavailable"):
        reader.summary(build_id)


async def test_mcp_never_exposes_raw_tools_resources_or_payload_errors(tmp_path, caplog):
    from mcp.shared.memory import create_connected_server_and_client_session
    build_id, _, projections, _ = imported(tmp_path)
    scout = Scout(user_agent="test", transport=httpx.MockTransport(Backend()), interval=0)
    server = build_server(scout, build_reader=BuildReader(projections))
    try:
        async with create_connected_server_and_client_session(server) as session:
            tools = (await session.list_tools()).tools
            private = [v for v in tools if v.name.startswith("get_build_")]
            assert len(tools) == 9 and len(private) == 2
            for tool in private:
                assert set(tool.inputSchema["properties"]) <= {"build_id","spec_index","offset","limit"}
                assert tool.outputSchema and tool.outputSchema["additionalProperties"] is False
            assert not (await session.list_resources()).resources
            assert not (await session.list_resource_templates()).resourceTemplates
            result = await session.call_tool("get_build_summary", {"build_id":build_id})
            assert not result.isError and result.structuredContent["level"] == 91
            for payload in [
                {"build_id":code().decode()},
                {"build_id":build_id,"pob_code":code().decode()},
                {"build_id":"../../private/input.pob"},
            ]:
                response = await session.call_tool("get_build_summary", payload)
                assert response.isError
                body = response.model_dump_json()
                assert code().decode() not in body and MARKER not in body and "private/input" not in body
            # Even a poisoned on-disk projection produces a fixed error, not a
            # Pydantic diagnostic with input_value containing code.
            path = projections/(build_id+".json")
            data = json.loads(path.read_text());data["summary"]["class_name"] = code().decode()
            path.write_text(json.dumps(data))
            response = await session.call_tool("get_build_summary", {"build_id":build_id})
            assert response.isError
            assert code().decode() not in response.model_dump_json()
            assert code().decode() not in caplog.text and MARKER not in caplog.text
    finally:
        await scout.close()
