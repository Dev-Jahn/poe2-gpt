local M={}
function M.resolve(build)
 local env=build.calcsTab.mainEnv
 local skill=env and env.player.mainSkill
 local active=skill and skill.activeEffect
 local effect=active and active.grantedEffect
 if not effect or not effect.id or not build.data.skills[effect.id] then return nil end
 local instance
 for setId,set in pairs(build.skillsTab.skillSets) do
  if set.socketGroupList==build.skillsTab.socketGroupList then
   for groupId,group in ipairs(set.socketGroupList) do
    for gemId,gem in ipairs(group.gemList or {}) do
     if gem==active.srcInstance then instance='skill:s'..setId..':g'..groupId..':n'..gemId end
    end
   end
  end
 end
 return {skill_instance_id=instance,skill_id=effect.id,actor_ref=skill.minion and 'minion' or 'player',
  component_ref=effect.id,weapon_set_id=build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1}
end
function M.select(build,target,refresh)
 if not target then return nil end
 if target.actor_ref~='player' and target.actor_ref~='minion' then return 'actor_not_supported' end
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
