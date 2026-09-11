"""Independent requirement aggregation oracle on native skill instances."""
import base64
import zlib
from xml.etree import ElementTree as ET
from poe2_companion.engine_protocol import WorkerRequest
from poe2_companion.requirements import RequirementsRequest, page
from test_engine_real import real_engine, FIXTURE, BID


async def test_native_maxima_support_sum_and_disabled_instance(real_engine):
    root = ET.fromstring(FIXTURE.read_bytes())
    for level in (1, 2):
        group = ET.SubElement(root.find('./Skills/SkillSet'), 'Skill', {'enabled': 'true', 'mainActiveSkill': '1'})
        for skill, enabled, gem_level in [('FireballPlayer', True, level),
                ('SupportAddedFireDamagePlayer', True, 1), ('SupportAddedColdDamagePlayer', False, 1)]:
            ET.SubElement(group, 'Gem', {'skillId': skill, 'level': str(gem_level),
                'quality': '0', 'enabled': str(enabled).lower()})
    raw = base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    (real_engine.private_dir / (BID + '.pob')).write_bytes(raw)
    value = await real_engine.calculate(WorkerRequest(build_id=BID))
    requirements = value.baseline.requirements
    assert requirements is not None
    gems = [row for row in requirements.sources if row.kind == 'native_gem' and not row.support]
    assert {row.native_level for row in gems} == {1, 2}
    assert len({row.skill_instance_id for row in gems}) == 2
    assert requirements.native_gem_maximum.intelligence == max(row.modified_attributes.intelligence for row in gems)
    # Two enabled red supports: 2 * 5, not MAX(5, 5). Disabled greens add zero.
    assert len([row for row in requirements.sources if row.support]) == 2
    assert requirements.support_sum.strength == 10
    assert requirements.support_sum.dexterity == 0
    assert requirements.engine_required.intelligence == requirements.native_gem_maximum.intelligence
    result = page(RequirementsRequest(calculation_id='calc_' + '2'*32, offset=10000), value.baseline)
    assert result.summary.sources == [] and result.next_offset is None
    assert result.total == len(requirements.sources)
    assert (real_engine.private_dir / (BID + '.pob')).read_bytes() == raw
