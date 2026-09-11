-- Each edge replays its exact preceding actions from the immutable XML.
-- No final-state passive/gem bonuses are borrowed to equip an earlier item.
local M={}
local function array(t) return setmetatable(t or {},{__jsontype='array'}) end
local function copy(t) local r={};for k,v in pairs(t) do r[k]=v end;return r end
local function touches(edit)
 local out={}
 if edit.slot then out['slot:'..edit.slot]=true end
 if edit.type=='instill_amulet' then out['slot:amulet']=true end
 if edit.skill_instance_id then out[edit.skill_instance_id:match('^(.*):n%d+$')]=true end
 for _,field in ipairs({'node_ids','allocate_node_ids','refund_node_ids'}) do
  for _,id in ipairs(edit[field] or {}) do out['node:'..id]=true end
 end
 return out
end
function M.solve(build,request,items,originals,slotKeys,slotName,selected,selectItem,refresh,itemChecks,load,edits,requirements)
 local goal={}
 local function token(id)
  local item=build.itemsTab.items[id]
  return item and item._companionTrade and 'trade:'..item.uniqueID or 'saved:'..id
 end
 for _,slot in ipairs(slotKeys) do goal[slot]=token(selected(slotName(slot))) end
 local dependencies,targets={},{}
 for i,edit in ipairs(request.edits) do
  targets[i]=touches(edit);dependencies[i]={}
  for j=1,i-1 do
   for key in pairs(targets[i]) do if targets[j][key] then dependencies[i][j]=true end end
  end
 end
 local function sequenceRequest(actions)
  local r=copy(request);r.edits={};local imported={}
  for i,action in ipairs(actions) do
   r.edits[i]=action.edit
   if action.index then imported[tostring(i)]=items and items[tostring(action.index)] end
  end
  return r,imported
 end
 local function replay(actions)
  load()
  if #actions>0 then
   local r,imported=sequenceRequest(actions)
   local _,checks=edits.apply(build,r,imported,slotName,selected,selectItem)
   refresh();edits.validateSupports(checks)
  end
 end
 local function validState()
  for _,row in ipairs(requirements.project(build).sources) do if not row.satisfied then return false end end
  for _,stat in ipairs({'LifeUnreserved','ManaUnreserved','SpiritUnreserved'}) do
   if (build.calcsTab.mainOutput[stat] or 0)<0 then return false end
  end
  local seen={}
  for _,slot in ipairs(slotKeys) do
   local id=selected(slotName(slot));local item=build.itemsTab.items[id]
   if item then
    if seen[id] or not build.itemsTab:IsItemValidForSlot(item,slotName(slot)) then return false end
    seen[id]=true
   end
  end
  return true
 end
 local function stateKey(done)
  local k={}
  for i=1,#request.edits do k[#k+1]=done[i] and '1' or '0' end
  for _,slot in ipairs(slotKeys) do k[#k+1]=token(selected(slotName(slot))) end
  return table.concat(k,':')
 end
 local function complete(done)
  for i=1,#request.edits do if not done[i] then return false end end
  for _,slot in ipairs(slotKeys) do if token(selected(slotName(slot)))~=goal[slot] then return false end end
  return true
 end
 local function edge(current,action)
  replay(current.actions)
  -- Augments must modify the item named by the plan, never a helper that
  -- happens to occupy its slot. Preceding same-slot edits are dependencies.
  local slot=action.edit.slot or action.edit.type=='instill_amulet' and 'amulet'
  if action.edit.type=='socket_rune' or action.edit.type=='instill_amulet' then
   if token(selected(slotName(slot)))~=goal[slot] then return nil end
  end
  local available,env,slotValid
  if action.edit.type=='equip_item' then
   selectItem(slotName(slot),0);refresh()
   available=copy(build.calcsTab.mainOutput);env=build.calcsTab.mainEnv
   -- Availability is captured before the new item exists in its slot.
   slotValid=true
  end
  local actions=copy(current.actions);actions[#actions+1]=action
  replay(actions)
  if slotValid then
   local item=build.itemsTab.items[selected(slotName(slot))];local issues={}
   if not item then return nil end
   itemChecks(item,slot,available,env,issues)
   if #issues>0 then return nil end
  end
  if not validState() then return nil end
  local done=copy(current.done);if action.index then done[action.index]=true end
  return {actions=actions,done=done,key=stateKey(done),complete=complete(done)}
 end
 replay({})
 local queue={{actions={},done={}}};local seen={[stateKey({})]=true};local head=1;local evaluated=0;local found
 while head<=#queue and not found and evaluated<request.transition_state_budget do
  local current=queue[head];head=head+1
  local choices={}
  for i,edit in ipairs(request.edits) do
   local ready=not current.done[i]
   for j in pairs(dependencies[i]) do if not current.done[j] then ready=false end end
   if ready then choices[#choices+1]={edit=edit,index=i,temporary=false,owned=false} end
  end
  for _,helper in ipairs(request.temporary_equipment or {}) do
   choices[#choices+1]={edit={type='equip_item',slot=helper.slot,source={kind='saved_item',saved_item_id=helper.saved_item_id}},temporary=true,owned=true}
   local original=originals[helper.slot]
   -- Restoration to a planned new item is represented by its actual edit.
   if goal[helper.slot]=='saved:'..original then
    choices[#choices+1]={edit=original==0 and {type='unequip_item',slot=helper.slot} or
     {type='equip_item',slot=helper.slot,source={kind='saved_item',saved_item_id=original}},temporary=false,owned=false}
   end
  end
  for _,action in ipairs(choices) do
   if evaluated>=request.transition_state_budget then break end
   evaluated=evaluated+1
   local ok,nextState=pcall(edge,current,action)
   if ok and nextState and not seen[nextState.key] then
    seen[nextState.key]=true
    if nextState.complete then found=nextState.actions;break end
    if #nextState.actions<32 then queue[#queue+1]=nextState end
   end
  end
 end
 local actions=array()
 for _,action in ipairs(found or {}) do
  local edit=action.edit
  actions[#actions+1]={action=edit.type=='equip_item' and 'equip' or edit.type=='unequip_item' and 'unequip' or 'apply_edit',
   slot=edit.slot,edit_index=action.index and action.index-1 or nil,temporary=action.temporary,owned_helper=action.owned,
   saved_item_id=edit.source and edit.source.kind=='saved_item' and edit.source.saved_item_id or nil}
 end
 -- Restore the exact joint candidate, independent of the last explored edge.
 load();edits.apply(build,request,items,slotName,selected,selectItem,true);refresh()
 local exhausted=not found and evaluated<request.transition_state_budget and head>#queue
 return {status=found and 'verified' or exhausted and 'no_valid_order_within_choices' or 'search_budget_exhausted',
  actions=actions,states_evaluated=evaluated,search_exhausted=exhausted,
  optimality=found and 'fewest_actions_within_supplied_owned_choices' or 'unproven'}
end
return M
