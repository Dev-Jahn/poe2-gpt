-- Private, one-job process. Only closed numeric projections leave stdout.
-- Uses commit-pinned community PoE2 PoB modules and reviewed data (MIT).
print = function() end
local json = require('dkjson')
local job = assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
assert(build and not __mainObject__.promptMsg)
-- Exact crafting-only lines in the pinned 0.5.5 data affect future item
-- modification, not the current combat stats. No broad pattern suppression.
-- See upstream PR2509 (crafting influences) and ModRunes' Atziri cores.
for _,line in ipairs({'Can roll Ring Modifiers','Can roll Chronomancy modifiers',
 'Can roll Marksman modifiers','Can roll Berserking modifiers',
 'Can roll Destruction modifiers','Can roll Soul modifiers','Can roll Decay modifiers',
 'Corrupting will always result in change'}) do
 modLib.parseModCache[line]={{},nil}
end
local slots = {helmet='Helmet',body_armour='Body Armour',gloves='Gloves',boots='Boots',belt='Belt',amulet='Amulet',ring_left='Ring 1',ring_right='Ring 2',weapon_main='Weapon 1',weapon_off='Weapon 2'}
local slotKeys = {'helmet','body_armour','gloves','boots','belt','amulet','ring_left','ring_right','weapon_main','weapon_off'}
local statKeys = {'Life','LifeUnreserved','Mana','ManaUnreserved','EnergyShield','Armour','Evasion','FireResist','ColdResist','LightningResist','ChaosResist','BlockChance','SpellBlockChance','Str','Dex','Int','TotalDPS','CombinedDPS','FullDPS','Speed','CritChance','CritMultiplier'}
local function array(t) return setmetatable(t or {}, {__jsontype='array'}) end
local function refresh()
 build.buildFlag = true
 runCallback('OnFrame')
 assert(build.calcsTab.mainOutput and not __mainObject__.promptMsg)
end
local function load()
 if GlobalCache and GlobalCache.cachedData then wipeGlobalCache() end
 loadBuildFromXML(job.xml, '')
 assert(build and build.savers and build.targetVersion==liveTargetVersion and build.calcsTab and build.calcsTab.mainOutput and not __mainObject__.promptMsg)
end
local function slotName(key)
 local name = slots[key]
 if (key == 'weapon_main' or key == 'weapon_off') and build.itemsTab.activeItemSet.useSecondWeaponSet then name = name .. ' Swap' end
 return name
end
local function selected(name)
 local s = build.itemsTab.activeItemSet[name]
 return s and s.selItemId or 0
end
local function selectItem(name, id)
 assert(build.itemsTab.slots[name])
 -- Do not call SetSelItemId: it can silently unequip the other weapon.
 build.itemsTab.activeItemSet[name].selItemId = id
 build.itemsTab.slots[name].selItemId = id
end
local function issue(t, code, key, stat, required, available)
 t[#t+1] = {code=code,slot=key,stat=stat,required=required,available=available}
end
local function itemChecks(item, key, out, env, issues)
 local req = item.requirements or {}
 local lv = tonumber(req.level) or 0
 if lv > build.characterLevel then issue(issues,'level_requirement',key,'Level',lv,build.characterLevel) end
 if item.classRestriction and item.classRestriction ~= build.spec.curClassName and item.classRestriction ~= build.spec.curAscendClassName then
  issue(issues,'class_requirement',key)
 end
 if not item.base then issue(issues,'unknown_item_base',key); return end
 local mult = item.base.weapon and out.GlobalWeaponAttributeRequirements or out.GlobalItemAttributeRequirements
 if not mult then issue(issues,'configuration_override',key); return end
 if not env.modDB:Flag(nil,'IgnoreAttributeRequirements') then
  for _, attr in ipairs({'Str','Dex','Int'}) do
   local required = math.floor((tonumber(req[attr:lower()..'Mod']) or 0) * mult)
   local available = out[attr] or 0
   if attr ~= 'Str' and env.modDB:Flag(nil,'StrengthSatisfiesMeleeWeaponsAndSkills') and item.base.weapon and build.data.weaponTypeInfo[item.base.type].melee then available=math.max(available,out.Str or 0) end
   if required > available then issue(issues,'attribute_requirement',key,attr,required,available) end
  end
 end
end
local function inspect(expected, order, sequenceOk)
 local out,env=build.calcsTab.mainOutput,build.calcsTab.mainEnv
 local stats,equipped,issues=array(),array(),array()
 local seenItems={}
 local fullDpsEnabled=type(out.SkillDPS)=='table' and #out.SkillDPS>0
 for _, key in ipairs(statKeys) do
  local v=out[key]
  if (key~='FullDPS' or fullDpsEnabled) and type(v)=='number' and v==v and math.abs(v)<=1e15 then stats[#stats+1]={name=key,value=v} end
 end
 local mainSkill=env.player.mainSkill
 local effect=mainSkill and mainSkill.activeEffect and mainSkill.activeEffect.grantedEffect
 local selectedSkill=nil
 -- Resolve identity from immutable engine data; saved labels are private.
 if effect and effect.id and build.data.skills[effect.id]==effect then
  selectedSkill={skill_id=effect.id,name=effect.name,actor=mainSkill.minion and 'minion' or 'player'}
  local gem=mainSkill.activeEffect.srcInstance and mainSkill.activeEffect.srcInstance.gemData
  if gem and type(gem.name)=='string' then selectedSkill.gem_name=gem.name end
 end
 if mainSkill and mainSkill.minion and type(out.Minion)=='table' then
  for _,key in ipairs({'TotalDPS','CombinedDPS','Speed'}) do
   local v=out.Minion[key]
   if type(v)=='number' and v==v and math.abs(v)<=1e15 then stats[#stats+1]={name='Minion'..key,value=v} end
  end
 end
 for _,key in ipairs(slotKeys) do
  local name=slotName(key);local id=selected(name);local item=build.itemsTab.items[id]
  if expected and expected[key] and expected[key]~=id then issue(issues,'item_not_equipped',key) end
  if id~=0 and not item then issue(issues,'unknown_item_base',key) end
  if item then
   if seenItems[id] then issue(issues,'duplicate_physical_item',key) end
   seenItems[id]=true
   equipped[#equipped+1]={slot=key,saved_item_id=not item._companionTrade and id or nil,origin=item._companionTrade and 'trade_candidate' or 'saved_build',level_required=tonumber((item.requirements or {}).level) or 0}
   if not item.base then issue(issues,'unknown_item_base',key)
   else
    if not build.itemsTab:IsItemValidForSlot(item,name) then issue(issues,'slot_incompatible',key) end
    itemChecks(item,key,out,env,issues)
   end
  end
 end
 -- Check every active item PoB accounts for, including jewels/charms/flasks.
 for _,req in ipairs(env.requirementsTableItems or {}) do
  local key=nil
  for _,k in ipairs(slotKeys) do if slotName(k)==req.sourceSlot then key=k end end
  if not key then itemChecks(req.sourceItem,nil,out,env,issues) end
 end
 -- Engine ReqStr/Dex/Int include support totals, global requirements and
 -- special highest-attribute/Strength substitution mechanics.
 if not env.modDB:Flag(nil,'IgnoreAttributeRequirements') then
  for _,attr in ipairs({'Str','Dex','Int'}) do
   if (out['Req'..attr] or 0) > (out[attr] or 0) then issue(issues,'attribute_requirement',nil,attr,out['Req'..attr],out[attr] or 0) end
  end
 end
 for _,req in ipairs(env.requirementsTableGems or {}) do
  local g=req.sourceGem
  if g then
   local lv=tonumber(g.reqLevel or (g.grantedEffect and g.grantedEffect.levels and g.grantedEffect.levels[g.level] and g.grantedEffect.levels[g.level].levelRequirement))
   if lv and lv>build.characterLevel then issue(issues,'gem_level_requirement',nil,'Level',lv,build.characterLevel) end
  end
 end
 -- Never silently ignore red/unrecognised item lines, even on unchanged gear.
 for _,item in pairs(env.player.itemList or {}) do
  for _,field in ipairs({'enchantModLines','runeModLines','implicitModLines','explicitModLines'}) do
   for _,line in ipairs(item[field] or {}) do
    if item:CheckModLineVariant(line) and (line.extra or not line.modList) then issue(issues,'unparsed_modifier') end
   end
  end
 end
 for _,group in pairs(build.skillsTab.socketGroupList or {}) do
  if group.enabled then
   for _,g in ipairs(group.gemList or {}) do
    if g.enabled and not g.gemData and not g.grantedEffect then issue(issues,'unknown_gem') end
   end
  end
 end
 -- Same tree version does not prove every allocated node was loaded/parsed.
 for _,id in ipairs(job.expected_node_ids or {}) do
  if not build.spec.nodes[id] then issue(issues,'unknown_passive');issues[#issues].passive_node_id=id end
 end
 for _,node in pairs(build.spec.allocNodes or {}) do
  if node.unknown or node.extra then issue(issues,'unparsed_passive');issues[#issues].passive_node_id=node.id end
 end
 for _,values in pairs(env.itemWarnings or {}) do if type(values)=='table' and next(values) then issue(issues,'engine_item_warning') end end
 if env.player.mainSkill and env.player.mainSkill.disableReason then issue(issues,'skill_unusable') end
 -- Include all warnings generated by PoB without returning their arbitrary text.
 if build.controls.warnings and next(build.controls.warnings.lines or {}) then issue(issues,'engine_item_warning') end
 for _,key in ipairs({'LifeUnreserved','ManaUnreserved','SpiritUnreserved'}) do
  if type(out[key])=='number' and out[key]<0 then issue(issues,'reservation_invalid') end
 end
 local config=build.configTab.input
 if build.spec.treeVersion ~= latestTreeVersion then issue(issues,'unsupported_tree_version') end
 if config.customMods and config.customMods:match('%S') then issue(issues,'custom_modifiers_present') end
 local configSet=build.configTab.configSets[build.configTab.activeConfigSetId]
 for _,block in ipairs(configSet and configSet.customModsList or {}) do
  if block.enabled~=false and type(block.text)=='string' and block.text:match('%S') then issue(issues,'custom_modifiers_present') end
 end
 if config.ignoreJewelLimits or config.ignoreItemDisablers then issue(issues,'ignored_limits') end
 if sequenceOk==false then issue(issues,'equip_sequence_unverified') end
 local uncertain={unparsed_modifier=true,unparsed_passive=true,unknown_passive=true,unsupported_skill_stat=true,unknown_item_base=true,unknown_gem=true,engine_item_warning=true,equip_sequence_unverified=true,custom_modifiers_present=true,ignored_limits=true,configuration_override=true}
 local status='pass'
 for _,v in ipairs(issues) do
  if not uncertain[v.code] then status='fail';break end
  status='indeterminate'
 end
 local count=#issues
 local uniqueIssues,seenIssues=array(),{}
 for _,v in ipairs(issues) do
  local key=json.encode(v)
  if not seenIssues[key] then seenIssues[key]=true;uniqueIssues[#uniqueIssues+1]=v end
 end
 local truncated=#uniqueIssues>16
 while #uniqueIssues>16 do table.remove(uniqueIssues) end
 return {stats=stats,equipped=equipped,issues=uniqueIssues,issue_count=count,issues_truncated=truncated,validation=status,equip_order=array(order),active_weapon_set=build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1,main_skill_group=build.mainSocketGroup or 0,selected_skill=selectedSkill,full_dps_enabled=fullDpsEnabled}
end
local function scenario(changes)
 load()
 local expected, imported, originals={}, {}, {}
 for _,k in ipairs(slotKeys) do originals[k]=selected(slotName(k)) end
 -- Import items privately with PoB's official character item importer.
 for _,c in ipairs(changes) do
  local name=slotName(c.slot)
  if c.item then
   for _,rune in ipairs(c.item.socketedItems or {}) do
    assert(build.data.itemMods.Runes[rune.baseType])
   end
   build.importTab:ImportItem(c.item,name)
   local id=selected(name)
   local item=build.itemsTab.items[id]
   assert(id~=0 and item and item.uniqueID==c.item.id)
   item._companionTrade=true
   imported[c.slot]=id
  else
   assert(c.saved_item_id==0 or build.itemsTab.items[c.saved_item_id])
   imported[c.slot]=c.saved_item_id
  end
  local candidate=build.itemsTab.items[imported[c.slot]]
  if candidate and c.slot~='weapon_main' and c.slot~='weapon_off' then
   local slotType=name:match('^([%a ]+) %d+$') or name
   if candidate.type~=slotType then
    return {stats=array(),equipped=array(),issues=array({{code='slot_incompatible',slot=c.slot}}),issue_count=1,validation='fail',equip_order=array(),active_weapon_set=build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1,main_skill_group=build.mainSocketGroup or 0}
   end
  end
 end
 for _,k in ipairs(slotKeys) do selectItem(slotName(k),originals[k]) end
 -- Try all insertion orders, removing all replaced gear first. This proves a
 -- conservative equip path without crediting a new item its own attributes.
 local function tryOrder(order)
  for _,k in ipairs(slotKeys) do selectItem(slotName(k),originals[k]) end
  for _,c in ipairs(changes) do selectItem(slotName(c.slot),0) end
  refresh()
  for _,c in ipairs(order) do
   local id=imported[c.slot]
   if id~=0 then
    local item=build.itemsTab.items[id];local issues={}
    itemChecks(item,c.slot,build.calcsTab.mainOutput,build.calcsTab.mainEnv,issues)
    if #issues>0 or not build.itemsTab:IsItemValidForSlot(item,slotName(c.slot)) then return false end
    selectItem(slotName(c.slot),id);refresh()
   end
  end
  return true
 end
 local order,success={},false
 local function permute(prefix,used)
  if success then return end
  if #prefix==#changes then
   if tryOrder(prefix) then success=true; for _,c in ipairs(prefix) do order[#order+1]=c.slot end end
   return
  end
  for i,c in ipairs(changes) do if not used[i] then used[i]=true;prefix[#prefix+1]=c;permute(prefix,used);prefix[#prefix]=nil;used[i]=nil end end
 end
 permute({}, {})
 -- Always evaluate the requested final state; PoB may reject the offhand.
 for _,k in ipairs(slotKeys) do selectItem(slotName(k),originals[k]);expected[k]=originals[k] end
 for _,c in ipairs(changes) do selectItem(slotName(c.slot),imported[c.slot]);expected[c.slot]=imported[c.slot] end
 refresh()
 return inspect(expected,order,success)
end
load()
local baseline=inspect()
local results=array()
for _,changes in ipairs(job.scenarios) do
 local ok,value=pcall(scenario,changes)
 if ok then results[#results+1]=value
 else results[#results+1]={stats=array(),equipped=array(),issues=array({{code='scenario_calculation_failed'}}),issue_count=1,validation='indeterminate',equip_order=array(),active_weapon_set=baseline.active_weapon_set,main_skill_group=baseline.main_skill_group} end
end
io.stdout:write(json.encode({baseline=baseline,results=results}))
