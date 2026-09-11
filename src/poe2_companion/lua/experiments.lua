-- Typed edits on a throwaway native build. Never writes an exported build.
local M={}
local function array(t) return setmetatable(t or {},{__jsontype='array'}) end
local function fail(index,code) error({edit_index=index-1,code=code},0) end
local function gemAt(build,id,index)
 local s,g,n=id:match('^skill:s(%d+):g(%d+):n(%d+)$')
 local set=build.skillsTab.skillSets[tonumber(s)]
 local group=set and set.socketGroupList[tonumber(g)]
 local gem=group and group.gemList[tonumber(n)]
 if not gem then fail(index,'entity_not_found') end
 return gem,group
end
local function nodeAt(build,id,index,ascendancy)
 local node=build.spec.nodes[id]
 if not node then fail(index,'entity_not_found') end
 if (not not node.ascendancyName)~=ascendancy then fail(index,'wrong_point_pool') end
 if node.type=='ClassStart' or node.type=='AscendClassStart' or node.type=='Mastery' or
  node.isMultipleChoice or node.isMultipleChoiceOption or node.isProxy or node.isFreeAllocate then
  fail(index,'unsupported_node_rule')
 end
 if ascendancy and node.ascendancyName~=build.spec.curAscendClassName then fail(index,'wrong_point_pool') end
 return node
end
local function graphConnected(build,index)
 for _,node in pairs(build.spec.allocNodes) do
  if node.type~='ClassStart' and node.type~='AscendClassStart' and not node.isFreeAllocate then
   local visited={}
   local connected=build.spec:FindStartFromNode(node,visited,false,node.allocMode)
   for _,v in ipairs(visited) do v.visited=false end
   if not connected then fail(index,'graph_disconnected') end
  end
 end
end
function M.apply(build,request,items,slotName,selected,selectItem)
 local used,ascUsed=build.spec:CountAllocNodes()
 local audit={status='valid_changeset',failures=array(),applied_edits=array(),base_unchanged=true,
  transition_validation='no_equipment_transition'}
 local supportChecks={}
 for index,edit in ipairs(request.edits) do
  if edit.type=='set_gem' then
   local gem,group=gemAt(build,edit.skill_instance_id,index)
   local effect=gem.grantedEffect or gem.gemData and gem.gemData.grantedEffect
   if not effect or not effect.levels[edit.native_level] or gem.fromItem or gem.fromTree then fail(index,'invalid_level') end
   gem.level=edit.native_level;gem.quality=edit.quality
   build.skillsTab:ProcessSocketGroup(group)
   if gem.level~=edit.native_level then fail(index,'invalid_level') end
  elseif edit.type=='set_supports' then
   local gem,group=gemAt(build,edit.skill_instance_id,index)
   if #edit.support_gem_ids>edit.observed_socket_capacity then fail(index,'socket_capacity') end
   -- Keep original instance positions stable, including inactive gems. New
   -- supports have no authority to change an existing active skill's identity.
   for _,old in ipairs(group.gemList) do
    local effect=old.grantedEffect or old.gemData and old.gemData.grantedEffect
    if effect and effect.support then old.enabled=false end
   end
   for _,id in ipairs(edit.support_gem_ids) do
    local data=build.data.gems[id] or build.data.gems[build.data.gemForSkill[id]]
    if not data or not data.grantedEffect.support then fail(index,'entity_not_found') end
    local support={gemId=data.id,skillId=data.grantedEffectId,level=data.naturalMaxLevel or 1,
     quality=0,enabled=true,enableGlobal1=true,enableGlobal2=true}
    group.gemList[#group.gemList+1]=support
    supportChecks[#supportChecks+1]={index=index,gem=gem,support=support}
   end
   build.skillsTab:ProcessSocketGroup(group)
  elseif edit.type=='allocate_passives' or edit.type=='refund_passives' or edit.type=='set_ascendancy' then
   local asc=edit.type=='set_ascendancy'
   local removals=edit.type=='refund_passives' and edit.node_ids or edit.refund_node_ids or {}
   for _,id in ipairs(removals) do
    local node=nodeAt(build,id,index,asc)
    if not node.alloc then fail(index,'entity_not_found') end
    build.spec:DeallocSingleNode(node)
   end
   local additions=edit.type=='allocate_passives' and edit.node_ids or edit.allocate_node_ids or {}
   local attributes={}
   for _,choice in ipairs(edit.attribute_choices or {}) do attributes[choice.node_id]=choice.attribute end
   for _,id in ipairs(additions) do
    local node=nodeAt(build,id,index,asc)
    if node.alloc then fail(index,'entity_not_found') end
    if node.isAttribute then
     local which=({strength=1,dexterity=2,intelligence=3})[attributes[id]]
     if not which then fail(index,'attribute_choice_required') end
     build.spec:SwitchAttributeNode(id,which)
    end
    local mode=edit.allocation_mode or 0
    if mode~=0 and (node.type=='Keystone' or node.type=='Socket') then fail(index,'unsupported_node_rule') end
    node.alloc=true;node.allocMode=mode;build.spec.allocNodes[id]=node
   end
   graphConnected(build,index)
   build.spec:BuildAllDependsAndPaths()
   local now,ascNow=build.spec:CountAllocNodes()
   if now-used>request.ordinary_points_available or ascNow-ascUsed>request.ascendancy_points_available then fail(index,'point_budget') end
  elseif edit.type=='equip_item' or edit.type=='unequip_item' then
   local id=0
   if edit.type=='equip_item' then
    if edit.source.kind=='saved_item' then id=edit.source.saved_item_id
    else
     local item=items and items[tostring(index)]
     if not item then fail(index,'entity_not_found') end
     build.importTab:ImportItem(item,slotName(edit.slot))
     id=selected(slotName(edit.slot))
     local imported=build.itemsTab.items[id]
     if not imported or imported.uniqueID~=item.id then fail(index,'entity_not_found') end
     imported._companionTrade=true
    end
    if not build.itemsTab.items[id] then fail(index,'entity_not_found') end
   end
   selectItem(slotName(edit.slot),id)
   audit.transition_validation='requires_order_validation'
  elseif edit.type=='socket_rune' then
   local item=build.itemsTab.items[selected(slotName(edit.slot))]
   local rune=build.data.itemMods.Runes[edit.rune_catalog_id]
   if not item or not rune then fail(index,'entity_not_found') end
   if edit.socket_index>=(item.itemSocketCount or 0) then fail(index,'socket_capacity') end
   local base,specific=item:GetSocketedAugmentTypes()
   if not rune[base] and not rune[specific] then fail(index,'rune_incompatible') end
   item.runes[edit.socket_index+1]=edit.rune_catalog_id
   item:UpdateRunes();item:BuildAndParseRaw()
  elseif edit.type=='instill_amulet' then
   local item=build.itemsTab.items[selected(slotName('amulet'))]
   local node=build.spec.tree.nodes[edit.notable_node_id]
   if not item or not node then fail(index,'entity_not_found') end
   if not node.recipe or #node.recipe==0 or node.type~='Notable' or node.ascendancyName or
    edit.recipe_catalog_id~='instill:'..node.id then fail(index,'instill_recipe_unverified') end
   build.itemsTab.displayItem=item;build.itemsTab.anointEnchantSlot=1
   build.itemsTab.items[item.id]=build.itemsTab:anointItem(node)
  else fail(index,'entity_not_found') end
  audit.applied_edits[#audit.applied_edits+1]={edit_index=index-1,type=edit.type,status='applied_to_private_clone'}
 end
 local now,ascNow=build.spec:CountAllocNodes()
 audit.ordinary_points_delta=now-used;audit.ascendancy_points_delta=ascNow-ascUsed
 return audit,supportChecks
end
function M.validateSupports(checks)
 for _,check in ipairs(checks) do
  local effect=check.support.supportEffect
  if not effect or not effect.isSupporting or not effect.isSupporting[check.gem] then
   fail(check.index,'support_incompatible')
  end
 end
end
return M
