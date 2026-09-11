-- Parse with the native pinned loaders, stopping at the explicit calculation
-- boundary in Build:Init. This module must never supply calculation output.
local M = {}
function M.load(xml)
 new('CalcsTab') -- Load the class without constructing a calculation tab.
 local class=assert(common.classes.CalcsTab)
 local original=class.BuildOutput
 local boundary={}
 class.BuildOutput=function() error(boundary,0) end
 -- Call the loader directly: the application's OnFrame error handler consumes
 -- exceptions and would conceal whether the boundary was actually reached.
 local ok,err=pcall(function() build:Init(false,'',xml) end)
 class.BuildOutput=original
 assert(not ok and err==boundary,'static_load_boundary_not_reached')
 assert(build and build.savers and build.targetVersion==liveTargetVersion)
 assert(build.calcsTab.mainOutput==nil,'static_load_calculated')
 for _,set in pairs(build.skillsTab.skillSets) do
  for _,group in ipairs(set.socketGroupList or {}) do build.skillsTab:ProcessSocketGroup(group) end
 end
 return build
end
return M
