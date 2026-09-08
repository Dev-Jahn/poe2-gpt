"""Narrow, source-anchored fixes identified during the 0.10 upstream audit.

Reviewed PR heads (PathOfBuildingCommunity/PathOfBuilding-PoE2):
2378: 62bc351fc6b189dc5133d6aad4fd244731ccf4d8 (enemy conditions)
2367: 3e40574e26628dc0f29cc8c20748e0d31a3c8310 (item spec round trips)
2381: 51dd1aa2a5a1c657bece8c6170833d2081fd5d72 (Baryanic Leylines)

The radius patch affects headless calculations, including allocation overrides;
desktop drawing and tooltip changes are deliberately excluded.
"""
from pathlib import Path


def patch_upstream_fixes(destination: Path) -> None:
    prepared = {}

    def replace(relative: str, old: str, new: str) -> None:
        path = destination / relative
        source = prepared.get(path, path.read_text())
        if source.count(old) != 1 or new in source:
            raise SystemExit("upstream_small_fixes_patch_mismatch")
        prepared[path] = source.replace(old, new)

    replace("src/Modules/ModParser.lua", '''\t["^enemies you (%a+) have "] = function(cond)
\t\treturn { tag = { type = "Condition", var = cond:gsub("^%a", string.upper) }, applyToEnemy = true }
\tend,''', '''\t["^enemies you (%a+) have "] = function(cond)
\t\t-- The grammatical verb is not the canonical actor condition.
\t\tlocal conditions = { curse = "Cursed", mark = "Marked", electrocute = "Electrocuted" }
\t\treturn { tag = { type = "Condition", var = conditions[cond] or cond:gsub("^%a", string.upper) }, applyToEnemy = true }
\tend,''')

    replace("src/Classes/Item.lua", '''\t\t\t\telseif specName == "Sockets" then
\t\t\t\t\tlocal group = 0
\t\t\t\t\tfor c in specVal:gmatch(".") do
\t\t\t\t\t\tif c:match("[S]") then
\t\t\t\t\t\t\tt_insert(self.sockets, { group = group })
\t\t\t\t\t\t\tgroup = group + 1
\t\t\t\t\t\telseif c:match("[J]") then -- e.g. specVal = "Sockets: J J J J J J"
\t\t\t\t\t\t\tself.jewelSocketCount = self.jewelSocketCount + 1
\t\t\t\t\t\tend
\t\t\t\t\tend
\t\t\t\t\tself.itemSocketCount = #self.sockets
\t\t\t\telseif specName == "Rune" then
\t\t\t\t\tt_insert(self.runes, specVal)''', '''\t\t\t\telseif specName == "Sockets" then
\t\t\t\t\tlocal itemSockets, jewelSocketCount = { }, 0
\t\t\t\t\tlocal group = 0
\t\t\t\t\tfor c in specVal:gmatch(".") do
\t\t\t\t\t\tif c:match("[S]") then
\t\t\t\t\t\t\tt_insert(itemSockets, { group = group })
\t\t\t\t\t\t\tgroup = group + 1
\t\t\t\t\t\telseif c:match("[J]") then
\t\t\t\t\t\t\tjewelSocketCount = jewelSocketCount + 1
\t\t\t\t\t\tend
\t\t\t\t\tend
\t\t\t\t\tif #itemSockets > 0 and #self.sockets == 0 then
\t\t\t\t\t\tself.sockets = itemSockets
\t\t\t\t\t\tself.itemSocketCount = #itemSockets
\t\t\t\t\tend
\t\t\t\t\tif jewelSocketCount > 0 and self.jewelSocketCount == 0 then
\t\t\t\t\t\tself.jewelSocketCount = jewelSocketCount
\t\t\t\t\tend
\t\t\t\t\tgoto continue
\t\t\t\telseif specName == "Rune" then
\t\t\t\t\tt_insert(self.runes, specVal)
\t\t\t\t\tgoto continue''')

    anchor = 'data.jewelRadius = data.setJewelRadiiGlobally(latestTreeVersion)'
    replace("src/Modules/Data.lua", anchor, '''-- Baryanic Leylines: precompute the public fixed 40% radius increase.
-- All four base sizes retain their own identity; no Unique/Relic is eligible.
data.companionTimeLostRadiusIndex = { }
for _, radii in pairs(data.jewelRadii) do
\tfor index = 1, 4 do
\t\tlocal base = radii[index]
\t\tlocal expanded = { inner = base.inner * 1.4, outer = base.outer * 1.4,
\t\t\tcol = base.col, label = "Baryanic " .. base.label, increased = true }
\t\tt_insert(radii, expanded)
\t\tdata.companionTimeLostRadiusIndex[index] = #radii
\tend
end
data.companionJewelRadiusIndex = function(item, increased)
\tlocal index = item.jewelRadiusIndex
\tlocal tags = item.base and item.base.tags
\tif increased and index and tags and tags.radius_jewel
\t\tand item.rarity ~= "UNIQUE" and item.rarity ~= "RELIC" then
\t\treturn data.companionTimeLostRadiusIndex[index] or index
\tend
\treturn index
end

''' + anchor)
    anchor = '\t["primordial"] = { mod("Multiplier:PrimordialItem", "BASE", 1) },'
    replace("src/Modules/ModParser.lua", anchor,
            '\t["non%-unique time%-lost jewels have 40%% increased radius"] = { mod("NonUniqueTimeLostJewelRadius", "INC", 40) },\n' + anchor)
    anchor = '\tenv.useAltGemQualityStats = nodesModsList:Flag(nil, "GemlingQuality")\n'
    replace("src/Modules/CalcSetup.lua", anchor, anchor + '''\t-- Use this calculation's allocation, including add/remove-node overrides.
\tlocal timeLostRadiusIncreased = nodesModsList:Sum("INC", nil, "NonUniqueTimeLostJewelRadius") == 40
''')
    anchor = '\t\t\t\t\t\t-- Jewel has a radius, add it to the list\n'
    replace("src/Modules/CalcSetup.lua", anchor, anchor +
            '\t\t\t\t\t\tlocal radiusIndex = data.companionJewelRadiusIndex(item, timeLostRadiusIncreased)\n')
    for old in (
        'nodes = node.nodesInRadius and node.nodesInRadius[item.jewelRadiusIndex] or { },',
        'attributes = node.attributesInRadius and node.attributesInRadius[item.jewelRadiusIndex] or { },',
        'for nodeId, node in pairs(node.nodesInRadius[item.jewelRadiusIndex]) do',
    ):
        replace("src/Modules/CalcSetup.lua", old, old.replace('item.jewelRadiusIndex', 'radiusIndex'))

    # Invalidate exact and combined precomputed parses before the tree loads.
    path = destination / "src/Data/ModCache.lua"
    lines = path.read_text().splitlines(keepends=True)
    affected = ("enemies you curse have", "enemies you mark have",
                "enemies you electrocute have", "non-unique time-lost jewels have")
    retained = [line for line in lines if not (
        line.startswith('c["') and any(token in line.lower() for token in affected))]
    if len(retained) == len(lines):
        raise SystemExit("upstream_small_fixes_modcache_mismatch")
    prepared[path] = "".join(retained)
    for path, source in prepared.items():
        path.write_text(source)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    patch_upstream_fixes(parser.parse_args().destination)
