-- Bounded breadth-first search over actual native equip actions. Every new
-- item is checked after removing its slot, so it cannot supply its own stats.
local M={}
local function array(t) return setmetatable(t or {},{__jsontype='array'}) end
function M.solve(build,request,originals,slotKeys,slotName,selected,selectItem,refresh,itemChecks)
 local goal,options,editIndex={},{},{}
 for _,slot in ipairs(slotKeys) do goal[slot]=selected(slotName(slot));options[slot]={} end
 for i,edit in ipairs(request.edits) do
  if edit.type~='equip_item' and edit.type~='unequip_item' then
   return {status='requires_order_validation',actions=array(),states_evaluated=0,search_exhausted=false}
  end
  if editIndex[edit.slot] then
   return {status='requires_order_validation',actions=array(),states_evaluated=0,search_exhausted=false}
  end
  editIndex[edit.slot]=i-1
 end
 for _,slot in ipairs(slotKeys) do
  if goal[slot]~=originals[slot] then options[slot][#options[slot]+1]=goal[slot] end
 end
 local helpers={}
 for _,helper in ipairs(request.temporary_equipment or {}) do
  if not build.itemsTab.items[helper.saved_item_id] then
   return {status='requires_order_validation',actions=array(),states_evaluated=0,search_exhausted=false}
  end
  options[helper.slot][#options[helper.slot]+1]=helper.saved_item_id
  -- Temporary slots must return to the exact final state.
  options[helper.slot][#options[helper.slot]+1]=goal[helper.slot]
  helpers[helper.slot..':'..helper.saved_item_id]=true
 end
 local function key(state)
  local values={};for _,slot in ipairs(slotKeys) do values[#values+1]=state[slot] end
  return table.concat(values,':')
 end
 local function set(state)
  for _,slot in ipairs(slotKeys) do selectItem(slotName(slot),state[slot]) end
  refresh()
 end
 local goalKey=key(goal)
 local queue={{state=originals,actions={}}};local head=1;local seen={[key(originals)]=true}
 local evaluated=0;local found
 while head<=#queue and evaluated<request.transition_state_budget do
  local current=queue[head];head=head+1;evaluated=evaluated+1
  if key(current.state)==goalKey then found=current.actions;break end
  for _,slot in ipairs(slotKeys) do
   for _,id in ipairs(options[slot]) do
    if id~=current.state[slot] then
     local nextState={};for _,s in ipairs(slotKeys) do nextState[s]=current.state[s] end
     nextState[slot]=id
     local nextKey=key(nextState)
     if not seen[nextKey] then
      local duplicate=false
      for _,s in ipairs(slotKeys) do if s~=slot and id~=0 and current.state[s]==id then duplicate=true end end
      if not duplicate then
       set(current.state);selectItem(slotName(slot),0);refresh()
       local issues={};local item=build.itemsTab.items[id]
       local valid=id==0
       if item then
        itemChecks(item,slot,build.calcsTab.mainOutput,build.calcsTab.mainEnv,issues)
        valid=#issues==0 and build.itemsTab:IsItemValidForSlot(item,slotName(slot))
       end
       if valid then
        selectItem(slotName(slot),id);refresh()
        for _,weapon in ipairs({'weapon_main','weapon_off'}) do
         local equipped=build.itemsTab.items[selected(slotName(weapon))]
         if equipped and not build.itemsTab:IsItemValidForSlot(equipped,slotName(weapon)) then valid=false end
        end
       end
       if valid then
        local actions={};for i,action in ipairs(current.actions) do actions[i]=action end
        actions[#actions+1]={slot=slot,action=id==0 and 'unequip' or 'equip',
         saved_item_id=item and not item._companionTrade and id or nil,
         edit_index=id==goal[slot] and editIndex[slot] or nil,
         temporary=id~=goal[slot],owned_helper=not not helpers[slot..':'..id]}
        seen[nextKey]=true;queue[#queue+1]={state=nextState,actions=actions}
       end
      end
     end
    end
   end
  end
 end
 set(goal)
 return {status=found and 'verified' or head>#queue and 'no_valid_order_within_choices' or 'search_budget_exhausted',
  actions=array(found),states_evaluated=evaluated,search_exhausted=head>#queue,
  optimality=found and 'fewest_actions_within_supplied_owned_choices' or 'unproven'}
end
return M
