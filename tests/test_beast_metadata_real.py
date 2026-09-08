"""Ninja supplement through the private worker; synthetic exports only."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET
import zlib

import pytest

from poe2_companion.beast_metadata import build_beast_metadata, validate_beast_metadata
from poe2_companion.engine_models import EngineError
from poe2_companion.engine_protocol import WorkerRequest
from poe2_companion.engine_worker import PrivateEngine
from poe2_companion.pob_io import decode_pob
from test_characters import beast_fixture
from test_companions_real import modifiers
from test_engine_real import FIXTURE, MARKER, change, val

PLAIN = 'bld_' + '3' * 32
CAPTURED = 'bld_' + '4' * 32
BOAR = 'Metadata/Monsters/GoreCharger/GoreCharger'


def synthetic_pair(main_group):
    encoded, model_groups = beast_fixture()
    template = ET.fromstring(decode_pob(encoded))
    root = ET.fromstring(FIXTURE.read_bytes())
    root.find('Build').set('mainSocketGroup', str(main_group))
    for beast in template.findall('./Build/BeastCompanion'):
        root.find('Build').append(copy.deepcopy(beast))
    ET.SubElement(root.find('Build'), 'BeastCompanion', {'id': BOAR})
    root.remove(root.find('Skills'))
    root.append(copy.deepcopy(template.find('Skills')))
    second = root.findall('./Skills/SkillSet/Skill')[1][0]
    second.set('nameSpec', 'Companion: Diretusk Boar')
    second.set('skillMinion', BOAR)
    active = model_groups[1]['allGems'][0]
    active['name'] = 'Companion: Diretusk Boar'
    for field in ('name', 'baseType', 'typeLine'):
        active['itemData'][field] = active['name']
    root.find("./Calcs/Input[@name='skill_number']").set('number', str(main_group))
    root.find('Notes').text = MARKER
    modifiers(root, ['You can have two Companions of different types',
                     '+300 to Strength', '+300 to Dexterity', '+300 to Intelligence'])
    original = base64.urlsafe_b64encode(zlib.compress(ET.tostring(root))).rstrip(b'=')
    # Neither the model ordering nor synthetic model item IDs identify a PoB
    # gem. The complete canonical species/support signatures perform the join.
    sidecar = build_beast_metadata({'skills': list(reversed(model_groups))}, original)
    return original, sidecar


@pytest.fixture
def private_worker(tmp_path):
    source = os.environ.get('POE2_TEST_ENGINE_DIR')
    if not source:
        pytest.skip('Set POE2_TEST_ENGINE_DIR for real Lua integration')
    return PrivateEngine(tmp_path, Path(source), os.environ.get('POE2_TEST_LUAJIT', 'luajit'))


@pytest.mark.parametrize('main_group', [1, 2])
async def test_real_beast_sidecar_associations_replay_and_original_immutability(private_worker, main_group):
    worker = private_worker
    original, encoded = synthetic_pair(main_group)
    metadata = validate_beast_metadata(encoded, original)
    assert metadata['unresolved_records'] == 0
    assert [(row['skill_group'], row['species_id']) for row in metadata['gems']] == [
        (1, 'Metadata/Monsters/Quadrilla/Quadrilla'), (2, BOAR)]
    for bid in (PLAIN, CAPTURED):
        (worker.private_dir / (bid + '.pob')).write_bytes(original)
    path = worker.private_dir / (CAPTURED + '.beasts.json')
    path.write_bytes(encoded)
    baseline = (await worker.calculate(WorkerRequest(build_id=PLAIN))).baseline
    captured = await worker.calculate(WorkerRequest(build_id=CAPTURED,
        scenarios=[[change('ring_right', mods=['+100 to maximum Life'])]]))
    expected = (await worker.calculate(WorkerRequest(build_id=PLAIN, configuration={
        'captured_beast_mods': [{key: row[key] for key in ('skill_group', 'mod_ids', 'complete')}
                               for row in metadata['gems']]}))).baseline
    assert val(captured.baseline, 'MinionCombinedDPS') > val(baseline, 'MinionCombinedDPS')
    assert val(captured.baseline, 'MinionCombinedDPS') == pytest.approx(val(expected, 'MinionCombinedDPS'))
    assert val(captured.results[0], 'MinionCombinedDPS') == pytest.approx(val(captured.baseline, 'MinionCombinedDPS'))
    assert val(captured.baseline, 'MinionSpeed') == pytest.approx(val(expected, 'MinionSpeed'))
    assert val(captured.baseline, 'Life') == val(baseline, 'Life')
    assert val(captured.results[0], 'Life') > val(captured.baseline, 'Life')
    mechanics = {row.mechanic: row for row in captured.baseline.mechanics}
    metrics = {row.name: row.value for row in mechanics['tamed_beast_modifiers'].metrics}
    assert metrics['configured_tamed_beasts'] == 2
    assert metrics['captured_beast_modifiers_applied'] == 4
    # Aura propagation and minimum chill potency remain explicitly incomplete.
    assert mechanics['tamed_beast_modifiers'].status == 'partial'
    assert 'captured_beast_modifiers' not in mechanics['tamed_beast_modifiers'].required_inputs
    assert not any(issue.code == 'missing_companion_data' for issue in captured.baseline.issues)
    result_text = captured.model_dump_json()
    for private_value in (MARKER, original.decode(), 'PRIVATE_BEAST_PROPERTY', 'private-synthetic'):
        assert private_value not in result_text
    assert path.read_bytes() == encoded
    expected_hash = hashlib.sha256(original).hexdigest()
    assert all(hashlib.sha256((worker.private_dir / (bid + '.pob')).read_bytes()).hexdigest()
               == expected_hash for bid in (PLAIN, CAPTURED))


@pytest.mark.parametrize('invalid', ['coordinate', 'export_hash', 'unknown_id', 'symlink', 'dangling_symlink'])
async def test_private_worker_rejects_unbound_or_symlink_beast_supplements(private_worker, invalid):
    worker = private_worker
    original, encoded = synthetic_pair(2)
    original_path = worker.private_dir / (CAPTURED + '.pob')
    original_path.write_bytes(original)
    sidecar_path = worker.private_dir / (CAPTURED + '.beasts.json')
    if invalid.endswith('symlink'):
        target = worker.private_dir / 'synthetic-target.json'
        if invalid == 'symlink':
            target.write_bytes(encoded)
        sidecar_path.symlink_to(target)
    else:
        value = json.loads(encoded)
        if invalid == 'coordinate':
            value['gems'][0]['skill_group'] = 2
        elif invalid == 'export_hash':
            value['export_sha256'] = '0' * 64
        else:
            value['gems'][0]['mod_ids'] = [MARKER]
        sidecar_path.write_text(json.dumps(value))
    with pytest.raises(EngineError, match='^engine_invalid_build$'):
        await worker.calculate(WorkerRequest(build_id=CAPTURED))
    assert original_path.read_bytes() == original


def test_real_missing_calcs_selector_binds_verified_second_species(private_worker, tmp_path):
    original, sidecar = synthetic_pair(2)
    module = Path(__file__).parents[1] / 'src/poe2_companion/lua/beast_metadata.lua'
    probe = tmp_path / 'beast-calcs.lua'
    probe.write_text("""print = function() end
local json = require('dkjson')
local input = assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
loadBuildFromXML(input.xml, '')
local gem = build.skillsTab.socketGroupList[2].gemList[1]
local before = gem.skillMinionCalcs
local module = dofile(input.module)
assert(module.apply(build, input.metadata))
if GlobalCache and GlobalCache.cachedData then wipeGlobalCache() end
build.buildFlag = true; runCallback('OnFrame')
io.write(json.encode({before=before, after=gem.skillMinionCalcs,
 main_species=build.calcsTab.mainEnv.minion.type,
 calcs_species=build.calcsTab.calcsEnv.minion.type}))
""")
    env = dict(os.environ)
    env['LUA_PATH'] = (str(private_worker.engine_dir / 'runtime/lua/?.lua') + ';'
                       + str(private_worker.engine_dir / 'runtime/lua/?/init.lua') + ';;')
    result = subprocess.run([private_worker.luajit, str(probe)],
        cwd=private_worker.engine_dir / 'src', env=env, capture_output=True, text=True, timeout=30,
        input=json.dumps({'xml': decode_pob(original).decode(), 'metadata': json.loads(sidecar), 'module': str(module)}))
    assert result.returncode == 0, result.stderr[-1000:]
    value = json.loads(result.stdout)
    assert value['before'] == 'Metadata/Monsters/Quadrilla/Quadrilla'
    assert value['after'] == value['main_species'] == value['calcs_species'] == BOAR
