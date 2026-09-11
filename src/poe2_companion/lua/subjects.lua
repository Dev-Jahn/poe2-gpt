local M={}
function M.actor(skill)
 if skill and skill.skillTypes and skill.skillTypes[SkillType.SupportedByHollowForm] then return 'hollow_image' end
 if skill and skill.minion and skill.activeEffect.grantedEffect.id=='SpiritVesselPlayer' then return 'spirit_vessel' end
 return skill and skill.minion and 'minion' or 'player'
end
local function instanceId(build,source)
 for setId,set in pairs(build.skillsTab.skillSets) do
  if set.socketGroupList==build.skillsTab.socketGroupList then
   for groupId,group in ipairs(set.socketGroupList) do
    for gemId,gem in ipairs(group.gemList or {}) do
     if gem==source then return 'skill:s'..setId..':g'..groupId..':n'..gemId end
    end
   end
  end
 end
end
local function copySource(owner,skillId)
 local found
 for _,gem in ipairs(owner.socketGroup and owner.socketGroup.gemList or {}) do
  local effect=gem.gemData and gem.gemData.grantedEffect or gem.grantedEffect
  if gem.enabled~=false and effect and effect.id==skillId then
   if found then return nil end -- Native copies deduplicate IDs: never choose a duplicate instance by name/order.
   found=gem
  end
 end
 return found
end
function M.resolve(build)
 local env=build.calcsTab.mainEnv
 local skill=env and env.player.mainSkill
 local active=skill and skill.activeEffect
 local effect=active and active.grantedEffect
 if not effect or not effect.id or not build.data.skills[effect.id] then return nil end
 if M.actor(skill)=='spirit_vessel' then
  local copy=skill.minion.mainSkill
  local copiedEffect=copy and copy.activeEffect and copy.activeEffect.grantedEffect
  if not copy or not copy.companionCopiedSkill or not copiedEffect then return nil end
  local source=copySource(skill,copiedEffect.id)
  if not source then return nil end
  return {skill_instance_id=instanceId(build,source),skill_id=copiedEffect.id,actor_ref='spirit_vessel',
   component_ref=copiedEffect.id,weapon_set_id=build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1,
   actor_owner_instance_id=instanceId(build,active.srcInstance)}
 end
 local instance=instanceId(build,active.srcInstance)
 return {skill_instance_id=instance,skill_id=effect.id,actor_ref=M.actor(skill),
  component_ref=effect.id,weapon_set_id=build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1}
end
function M.select(build,target,refresh)
 if not target then return nil end
 if target.aggregation=='component_breakdown' then return 'aggregation_not_supported' end
 local s,g,n=target.skill_instance_id:match('^skill:s(%d+):g(%d+):n(%d+)$')
 s,g,n=tonumber(s),tonumber(g),tonumber(n)
 local set=build.skillsTab.skillSets[s]
 local group=set and set.socketGroupList[g]
 local gem=group and group.gemList[n]
 if not gem then return 'instance_not_found' end
 if group.enabled==false or gem.enabled==false then return 'instance_disabled' end
 build.skillsTab:SetActiveSkillSet(s,true)
 build.itemsTab.controls['weaponSwap'..target.weapon_set_id]:Click()
 build.mainSocketGroup=g
 refresh()
 if target.actor_ref=='spirit_vessel' then
  local effect=gem.gemData and gem.gemData.grantedEffect or gem.grantedEffect
  if not effect or (target.component_ref and target.component_ref~=effect.id) then return 'component_not_found' end
  local matches={}
  for index,owner in ipairs(group.displaySkillList or {}) do
   if owner.minion and owner.activeEffect.grantedEffect.id=='SpiritVesselPlayer'
    and (not target.actor_owner_instance_id or instanceId(build,owner.activeEffect.srcInstance)==target.actor_owner_instance_id) then
    if copySource(owner,effect.id)~=gem then return 'ambiguous_component' end
    for copyIndex,copy in ipairs(owner.minion.activeSkillList or {}) do
     if copy.companionCopiedSkill and copy.activeEffect.grantedEffect.id==effect.id then
      matches[#matches+1]={index=index,copyIndex=copyIndex,owner=owner.activeEffect.srcInstance}
     end
    end
   end
  end
  if #matches==0 then return 'component_not_found' end
  if #matches>1 then return 'ambiguous_component' end
  local selected=matches[1]
  group.mainActiveSkill=selected.index
  selected.owner.skillMinionSkill=selected.copyIndex
  selected.owner.skillMinionSkillCalcs=selected.copyIndex
  if GlobalCache and GlobalCache.cachedData then wipeGlobalCache() end
  refresh()
  return nil
 end
 local matches={}
 for index,skill in ipairs(group.displaySkillList or {}) do
  local active=skill.activeEffect
  if active and active.srcInstance==gem and
   (not target.component_ref or active.grantedEffect.id==target.component_ref) then
   matches[#matches+1]=index
  end
 end
 if #matches==0 then return 'component_not_found' end
 if #matches>1 then return 'ambiguous_component' end
 group.mainActiveSkill=matches[1]
 refresh()
 return nil
end
function M.bind(build,target,saved,selectionError,scenarioDigest)
 local evaluated=M.resolve(build)
 local reason=selectionError
 if target and not reason then
  local main=build.calcsTab.mainEnv.player.mainSkill
  if not evaluated or evaluated.skill_instance_id~=target.skill_instance_id or
   evaluated.weapon_set_id~=target.weapon_set_id or main.disableReason or
   (target.actor_owner_instance_id and evaluated.actor_owner_instance_id~=target.actor_owner_instance_id) or
   (target.component_ref and evaluated.component_ref~=target.component_ref) then
   reason='eligibility_changed'
  elseif evaluated.actor_ref~=target.actor_ref then reason='actor_mismatch' end
 end
 local nextAction=reason and 'inspect_skill_instances' or nil
 if reason=='ambiguous_component' then nextAction='choose_component'
 elseif reason=='actor_not_supported' or reason=='actor_mismatch' then nextAction='supply_supported_actor'
 elseif reason=='eligibility_changed' or reason=='instance_disabled' then nextAction='repair_skill_eligibility' end
 return {saved=saved,requested=target,evaluated=not reason and evaluated or nil,
  status=reason and 'unavailable' or target and 'matched' or 'saved_default',
  reason=reason,scenario_digest=scenarioDigest,next_action=nextAction}
end
return M
