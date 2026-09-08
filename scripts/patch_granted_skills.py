"""Backport only granted-skill level resolution from upstream PR2498.

Source: PathOfBuildingCommunity/PathOfBuilding-PoE2#2498,
head 86acf81e6f8019f16c6867d78424aee8b749b23f, Modules/CalcSetup.lua.
The broad weapon-context, import, UI and default-attack rewrite is excluded.
"""
from pathlib import Path


def _replace(path: Path, old: str, new: str) -> None:
    source = path.read_text()
    if source.count(old) != 1:
        raise SystemExit("upstream_granted_skill_level_patch_mismatch")
    path.write_text(source.replace(old, new))


def patch_granted_skills(destination: Path) -> None:
    target = destination / "src/Modules/CalcSetup.lua"
    anchor = "local function getNormalizedSkillLevel(grantedSkill)"
    helper = '''-- PoE2Companion: narrow granted-skill level backport (upstream PR2498).
-- Source levels are caps, not ordinary socketed-gem requirements. Equipment
-- requirement exemptions do not exempt a granted skill's attributes.
local function getGrantedSkillLevel(gemData, maxLevel, characterLevel, modDB)
\tlocal str, dex, int
\tif modDB then
\t\tstr = m_max(round(calcLib.val(modDB, "Str")), 0)
\t\tdex = m_max(round(calcLib.val(modDB, "Dex")), 0)
\t\tint = m_max(round(calcLib.val(modDB, "Int")), 0)
\tend
\tfor level = maxLevel, 1, -1 do
\t\tlocal levelData = gemData.grantedEffect.levels[level]
\t\tlocal levelRequirement = levelData and levelData.levelRequirement
\t\tif levelRequirement and levelRequirement <= characterLevel and (not modDB
\t\t\tor calcLib.getGemStatRequirement(levelRequirement, gemData.reqStr, false) <= str
\t\t\tand calcLib.getGemStatRequirement(levelRequirement, gemData.reqDex, false) <= dex
\t\t\tand calcLib.getGemStatRequirement(levelRequirement, gemData.reqInt, false) <= int) then
\t\t\treturn level
\t\tend
\tend
\treturn 1
end

'''
    _replace(target, anchor, helper + anchor)

    # A tree grant has no item source cap: the canonical natural maximum is
    # constrained by character level. Keep the original group identity when
    # it changes, so saved enabled states and supports do not disappear.
    anchor = '\t\t\tfor _, grantedSkill in ipairs(env.grantedSkills) do\n'
    tree_level = '''\t\t\t\tif grantedSkill.sourceNode then
\t\t\t\t\tlocal effect = data.skills[grantedSkill.skillId]
\t\t\t\t\tlocal gemData = effect and data.gems[data.gemForSkill[effect]]
\t\t\t\t\tif gemData then
\t\t\t\t\t\tgrantedSkill.level = getGrantedSkillLevel(gemData, gemData.naturalMaxLevel, build.characterLevel)
\t\t\t\t\tend
\t\t\t\tend
'''
    _replace(target, anchor, anchor + tree_level)
    old = 'and (socketGroup.gemList[1].level == grantedSkill.level or socketGroup.gemList[1].level == getNormalizedSkillLevel(grantedSkill))'
    new = 'and (socketGroup.sourceItem or socketGroup.sourceNode or socketGroup.gemList[1].level == grantedSkill.level or socketGroup.gemList[1].level == getNormalizedSkillLevel(grantedSkill))'
    _replace(target, old, new)
    anchor = '\t\t\t\tactiveGemInstance.fromItem = grantedSkill.sourceItem ~= nil\n'
    _replace(target, anchor, anchor + '''\t\t\t\tactiveGemInstance.fromNode = grantedSkill.sourceNode ~= nil
\t\t\t\tactiveGemInstance.sourceLevel = grantedSkill.sourceItem and grantedSkill.level or nil
''')
    # Unlike an explosion group, a granted skill group may contain supports.
    # The source remains first; updating its level must preserve those inputs.
    old = '\t\t\t\twipeTable(group.gemList)\n\t\t\t\tt_insert(group.gemList, activeGemInstance)\n\t\t\t\tbuild.skillsTab:ProcessSocketGroup(group)'
    new = '\t\t\t\tgroup.gemList[1] = activeGemInstance\n\t\t\t\tbuild.skillsTab:ProcessSocketGroup(group)'
    _replace(target, old, new)

    # Resolve before active effects and supports are built in every full
    # calculation, including CALCS and item comparisons. Only the active
    # source slot uses the current weapon-context attribute database.
    anchor = '\t\t\tgroup.slotEnabled = not slot or not slot.weaponSet or slot.weaponSet == (build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1)\n'
    level_group = '''\t\t\tlocal sourceGem = group.gemList[1]
\t\t\t-- Older imports save a supported explicit group beside the generated
\t\t\t-- source group. Resolve only canonical item/tree-only skills, and only
\t\t\t-- when their current source is unambiguous; ordinary gems are untouched.
\t\t\tif sourceGem and sourceGem.companionGrantMirror then
\t\t\t\tsourceGem.fromItem, sourceGem.fromNode, sourceGem.sourceLevel = nil, nil, nil
\t\t\t\tsourceGem.companionGrantMirror = nil
\t\t\tend
\t\t\tlocal effect = sourceGem and sourceGem.gemData and sourceGem.gemData.grantedEffect
\t\t\tif sourceGem then sourceGem.companionGrantLevelUnresolved = nil end
\t\t\tif not group.source and effect and (effect.fromItem or effect.fromTree) then
\t\t\t\tlocal matched, count = nil, 0
\t\t\t\tfor _, grant in ipairs(env.grantedSkills) do
\t\t\t\t\tlocal grantSlot = grant.slotName and build.itemsTab.slots[grant.slotName]
\t\t\t\t\tlocal activeSource = not grantSlot or not grantSlot.weaponSet or grantSlot.weaponSet == (build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1)
\t\t\t\t\tif grant.skillId == effect.id and (effect.fromItem and grant.sourceItem or effect.fromTree and grant.sourceNode)
\t\t\t\t\t\tand activeSource and (grant.sourceNode or not group.slot or group.slot == grant.slotName) then
\t\t\t\t\t\tmatched, count = grant, count + 1
\t\t\t\t\tend
\t\t\t\tend
\t\t\t\tif count == 1 then
\t\t\t\t\tsourceGem.fromItem, sourceGem.fromNode = matched.sourceItem ~= nil, matched.sourceNode ~= nil
\t\t\t\t\tsourceGem.sourceLevel = matched.sourceItem and matched.level or nil
\t\t\t\t\tsourceGem.companionGrantMirror = true
\t\t\t\telse
\t\t\t\t\tsourceGem.companionGrantLevelUnresolved = true
\t\t\t\tend
\t\t\tend
\t\t\tif sourceGem and sourceGem.gemData and (sourceGem.fromNode or sourceGem.fromItem and sourceGem.sourceLevel and group.slotEnabled) then
\t\t\t\tlocal level = getGrantedSkillLevel(sourceGem.gemData,
\t\t\t\t\tsourceGem.fromNode and sourceGem.gemData.naturalMaxLevel or sourceGem.sourceLevel,
\t\t\t\t\tbuild.characterLevel, not sourceGem.fromNode and env.modDB or nil)
\t\t\t\tif sourceGem.level ~= level then
\t\t\t\t\tsourceGem.level = level
\t\t\t\t\tlocal grantedEffect = sourceGem.gemData.grantedEffect
\t\t\t\t\tsourceGem.reqLevel = grantedEffect.levels[level].levelRequirement
\t\t\t\t\tsourceGem.reqStr = calcLib.getGemStatRequirement(sourceGem.reqLevel, sourceGem.gemData.reqStr, false)
\t\t\t\t\tsourceGem.reqDex = calcLib.getGemStatRequirement(sourceGem.reqLevel, sourceGem.gemData.reqDex, false)
\t\t\t\t\tsourceGem.reqInt = calcLib.getGemStatRequirement(sourceGem.reqLevel, sourceGem.gemData.reqInt, false)
\t\t\t\tend
\t\t\tend
'''
    _replace(target, anchor, anchor + level_group)
