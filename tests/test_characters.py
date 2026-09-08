import asyncio
import json
import socket
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from poe2_companion.character_provider import CharacterProvider, provider_app
from poe2_companion.characters import (CharacterClient, CharacterRequest, AccountRequest,
    AttachmentRequest, OpenAIFile, CharacterError, account_slug)
from poe2_companion.pob_io import atomic_write
from poe2_companion.server import build_server
from poe2_companion.scout import Scout
from test_build_boundary import code, MARKER
from test_scout import Backend

TAG = "Example_#7513"
REQUEST = CharacterRequest(account_tag=TAG, character_name="테스트캐릭터", league="forbiddenrites")


class NinjaBackend:
    def __init__(self):
        self.calls = []
        self.status = 200
        self.rows = [{"accountName":TAG, "name": REQUEST.character_name, "leagueUrl": "forbiddenrites", "level": 91, "className": "Witch"}]
        self.model = {"account": TAG, "name": REQUEST.character_name, "league": "Forbidden Rites",
                      "level": 91, "class": "Witch", "pathOfBuildingExport": code().decode(),
                      "defensiveStats": {"life": 2100, "energyShield": 4300, "unknown": MARKER},
                      "updatedUtc": "2026-09-08T09:00:00Z", "notes": MARKER}

    def __call__(self, request):
        self.calls.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"message": MARKER}, headers={"retry-after": "60"})
        if "/events/" in request.url.path:
            return httpx.Response(200, content=b'data: {"version":15}\n\n', headers={"content-type":"text/event-stream"})
        if request.method == "POST":
            assert request.content == b""
            return httpx.Response(200, json={"success": True, "waitSeconds": None, "message": MARKER})
        if "/model/" in request.url.path:
            return httpx.Response(200, json={"type": "profile", "charModel": self.model})
        return httpx.Response(200, json=self.rows)


def provider(tmp_path, backend=None, files=None):
    backend = backend or NinjaBackend()
    return CharacterProvider(tmp_path/"raw", tmp_path/"safe", tmp_path/"state",
        http=httpx.AsyncClient(transport=httpx.MockTransport(backend)),
        attachment_http=httpx.AsyncClient(transport=httpx.MockTransport(files or (lambda _: httpx.Response(200, content=code())))))


async def test_account_resolution_import_dedup_and_private_projection(tmp_path):
    backend = NinjaBackend()
    p = provider(tmp_path, backend)
    result = await p.get_character(CharacterRequest(account_tag=TAG, character_name=REQUEST.character_name))
    text = result.model_dump_json()
    assert result.build.level == 91 and result.build.build_id.startswith("bld_")
    assert MARKER not in text and code().decode() not in text and "pathOfBuildingExport" not in text
    assert (p.private/(result.build.build_id+".pob")).read_bytes() == code()
    assert (await p.get_character(REQUEST)).reused
    assert len(list(p.private.glob("*.pob"))) == 1
    backend.rows += [{**backend.rows[0], "leagueUrl": "standard"}]
    with pytest.raises(CharacterError, match="ambiguous_league"):
        await p.get_character(CharacterRequest(account_tag=TAG, character_name=REQUEST.character_name))
    backend.model["account"] = "Another#1111"
    with pytest.raises(CharacterError, match="schema_changed"):
        await p.get_character(REQUEST)
    await p.close()


async def test_refresh_auth_binding_cooldown_persistence_and_redaction(tmp_path):
    backend = NinjaBackend()
    p = provider(tmp_path, backend)
    assert (await p.refresh_character(REQUEST)).status == "authentication_required"
    atomic_write(p.state/"session.json", json.dumps({"account_tag": "Other#1111", "cookie": "test=synthetic"}).encode())
    assert (await p.refresh_character(REQUEST)).status == "account_mismatch"
    atomic_write(p.state/"session.json", json.dumps({"account_tag": TAG, "cookie": "test=synthetic"}).encode())
    result = await p.refresh_character(REQUEST)
    assert result.success and result.snapshot and not result.game_fetch_confirmed
    assert MARKER not in result.model_dump_json()
    assert sum(r.method == "POST" for r in backend.calls) == 1
    assert all("cookie" not in r.headers for r in backend.calls if r.method == "GET")
    second = provider(tmp_path, backend)
    assert (await second.refresh_character(REQUEST)).status == "cooldown"
    assert sum(r.method == "POST" for r in backend.calls) == 1
    await p.close()
    await second.close()


async def test_attachment_preserves_bytes_and_blocks_ssrf_redirects_and_payloads(tmp_path, monkeypatch):
    async def public_dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", public_dns)
    original = b"\xef\xbb\xbf" + code() + b"\r\n"
    calls = []
    def files(request):
        calls.append(request)
        assert "cookie" not in request.headers and "authorization" not in request.headers
        return httpx.Response(200, content=original)
    p = provider(tmp_path, files=files)
    file = OpenAIFile(download_url="https://files.oaiusercontent.com/file/test?sig=synthetic", file_id="file_test", file_name="build.txt")
    result = await p.import_pob_attachment(AttachmentRequest(file=file))
    assert (p.private/(result.build.build_id+".pob")).read_bytes() == original
    assert code().decode() not in result.model_dump_json()
    for url in ["http://files.oaiusercontent.com/f", "https://127.0.0.1/f", "https://files.oaiusercontent.com.attacker.test/f",
                "https://files.oaiusercontent.com@127.0.0.1/f", "file:///private-builds/input.pob"]:
        with pytest.raises(CharacterError, match="host_not_allowed"):
            await p.import_pob_attachment(AttachmentRequest(file=file.model_copy(update={"download_url": url})))
    assert len(calls) == 1
    async def private_dns(*a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", private_dns)
    with pytest.raises(CharacterError, match="host_not_allowed"):
        await p.import_pob_attachment(AttachmentRequest(file=file))
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", public_dns)
    await p.attachment_http.aclose()
    p.attachment_http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(302, headers={"location":"http://127.0.0.1/"})))
    with pytest.raises(CharacterError, match="attachment_unavailable"):
        await p.import_pob_attachment(AttachmentRequest(file=file))
    await p.close()


async def test_mcp_file_schema_and_invalid_inputs_never_echo_payload(tmp_path, caplog, monkeypatch):
    p = provider(tmp_path)
    rpc = CharacterClient("unused", http=httpx.AsyncClient(transport=httpx.ASGITransport(app=provider_app(p)), base_url="http://provider"))
    scout = Scout(user_agent="test", cache_path=tmp_path/"prices.db", transport=httpx.MockTransport(Backend()))
    server = build_server(scout, characters=rpc)
    tools = {t.name:t for t in await server.list_tools()}
    tool = tools["import_pob_attachment"]
    assert tool.meta["openai/fileParams"] == ["file"]
    schema = tool.inputSchema
    file_schema = schema["$defs"]["OpenAIFile"]
    assert set(file_schema["required"]) == {"download_url", "file_id"}
    assert set(file_schema["properties"]) == {"download_url", "file_id", "mime_type", "file_name"}
    assert not tool.annotations.readOnlyHint and not tools["refresh_character"].annotations.idempotentHint
    async def public_dns(*a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", public_dns)
    result = await server.call_tool("import_pob_attachment", {"file": {
        "download_url": "https://files.oaiusercontent.com/file/test?sig=do-not-return",
        "file_id": "file_test", "file_name": "build.txt", "mime_type": "text/plain"}})
    # FastMCP's successful direct call returns content + structured projection.
    serialized = str(result)
    assert "bld_" in serialized and code().decode() not in serialized
    assert "do-not-return" not in serialized and MARKER not in serialized
    for name, arguments in [("get_character", {"request":{"account_tag":TAG,"character_name":MARKER}}),
                            ("import_pob_attachment", {"file":{"content":code().decode()}}),
                            ("get_character", {"request": REQUEST.model_dump(), "raw": MARKER})]:
        result = await server.call_tool(name, arguments)
        assert result.isError and MARKER not in str(result) and code().decode() not in str(result)
    response = await rpc.http.post("/get_character", json={**REQUEST.model_dump(), "raw": MARKER})
    assert response.status_code == 400 and MARKER not in response.text
    assert MARKER not in caplog.text
    await rpc.close()
    await p.close()
    await scout.close()


async def test_streamed_versions_are_bounded_and_close_after_first_data(tmp_path):
    class Events(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            yield b': ping\r\n\r'
            yield b'\ndata: {"version":'
            yield b'26}\r\n\r\n'
            pytest.fail("Version consumer kept the SSE connection open")
        async def aclose(self):
            self.closed = True
    events = Events()
    p = provider(tmp_path)
    await p.http.aclose()
    p.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
        stream=events, headers={"content-type":"text/event-stream"})))
    assert await p.version("characters/Example_-7513") == 26 and events.closed
    await p.http.aclose()
    p.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
        content=b": ping\n\n"*3000, headers={"content-type":"text/event-stream"})))
    with pytest.raises(CharacterError, match="schema_changed"):
        await p.version("characters/Example_-7513")
    await p.close()


async def test_import_quota_and_dedup_are_private_per_user(tmp_path):
    first, second = provider(tmp_path/"owner"), provider(tmp_path/"guest1")
    a, reused = first.store(code())
    b, _ = second.store(code())
    assert not reused and a.build_id != b.build_id
    assert not (second.private/(a.build_id+".pob")).exists()
    for i in range(499):
        (first.private/f"bld_quota{i}.pob").touch()
    assert first.store(code())[1]  # Dedup is permitted at capacity.
    with pytest.raises(CharacterError, match="storage_full"):
        first.store(code()+b"\n")
    from poe2_companion.pob_io import MAX_CODE_BYTES
    with pytest.raises(CharacterError, match="too_large"):
        first.store(b"x"*(MAX_CODE_BYTES+1))
    await first.close()
    await second.close()


@pytest.mark.parametrize("status,error", [(401,"authentication_required"),(403,"authentication_required"),(429,"rate_limited"),(500,"unavailable")])
async def test_upstream_errors_are_fixed_and_no_retry(tmp_path, status, error):
    b = NinjaBackend()
    b.status = status
    p = provider(tmp_path,b)
    with pytest.raises(CharacterError, match=error):
        await p.get_character(REQUEST)
    assert len(b.calls) == 1
    if status == 429:
        with pytest.raises(CharacterError, match="rate_limited"):
            await p.get_character(REQUEST)
        assert len(b.calls) == 1
    await p.close()


def test_identifiers_and_removed_host_file_import():
    assert account_slug(TAG) == "Example_-7513"
    for tag in ["https://example.com", "../foo#7513", "hello\n#7513", MARKER]:
        with pytest.raises(ValueError): account_slug(tag)
    for name in ["../secret", "foo%2fbar", MARKER]:
        with pytest.raises(ValidationError): CharacterRequest(account_tag=TAG,character_name=name)
    root = Path(__file__).resolve().parents[1]
    assert 'sub.add_parser("import-build"' not in (root/"scripts/mac.py").read_text()
    assert "poe2-pob-files =" not in (root/"pyproject.toml").read_text()


# Synthetic Ninja payloads exercise structural joins without any character data.
def beast_fixture():
    import base64
    import xml.etree.ElementTree as ET
    import zlib
    from test_build_boundary import xml
    root = ET.fromstring(xml())
    ET.SubElement(root.find('Build'), 'BeastCompanion', {'id': 'Metadata/Monsters/Quadrilla/Quadrilla'})
    section = root.find('Skills')
    section.clear()
    section.set('activeSkillSet', '1')
    skill_set = ET.SubElement(section, 'SkillSet', {'id': '1'})
    support_sets = [
        [('Rapid Attacks II', 'SupportRapidAttacksPlayerTwo'), ('Rage III', 'SupportRagePlayerThree'),
         ('Muster', 'SupportMusterPlayer'), ('Loyalty', 'SupportLoyaltyPlayer')],
        [('Rapid Attacks II', 'SupportRapidAttacksPlayerTwo'), ('Rage III', 'SupportRagePlayerThree'),
         ('Feeding Frenzy II', 'SupportFeedingFrenzyPlayerTwo'), ('Loyalty', 'SupportLoyaltyPlayer')],
    ]
    groups = []
    for index, supports in enumerate(support_sets):
        skill = ET.SubElement(skill_set, 'Skill', {'enabled': 'true', 'mainActiveSkill': '1'})
        ET.SubElement(skill, 'Gem', {'nameSpec': 'Companion: Quadrilla', 'skillId': 'SummonBeastPlayer', 'skillMinion': 'Metadata/Monsters/Quadrilla/Quadrilla', 'level': '18', 'quality': '0', 'enabled': 'true'})
        labels = ('[public_link|Extra Physical Damage Aura]\n[public_link|Breaks Armour]' if index == 0
                  else '[public_link|Haste Aura]\n[public_link|All Damage Chills]')
        gems = [{'name': 'Companion: Quadrilla', 'level': 18, 'quality': 0,
            'itemData': {'id': 'private-synthetic-' + str(index), 'support': False, 'gemSkill': 'noncanonical display',
                'name': 'Companion: Quadrilla', 'baseType': 'Companion: Quadrilla', 'typeLine': 'Companion: Quadrilla',
                'tamedBeastProperties': [{'name': 'PRIVATE_BEAST_PROPERTY', 'displayMode': 3, 'values': [[labels, 0]]}]}}]
        for name, identifier in supports:
            ET.SubElement(skill, 'Gem', {'nameSpec': name, 'skillId': identifier, 'level': '1', 'quality': '0', 'enabled': 'true'})
            # Ninja support levels differ from the XML and are not identity.
            gems.append({'name': name, 'level': 0, 'quality': 0, 'itemData': {'support': True}})
        groups.append({'allGems': gems})
    encoded = base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))).rstrip(b'=')
    return encoded, groups


async def test_beast_ingestion_unique_signatures_private_ids_and_immutable_dedup(tmp_path, caplog):
    from poe2_companion.beast_metadata import validate_beast_metadata
    original, groups = beast_fixture()
    backend = NinjaBackend()
    backend.model.update(pathOfBuildingExport=original.decode(), skills=list(reversed(groups)))
    p = provider(tmp_path, backend)
    result = await p.get_character(REQUEST)
    path = p.private / (result.build.build_id + '.beasts.json')
    before = path.read_bytes()
    metadata = validate_beast_metadata(before, original)
    assert metadata['species_verified'] is True and metadata['unresolved_records'] == 0
    assert [(row['skill_group'], row['mod_ids']) for row in metadata['gems']] == [
        (1, ['PlayerMonsterArmourPenetration1', 'PlayerMonsterPhysicalDamageAura1']),
        (2, ['PlayerMonsterFreezeDamageIncrease1', 'PlayerMonsterIncreasedSpeedAura1'])]
    assert all(row['complete'] for row in metadata['gems'])
    assert all(row['species_id'] == 'Metadata/Monsters/Quadrilla/Quadrilla' for row in metadata['gems'])
    assert MARKER.encode() not in before and b'PRIVATE_BEAST_PROPERTY' not in before and b'private-synthetic' not in before and b'public_link' not in before
    assert (p.private / (result.build.build_id + '.pob')).read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(p.projections.glob('*.beasts.json'))
    assert (await p.get_character(REQUEST)).reused
    assert MARKER not in result.model_dump_json() and original.decode() not in result.model_dump_json()
    groups[0]['allGems'][0]['itemData']['tamedBeastProperties'][0]['values'][0][0] = 'Hasted'
    refreshed = await p.get_character(REQUEST)
    assert not refreshed.reused and refreshed.build.build_id != result.build.build_id
    assert path.read_bytes() == before  # Previously imported identity is immutable.
    assert (p.private / (refreshed.build.build_id + '.pob')).read_bytes() == original
    assert (await p.get_character(REQUEST)).reused
    assert MARKER not in caplog.text
    await p.close()


def test_beast_join_rejects_model_and_export_ambiguity_unknown_support_and_wrong_roman_tier():
    import base64
    import copy
    import xml.etree.ElementTree as ET
    import zlib
    from poe2_companion.beast_metadata import build_beast_metadata
    from poe2_companion.pob_io import decode_pob
    original, groups = beast_fixture()
    model = {'skills': groups + [copy.deepcopy(groups[0])]}
    metadata = json.loads(build_beast_metadata(model, original))
    assert metadata['unresolved_records'] == 2
    assert [row['skill_group'] for row in metadata['gems']] == [2]
    root = ET.fromstring(decode_pob(original))
    skill_set = root.find('./Skills/SkillSet')
    skill_set.append(copy.deepcopy(skill_set[0]))
    duplicate_xml = base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))).rstrip(b'=')
    metadata = json.loads(build_beast_metadata({'skills': groups}, duplicate_xml))
    assert metadata['unresolved_records'] == 1
    assert [row['skill_group'] for row in metadata['gems']] == [2]
    for name in ['unrecognised support', 'Rapid Attacks I']:
        changed = copy.deepcopy(groups)
        changed[0]['allGems'][1]['name'] = name
        metadata = json.loads(build_beast_metadata({'skills': changed}, original))
        assert not any(row['skill_group'] == 1 for row in metadata['gems'])
        assert metadata['unresolved_records'] >= 1
    root = ET.fromstring(decode_pob(original))
    root.find('./Skills/SkillSet/Skill/Gem[@skillId="SupportRapidAttacksPlayerTwo"]').set('skillId', 'SupportRapidAttacksPlayer')
    conflicting_xml = base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))).rstrip(b'=')
    metadata = json.loads(build_beast_metadata({'skills': groups}, conflicting_xml))
    assert metadata['unresolved_records'] == 2 and metadata['gems'] == []
    root = ET.fromstring(decode_pob(original))
    root.find('./Skills/SkillSet/Skill/Gem').set('skillMinion', 'Metadata/Monsters/GoreCharger/GoreCharger')
    mismatched_species = base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))).rstrip(b'=')
    metadata = json.loads(build_beast_metadata({'skills': groups}, mismatched_species))
    assert metadata['unresolved_records'] == 2 and metadata['gems'] == []
    root = ET.fromstring(decode_pob(original))
    root.find('./Skills').append(copy.deepcopy(root.find('./Skills/SkillSet/Skill')))
    legacy = base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))).rstrip(b'=')
    metadata = json.loads(build_beast_metadata({'skills': groups}, legacy))
    assert metadata['unresolved_records'] == 2 and metadata['gems'] == []


def test_beast_unknown_modifiers_stay_partial_and_tampered_sidecar_is_rejected():
    import copy
    from poe2_companion.beast_metadata import build_beast_metadata, validate_beast_metadata, BeastMetadataError
    original, groups = beast_fixture()
    groups[0]['allGems'][0]['itemData']['tamedBeastProperties'][0]['values'][0][0] = 'Hasted\n' + MARKER
    encoded = build_beast_metadata({'skills': groups}, original)
    value = validate_beast_metadata(encoded, original)
    assert value['gems'][0]['mod_ids'] == ['PlayerMonsterIncreasedSpeed1']
    assert not value['gems'][0]['complete'] and MARKER.encode() not in encoded
    for mutate in [lambda data: data['gems'][0].update(skill_group=2),
                   lambda data: data['gems'][0].update(mod_ids=[MARKER]),
                   lambda data: data['gems'][0].update(mod_ids=['PlayerMonsterIncreasedSpeed1'] * 2),
                   lambda data: data.update(export_sha256='0'*64),
                   lambda data: data.update(provenance=MARKER)]:
        corrupted = copy.deepcopy(value)
        mutate(corrupted)
        with pytest.raises(BeastMetadataError, match='^invalid_beast_metadata$'):
            validate_beast_metadata(json.dumps(corrupted).encode(), original)
    with pytest.raises(BeastMetadataError, match='^invalid_beast_metadata$'):
        validate_beast_metadata(encoded, original + b'\n')


@pytest.mark.parametrize('mismatch', ['missing_selection', 'missing_declaration', 'calcs_species', 'duplicate_set'])
def test_beast_export_identity_never_uses_engine_first_beast_fallback(mismatch):
    import base64
    import copy
    import xml.etree.ElementTree as ET
    import zlib
    from poe2_companion.beast_metadata import build_beast_metadata
    from poe2_companion.pob_io import decode_pob
    original, groups = beast_fixture()
    root = ET.fromstring(decode_pob(original))
    gem = root.find('./Skills/SkillSet/Skill/Gem')
    if mismatch == 'missing_selection':
        del gem.attrib['skillMinion']
    elif mismatch == 'missing_declaration':
        root.find('Build').remove(root.find('./Build/BeastCompanion'))
    elif mismatch == 'calcs_species':
        gem.set('skillMinionCalcs', 'Metadata/Monsters/GoreCharger/GoreCharger')
    else:
        root.find('Skills').append(copy.deepcopy(root.find('./Skills/SkillSet')))
    encoded = base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))).rstrip(b'=')
    metadata = json.loads(build_beast_metadata({'skills': groups}, encoded))
    assert metadata['gems'] == [] and metadata['unresolved_records'] == 2


async def test_beast_sidecar_schema_limits_and_failed_storage_leave_no_import(tmp_path, monkeypatch):
    import poe2_companion.character_provider as module
    original, groups = beast_fixture()
    backend = NinjaBackend()
    backend.model.update(pathOfBuildingExport=original.decode(), skills=groups)
    p = provider(tmp_path, backend)
    raw = groups[0]['allGems'][0]['itemData']['tamedBeastProperties'][0]['values'][0][0]
    groups[0]['allGems'][0]['itemData']['tamedBeastProperties'][0]['values'][0][0] = MARKER * 500
    with pytest.raises(CharacterError, match='schema_changed'):
        await p.get_character(REQUEST)
    groups[0]['allGems'][0]['itemData']['tamedBeastProperties'][0]['values'][0][0] = raw
    writer = module.atomic_write
    def fail_sidecar(path, content):
        if path.name.endswith('.beasts.json'):
            raise OSError('synthetic-write-failure')
        writer(path, content)
    monkeypatch.setattr(module, 'atomic_write', fail_sidecar)
    with pytest.raises(CharacterError, match='import_unavailable'):
        await p.get_character(REQUEST)
    assert not list(p.private.glob('bld_*')) and not list(p.projections.glob('bld_*'))
    assert not list(p.state.glob('import-*'))
    monkeypatch.setattr(module, 'atomic_write', writer)
    assert (await p.get_character(REQUEST)).build.build_id
    await p.close()


async def test_beast_dedup_integrity_and_user_isolation(tmp_path):
    original, groups = beast_fixture()
    backend = NinjaBackend()
    backend.model.update(pathOfBuildingExport=original.decode(), skills=groups)
    owner, guest = provider(tmp_path/'owner', backend), provider(tmp_path/'guest1', backend)
    first, other = await owner.get_character(REQUEST), await guest.get_character(REQUEST)
    assert first.build.build_id != other.build.build_id
    sidecar = owner.private/(first.build.build_id+'.beasts.json')
    sidecar.write_bytes(b'{}')
    repaired = await owner.get_character(REQUEST)
    assert not repaired.reused and repaired.build.build_id != first.build.build_id
    assert sidecar.read_bytes() == b'{}'  # No silent mutation of existing IDs.
    assert (await guest.get_character(REQUEST)).reused
    # The TXT-only import path retains exact bytes and does not acquire Ninja
    # metadata from a separate earlier import, even when code bytes are equal.
    attachment, reused = owner.store(original)
    assert not reused and not (owner.private/(attachment.build_id+'.beasts.json')).exists()
    assert owner.store(original)[1]
    await owner.close()
    await guest.close()
