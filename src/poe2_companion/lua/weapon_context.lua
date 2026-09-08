-- One private calculation may resolve one shared weapon context. Different
-- explicit contexts require upstream's broader per-skill environment work.
-- Saved PoB bytes and enabled skill flags are never changed by this adapter.
local context = {}
local calcs = require('Modules.CalcBase')

function context.isActive(build, skill)
 return calcs.companionIsActiveSkill(build.calcsTab.mainEnv, skill)
end

local function current(build)
 return build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1
end

local function effectForGroup(build, group)
 for _, gem in ipairs(group.gemList or {}) do
  if gem.enabled then
   local effect = gem.grantedEffect or (gem.gemData and gem.gemData.grantedEffect)
   if effect and not effect.support and build.data.skills[effect.id]==effect then return effect end
  end
 end
end

local function explicit(group)
 return group.set1~=nil or group.set2~=nil or group.companionInvalidWeaponContext
end

local function permitted(group, set)
 return not group.companionInvalidWeaponContext and group['set'..set]~=false
end

local function slotContext(build, group)
 local slot=group.slot and build.itemsTab.slots[group.slot]
 return slot and slot.weaponSet
end

local function desired(build, group)
 if not group or group.companionInvalidWeaponContext then return nil end
 local one,two=group.set1~=false,group.set2~=false
 if one~=two then return one and 1 or 2 end
 if not one then return nil end
 if explicit(group) then return nil end -- Both preserves the saved global context.
 -- A legacy main skill explicitly socketed in a weapon slot also identifies
 -- its context. Ordinary unslotted legacy groups retain their saved behavior.
 return slotContext(build,group)
end

function context.activate(build)
 local groups=build.skillsTab.socketGroupList or {}
 local main=groups[build.mainSocketGroup or 1]
 if not main or not effectForGroup(build,main) then return false end
 local target=desired(build,main)
 if not target or target==current(build) then return false end
 for _, group in ipairs(groups) do
  if (group.enabled or group==main) and effectForGroup(build,group) then
   -- No silently discarded active legacy slot, or competing explicit set.
   -- The rest of PR2498 is necessary to calculate simultaneous contexts.
   local slot=slotContext(build,group)
   if not permitted(group,target) or (slot and slot~=target) then return false end
  end
 end
 -- Invoke the upstream ItemsTab action, including cache/undo/build flags.
 -- The proof above excludes its main-group reselection case.
 local selected=build.mainSocketGroup
 build.itemsTab.controls['weaponSwap'..target]:Click()
 assert(build.mainSocketGroup==selected and current(build)==target)
 return true
end

function context.inspect(build)
 local issues={}
 local groups=build.skillsTab.socketGroupList or {}
 local main=groups[build.mainSocketGroup or 1]
 local active=current(build)
 for _, group in ipairs(groups) do
  local effect=effectForGroup(build,group)
  if effect and (group.enabled or group==main) then
   local requested=desired(build,group)
   local slot=slotContext(build,group)
   local conflict=explicit(group) and (not permitted(group,active) or (slot and slot~=active))
   if group==main and requested and requested~=active then conflict=true end
   if conflict then issues[#issues+1]={code='unsupported_weapon_context',skill_id=effect.id} end
  end
 end
 return issues
end

return context
