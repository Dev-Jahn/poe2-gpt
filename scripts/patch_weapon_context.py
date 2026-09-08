"""Preserve explicit saved per-skill weapon selectors from upstream PR #2498.

This is deliberately not a backport of the PR's cross-skill environments.
The private adapter resolves only a single provable shared context and
diagnoses mixed contexts. Source: https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/pull/2498
"""
from pathlib import Path


def patch_weapon_context(destination: Path) -> None:
    target = destination / 'src/Classes/SkillsTab.lua'
    source = target.read_text()
    old = '\tsocketGroup.slot = node.attrib.slot\n\tsocketGroup.source = node.attrib.source\n'
    new = old + '''\t-- Preserve explicit saved selectors for the private context adapter.
\tfor _, key in ipairs({ "set1", "set2" }) do
\t\tlocal value = node.attrib[key]
\t\tif value ~= nil then
\t\t\tif value == "true" or value == "false" then socketGroup[key] = value == "true"
\t\t\telse socketGroup.companionInvalidWeaponContext = true end
\t\tend
\tend
'''
    if source.count(old) != 1 or new in source:
        raise SystemExit('upstream_weapon_context_patch_mismatch')
    updated = source.replace(old, new)
    setup = destination / 'src/Modules/CalcSetup.lua'
    setup_source = setup.read_text()
    anchor = 'local tempTable1 = { }\n'
    helper = '''-- Shared effective-skill scope for private compatibility calculations.
function calcs.companionIsActiveSkill(env, activeSkill)
\tif not activeSkill or activeSkill.disableReason then return false end
\tlocal effect = activeSkill.activeEffect
\tlocal selected = effect and (env.mode == "CALCS" and effect.statSetCalcs or effect.statSet)
\tlocal flags = selected and selected.skillFlags or activeSkill.skillFlags
\tif flags and flags.disable then return false end
\tif activeSkill == env.player.mainSkill then return true end
\tlocal group = activeSkill.socketGroup
\tif not group then return true end
\tlocal set = env.build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1
\treturn group.enabled and group.slotEnabled ~= false and group["set" .. set] ~= false and not group.companionInvalidWeaponContext
end

'''
    if setup_source.count(anchor) != 1 or 'function calcs.companionIsActiveSkill(' in setup_source:
        raise SystemExit('upstream_weapon_context_patch_mismatch')
    target.write_text(updated)
    setup.write_text(setup_source.replace(anchor, helper + anchor))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    patch_weapon_context(parser.parse_args().destination)
