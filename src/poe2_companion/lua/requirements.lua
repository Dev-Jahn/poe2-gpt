-- Project native requirement tables using canonical identities only.
local M={}
local attrs={Str='strength',Dex='dexterity',Int='intelligence'}
local function zeros() return {strength=0,dexterity=0,intelligence=0} end
function M.project(build)
 local env,out=build.calcsTab.mainEnv,build.calcsTab.mainOutput
 local result={available=zeros(),engine_required=zeros(),equipment_maximum=zeros(),
  native_gem_maximum=zeros(),support_sum=zeros(),sources=setmetatable({},{__jsontype='array'})}
 local ids={}
 for sid,set in pairs(build.skillsTab.skillSets) do
  for gid,group in ipairs(set.socketGroupList or {}) do
   for nid,gem in ipairs(group.gemList or {}) do ids[gem]='skill:s'..sid..':g'..gid..':n'..nid end
  end
 end
 for attr,name in pairs(attrs) do result.available[name]=math.max(0,out[attr] or 0);result.engine_required[name]=out['Req'..attr] or 0 end
 local ignored=not not env.modDB:Flag(nil,'IgnoreAttributeRequirements')
 local highest=env.modDB:Flag(nil,'GemAttributeRequirementsSatisfiedByHighestAttribute')
 local strength=env.modDB:Flag(nil,'StrengthSatisfiesMeleeWeaponsAndSkills')
 for _,req in ipairs(env.requirementsTable or {}) do
  local item,gem=req.sourceItem,req.sourceGem
  local kind=item and 'equipment' or gem and 'native_gem' or 'support_total'
  local row={kind=kind,base_attributes=zeros(),modified_attributes=zeros(),satisfying_attributes=zeros(),
   attribute_requirements_ignored=ignored,satisfied=true}
  local mult=1;local melee=false
  if item then
   row.saved_item_id=not item._companionTrade and item.id or nil;row.slot=req.sourceSlot
   row.character_level_required=tonumber((item.requirements or {}).level) or 0
   mult=item.base and item.base.weapon and out.GlobalWeaponAttributeRequirements or out.GlobalItemAttributeRequirements
   melee=item.base and item.base.weapon and build.data.weaponTypeInfo[item.base.type].melee
   if item.base and item.base.type=='Gloves' and env.modDB:Flag(nil,'IgnoreGloveAttributeRequirements') then mult=0 end
  elseif gem then
   row.skill_instance_id=ids[gem];row.skill_id=gem.skillId;row.native_level=gem.level
   row.support=not not (gem.gemData and gem.gemData.grantedEffect.support)
   row.effective_level=gem.displayEffect and gem.displayEffect.level or nil
   row.character_level_required=gem.reqLevel or 0
   mult=out.GlobalGemAttributeRequirements
   melee=gem.gemData and gem.gemData.tags and gem.gemData.tags.melee
  end
  row.satisfied=row.character_level_required==nil or row.character_level_required<=build.characterLevel
  local bucket=kind=='equipment' and result.equipment_maximum or kind=='native_gem' and result.native_gem_maximum or result.support_sum
  for attr,name in pairs(attrs) do
   local raw=tonumber(req[attr]) or 0
   local modified=math.floor(raw*(mult or 1))
   local available=out[attr] or 0
   if gem and highest then available=math.max(out.Str or 0,out.Dex or 0,out.Int or 0) end
   if attr~='Str' and strength and melee then available=math.max(available,out.Str or 0) end
   row.base_attributes[name]=raw;row.modified_attributes[name]=modified
   row.satisfying_attributes[name]=math.max(0,available)
   if not ignored and modified>available then row.satisfied=false end
   bucket[name]=math.max(bucket[name],modified)
  end
  result.sources[#result.sources+1]=row
 end
 return result
end
return M
