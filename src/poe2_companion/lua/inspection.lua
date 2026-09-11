-- Interpreted game data only. Never emit notes, custom blocks, XML or raw items.
local M = {}
local function array(t) return setmetatable(t or {}, {__jsontype='array'}) end
local function label(s, max)
 if type(s)~='string' then return nil end
 s=s:gsub('%^%d',''):gsub('[%z\1-\8\11\12\14-\31\127]','')
 if #s>(max or 240) then return nil end
 return s
end
local function scalar(v)
 if type(v)=='boolean' then return v end
 if type(v)=='number' and v==v and math.abs(v)<=1e15 then return v end
 return label(v)
end
local function keys(t)
 local result={};for k in pairs(t or {}) do result[#result+1]=k end
 table.sort(result,function(a,b) return tostring(a)<tostring(b) end);return result
end
function M.project(build, query, saved, aliases)
 local rows={}
 local function add(v) rows[#rows+1]=v end
 if query.section=='sets' then
  for _,id in ipairs(keys(build.itemsTab.itemSets)) do add{kind='item_set',set_id=id,selected=build.itemsTab.itemSets[id]==build.itemsTab.activeItemSet} end
  for _,id in ipairs(keys(build.skillsTab.skillSets)) do add{kind='skill_set',set_id=id,selected=build.skillsTab.skillSets[id].socketGroupList==build.skillsTab.socketGroupList} end
  for _,id in ipairs(keys(build.configTab.configSets)) do add{kind='configuration_set',set_id=id,selected=id==build.configTab.activeConfigSetId} end
  for id,spec in ipairs(build.treeTab.specList or {}) do add{kind='tree_set',set_id=id,selected=spec==build.spec} end
 elseif query.section=='equipment' then
  -- Resolve the selector inside this one private request, including swap sets.
  local slotMap={['Helmet']='helmet',['Body Armour']='body_armour',['Gloves']='gloves',
   ['Boots']='boots',['Belt']='belt',['Amulet']='amulet',['Ring 1']='ring_left',
   ['Ring 2']='ring_right',['Ring 3']='ring_third',['Weapon 1']='weapon_main',
   ['Weapon 2']='weapon_off',['Weapon 3']='weapon_off',['Flask 1']='flask_1',
   ['Flask 2']='flask_2',['Charm 1']='charm_1',['Charm 2']='charm_2',['Charm 3']='charm_3',
   ['Arm 1']='arm_1',['Arm 2']='arm_2',['Leg 1']='leg_1',['Leg 2']='leg_2'}
  local selectedId=query.saved_item_id
  if query.slot then
   selectedId=0
   local itemSet=build.itemsTab.activeItemSet
   for _,slot in ipairs(keys(itemSet)) do
    local value=itemSet[slot]
    local active=not slot:match('^Weapon ') or (not not slot:match(' Swap$'))==(not not itemSet.useSecondWeaponSet)
    if active and slotMap[slot:gsub(' Swap$','')]==query.slot and type(value)=='table' and (value.selItemId or 0)>0 then
     selectedId=value.selItemId;break
    end
   end
  end
  for _,id in ipairs(keys(build.itemsTab.items)) do
   local item=build.itemsTab.items[id]
   if type(id)=='number' and (not selectedId or id==selectedId) then
    local placements=array()
    for _,setId in ipairs(keys(build.itemsTab.itemSets)) do
     local itemSet=build.itemsTab.itemSets[setId]
     for _,slot in ipairs(keys(itemSet)) do
      local value=itemSet[slot]
      if type(value)=='table' and value.selItemId==id then
       placements[#placements+1]={set_id=setId,slot=slot,active_set=itemSet==build.itemsTab.activeItemSet,
        active_weapon_set=not slot:match('^Weapon ') or (not not slot:match(' Swap$'))==(not not itemSet.useSecondWeaponSet)}
      end
     end
    end
    local included=not query.set_id
    for _,p in ipairs(placements) do if p.set_id==query.set_id then included=true end end
    if included then
     local req=item.requirements or {}
     local rarity=(item.rarity or 'other'):lower()
     if rarity~='normal' and rarity~='magic' and rarity~='rare' and rarity~='unique' then rarity='other' end
     add{kind='item',saved_item_id=id,name=label(item.title or item.baseName),base_type=label(item.baseName),
      canonical_id=label(item.baseName),rarity=rarity,item_level=item.itemLevel,quality=item.quality,
      socket_count=item.itemSocketCount or 0,corrupted=not not item.corrupted,
      placements=(function() local a=array();for _,p in ipairs(placements) do if p.active_set then a[#a+1]=p end end;return a end)(),placement_count=#placements,
      requirements={level=req.level or 0,strength=req.str or 0,dexterity=req.dex or 0,intelligence=req.int or 0},
      status=item.base and 'known' or 'unknown'}
     if selectedId then
      for _,p in ipairs(placements) do add{kind='placement',saved_item_id=id,placements=array{p}} end
      for _,group in ipairs{{'rune',item.runeModLines},{'enchant',item.enchantModLines},{'implicit',item.implicitModLines},{'explicit',item.explicitModLines}} do
       for _,line in ipairs(group[2] or {}) do
        local active=not line.disabled and item:CheckModLineVariant(line)
        local ids=array();for _,mod in ipairs(line.modList or {}) do ids[#ids+1]=mod.name end
        local kind=line.crafted and 'crafted' or line.fractured and 'fractured' or group[1]
        local values=array();for n in (line.line or ''):gmatch('[+-]?%d+%.?%d*') do values[#values+1]=tonumber(n) end
        local flags=array();for _,key in ipairs({'crafted','fractured','desecrated','mutated','rune','enchant','implicit','custom','unscalable','disabled','prefix','suffix'}) do if line[key] then flags[#flags+1]=key end end
        add{kind='modifier',saved_item_id=id,text=label(line.line,2000),numeric_values=values,modifier_kind=kind,modifier_flags=flags,enabled=not not active,
         canonical_ids=ids,status=not active and 'inactive' or line.extra and 'unparsed' or line.modList and 'parsed_not_fully_verified' or 'unparsed'}
       end
      end
      for _,key in ipairs(keys(item.armourData)) do
       if type(item.armourData[key])=='number' then add{kind='property',saved_item_id=id,name=key,effective_value=item.armourData[key]} end
      end
      for _,key in ipairs(keys(item.weaponData)) do
       if type(item.weaponData[key])=='number' then add{kind='property',saved_item_id=id,name=key,effective_value=item.weaponData[key]} end
      end
      for i,rune in ipairs(item.runes or {}) do add{kind='property',saved_item_id=id,name='rune_'..i,effective_value=label(rune)} end
     end
    end
   end
  end
 elseif query.section=='skills' then
  for _,setId in ipairs(keys(build.skillsTab.skillSets)) do
   if not query.set_id or setId==query.set_id then
    local set=build.skillsTab.skillSets[setId]
    for groupId,group in ipairs(set.socketGroupList or {}) do
     local active=set.socketGroupList==build.skillsTab.socketGroupList
     add{kind='skill_group',set_id=setId,skill_group=groupId,enabled=group.enabled~=false,
      selected=active and build.mainSocketGroup==groupId,selected_active_skill=group.mainActiveSkill or 1,name=label(group.slot)}
     for gemId,gem in ipairs(group.gemList or {}) do
      local effect=build.data.skills[gem.skillId or '']
      add{kind='gem',set_id=setId,skill_group=groupId,gem_index=gemId,
       skill_instance_id='skill:s'..setId..':g'..groupId..':n'..gemId,canonical_id=effect and effect.id or nil,
       name=effect and label(effect.name) or nil,level=gem.level,quality=gem.quality,enabled=gem.enabled~=false,
       support=effect~=nil and not not effect.support,status=effect and 'known' or 'unknown'}
     end
    end
   end
  end
 elseif query.section=='configuration' then
  local reverse={};for public,key in pairs(aliases or {}) do reverse[key]=public end
  for _,option in ipairs(require('Modules.ConfigOptions')) do
   local name=option.var
   if name and name~='customMods' and (not query.configuration_key or name==query.configuration_key or reverse[name]==query.configuration_key) then
    local old=saved[name]
    local public=reverse[name]
    local override=public and query.configuration and query.configuration[public]
    local value=build.configTab.input[name]
    local default=build.configTab.defaultState[name]
    if value==nil then value=default end
    local source=override~=nil and 'override' or old~=nil and 'saved' or value~=nil and 'engine_default' or 'unknown'
    add{kind='configuration',set_id=build.configTab.activeConfigSetId,canonical_id=name,name=label(option.label),saved_value=scalar(old),override_value=scalar(override),
     effective_value=scalar(value),default_value=scalar(default),effective_source=source,public_field=public,
     status=source=='unknown' and 'unknown' or 'known'}
   end
  end
  -- Typed compound overrides are flattened into individually pageable values.
  -- Only schema-validated input is traversed; no custom PoB configuration text.
  local function overrides(value,path,public)
   if type(value)=='table' then
    for _,key in ipairs(keys(value)) do overrides(value[key],path..'.'..key,public) end
   else
    add{kind='configuration',set_id=build.configTab.activeConfigSetId,public_field=public,override_path=path,
     override_value=scalar(value),effective_value=scalar(value),effective_source='override',status='known'}
   end
  end
  for _,public in ipairs(keys(query.configuration)) do
   if not aliases[public] and (not query.configuration_key or query.configuration_key==public) then
    overrides(query.configuration[public],public,public)
   end
  end
 elseif query.section=='passives' then
  for _,id in ipairs(keys(build.spec.allocNodes)) do
   local node=build.spec.allocNodes[id]
   if node then
    add{kind='passive',node_id=tonumber(id),name=label(node.name),status='known'}
    for _,line in ipairs(node.sd or {}) do add{kind='passive',node_id=tonumber(id),text=label(line,2000),status='parsed_not_fully_verified'} end
   end
  end
 end
 local page=array()
 for i=query.offset+1,math.min(#rows,query.offset+query.limit) do page[#page+1]=rows[i] end
 return {build_id=query.build_id,section=query.section,records=page,total=#rows,
  next_offset=query.offset+query.limit<#rows and query.offset+query.limit or nil}
end
return M
