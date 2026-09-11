-- Private, one-job process. Only closed numeric projections leave stdout.
-- Uses commit-pinned community PoE2 PoB modules and reviewed data (MIT).
print = function() end
local json = require('dkjson')
local job = assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
assert(build and not __mainObject__.promptMsg)
local companionRoot = assert(arg[0]:match('^(.*[/\\])'))
local subjects=dofile(companionRoot..'subjects.lua')
local savedSubject,selectionError
local stonefist = dofile(companionRoot..'stonefist.lua')
local companions = dofile(companionRoot..'companions.lua')
local skillCoverage = dofile(companionRoot..'skill_coverage.lua')
local weaponContext = dofile(companionRoot..'weapon_context.lua')
local martialMechanics = dofile(companionRoot..'martial_mechanics.lua')
local spiritVessel = dofile(companionRoot..'spirit_vessel.lua')
local damageRules = dofile(companionRoot..'damage_rules.lua')
local hitBuffs = dofile(companionRoot..'hit_buffs.lua')
local curseMechanics = dofile(companionRoot..'curse_mechanics.lua')
local beastMetadata = dofile(companionRoot..'beast_metadata.lua')
local beastAuras = dofile(companionRoot..'beast_auras.lua')
stonefist.register()
companions.register()
-- Exact crafting-only lines in the pinned 0.5.5 data affect future item
-- modification, not the current combat stats. No broad pattern suppression.
-- See upstream PR2509 (crafting influences) and ModRunes' Atziri cores.
for _,line in ipairs({'Can roll Ring Modifiers','Can roll Chronomancy modifiers',
 'Can roll Marksman modifiers','Can roll Berserking modifiers',
 'Can roll Destruction modifiers','Can roll Soul modifiers','Can roll Decay modifiers',
 'Corrupting will always result in change'}) do
 modLib.parseModCache[line]={{},nil}
end
-- The Vertex's equipment variant also covers weapons. The upstream weapon
-- multiplier includes GlobalItemAttributeRequirements; gem requirements use
-- a separate multiplier and must remain intact.
modLib.parseModCache['Equipment has no Attribute Requirements']={{
 modLib.createMod('GlobalItemAttributeRequirements','MORE',-100,'PoE2Companion')},nil}
local slots = {helmet='Helmet',body_armour='Body Armour',gloves='Gloves',boots='Boots',belt='Belt',amulet='Amulet',ring_left='Ring 1',ring_right='Ring 2',weapon_main='Weapon 1',weapon_off='Weapon 2'}
local slotKeys = {'helmet','body_armour','gloves','boots','belt','amulet','ring_left','ring_right','weapon_main','weapon_off'}
local statKeys = {'Life','LifeUnreserved','Mana','ManaUnreserved','EnergyShield','Armour','Evasion','DeflectionRating','FireResist','ColdResist','LightningResist','ChaosResist','BlockChance','SpellBlockChance','Str','Dex','Int','TotalDPS','CombinedDPS','FullDPS','Speed','CritChance','CritMultiplier'}
for _,key in ipairs({'FireResistTotal','ColdResistTotal','LightningResistTotal','ChaosResistTotal','FireResistOverCap','ColdResistOverCap','LightningResistOverCap','ChaosResistOverCap','PhysicalMaximumHitTaken','FireMaximumHitTaken','ColdMaximumHitTaken','LightningMaximumHitTaken','ChaosMaximumHitTaken','LifeRegen','ManaRegen','EnergyShieldRegen','LifeLeechRate','ManaLeechRate','EnergyShieldLeechRate','TotalEHP'}) do statKeys[#statKeys+1]=key end
local function array(t) return setmetatable(t or {}, {__jsontype='array'}) end
local function refresh()
 build.buildFlag = true
 runCallback('OnFrame')
 assert(build.calcsTab.mainOutput and not __mainObject__.promptMsg)
end
local savedConfig,configurationAliases
local function load()
 if GlobalCache and GlobalCache.cachedData then wipeGlobalCache() end
 loadBuildFromXML(job.xml, '')
 assert(build and build.savers and build.targetVersion==liveTargetVersion and build.calcsTab and build.calcsTab.mainOutput and not __mainObject__.promptMsg)
 savedSubject=subjects.resolve(build)
 if beastMetadata.apply(build,job.beast_metadata) then
  if GlobalCache and GlobalCache.cachedData then wipeGlobalCache() end
  refresh()
 end
 if weaponContext.activate(build) then refresh() end
 if job.inspection and job.inspection.section=='configuration' and job.inspection.set_id then
  assert(build.configTab.configSets[job.inspection.set_id])
  build.configTab:SetActiveConfigSet(job.inspection.set_id)
  refresh()
 end
 savedConfig={};for key,value in pairs(build.configTab.input) do savedConfig[key]=value end
 local configuration=job.configuration
  local aliases={ghost_shroud_lost_recently='conditionLostGhostShroudRecently',
   refutation_active='conditionRefutationActive',refutation_ward_spent='refutationWardSpent',
   tempest_bell_prior_hits='tempestBellPriorHits',tempest_bell_knockback_metres='tempestBellKnockbackMetres',
   enemy_maimed='conditionEnemyMaimed',enemy_blinded='conditionEnemyBlinded',
   wind_dancer_stages='windDancerStacks',impale_magnitude='companionImpaleMagnitude',
   leech_resistance_percent='companionLeechResistance',onslaught_active='buffOnslaught',
   thrill_of_the_kill_active='companionThrillOfTheKillActive',
   culling_strike_recent_cull='companionCullingStrikeRecentCull'}
 configurationAliases=aliases
 if configuration then
  if configuration.tempest_bell_ailment_types then
   local selected={}
   for _,element in ipairs(configuration.tempest_bell_ailment_types) do selected[element]=true end
   for _,element in ipairs({'Fire','Cold','Lightning'}) do
    build.configTab.input['conditionTempestBell'..element..'Ailment']=selected[element:lower()] or false
   end
  end
  for key,name in pairs(aliases) do
   if configuration[key]~=nil then build.configTab.input[name]=configuration[key] end
  end
  companions.apply_configuration(build,configuration)
  curseMechanics.apply_configuration(build,configuration)
  beastAuras.apply_configuration(build,configuration)
  if stonefist.apply_configuration then stonefist.apply_configuration(build,configuration) end
  build.configTab:BuildModList()
  if GlobalCache and GlobalCache.cachedData then wipeGlobalCache() end
  refresh()
  if configuration.spirit_vessel_skill_id then
   assert(spiritVessel.configure(build,configuration.spirit_vessel_skill_id))
   if GlobalCache and GlobalCache.cachedData then wipeGlobalCache() end
   refresh()
  end
 end
 selectionError=subjects.select(build,job.target,refresh)
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
 if not env.modDB:Flag(nil,'IgnoreAttributeRequirements') and not stonefist.ignore_glove_attributes(item,env) then
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
 local stats,equipped,issues,mechanics=array(),array(),array(),array()
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
 local canonicalEffect=effect and effect.id and build.data.skills[effect.id]
 if canonicalEffect then
  selectedSkill={skill_id=effect.id,name=canonicalEffect.name,actor=mainSkill.minion and 'minion' or 'player'}
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
 -- Chakra rune modifiers bypass item mod-line parsing in upstream CalcSetup.
 -- Validate their selected names and all actually applied (non-Bonded) lines.
 if env.modDB:Flag(nil,'SocketRunesOnCharacter') then
  for name,slot in pairs(build.itemsTab.runeSlots or {}) do
   local rune=slot:GetSelValue()
   local saved=build.itemsTab.activeItemSet[name]
   if saved and saved.runeName~='None' and (not rune or rune.name~=saved.runeName) then
    issue(issues,'unknown_rune')
   elseif rune and rune.name~='None' then
    if rune.req and rune.req>build.characterLevel then issue(issues,'level_requirement',nil,'Level',rune.req,build.characterLevel) end
    for _,line in ipairs(rune.lines or {}) do
     if not line:match('^Bonded:') then
      local mods,extra=modLib.parseMod(line)
      if not mods or extra then issue(issues,'unparsed_modifier') end
     end
    end
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
 for _,module in ipairs({stonefist,companions,martialMechanics,spiritVessel,damageRules,hitBuffs,curseMechanics,beastAuras}) do
  local moduleMechanics,moduleIssues=module.inspect(build,env,out,job.configuration)
  for _,entry in ipairs(moduleMechanics) do mechanics[#mechanics+1]=entry end
  for _,entry in ipairs(moduleIssues) do issues[#issues+1]=entry end
 end
 for _,entry in ipairs(skillCoverage.inspect(build)) do issues[#issues+1]=entry end
 for _,entry in ipairs(weaponContext.inspect(build)) do issues[#issues+1]=entry end
 -- A new projection module must not accidentally certify an incomplete
 -- calculation merely because it omitted a parallel requirement issue.
 local missingAssumptions={}
 for _,entry in ipairs(issues) do
  if entry.code=='missing_combat_assumption' then missingAssumptions[entry.skill_id or '']=true end
 end
 for _,entry in ipairs(mechanics) do
  if entry.status=='partial' or entry.status=='unsupported' or entry.status=='requires_configuration' then
   local key=entry.skill_id or ''
   if not missingAssumptions[key] then
    issues[#issues+1]={code='missing_combat_assumption',skill_id=entry.skill_id}
    missingAssumptions[key]=true
   end
  end
 end
 local uncertain={unparsed_modifier=true,unparsed_passive=true,unknown_passive=true,unknown_rune=true,unsupported_skill_stat=true,unknown_item_base=true,unknown_gem=true,engine_item_warning=true,equip_sequence_unverified=true,custom_modifiers_present=true,ignored_limits=true,configuration_override=true,
  unsupported_item_transformation=true,stonefist_passive_missing=true,charge_sustain_unverified=true,ally_charge_state_unverified=true,conditional_recoup_unverified=true,companion_identity_unverified=true,unsupported_companion_mechanic=true,missing_companion_data=true,missing_combat_assumption=true,unsupported_weapon_context=true,granted_skill_source_unresolved=true}
 local status='pass'
 for _,v in ipairs(issues) do
  if not uncertain[v.code] then status='fail';break end
  status='indeterminate'
 end
 local binding=subjects.bind(build,job.target,savedSubject,selectionError,job.scenario_digest)
 if binding.status=='unavailable' then
  issue(issues,'target_unavailable');status='indeterminate';stats=array();mechanics=array();selectedSkill=nil
 end
 local count=#issues
 local uniqueIssues,seenIssues=array(),{}
 for _,v in ipairs(issues) do
  local key=json.encode(v)
  if not seenIssues[key] then seenIssues[key]=true;uniqueIssues[#uniqueIssues+1]=v end
 end
 local truncated=false
 local mechanicCount=#mechanics
 local combat=job.combat_scenario and stonefist.simulate(build,env,out,job.combat_scenario) or nil
 local equipmentValidity,coverage=dofile(companionRoot..'metric_coverage.lua').inspect(env,out,stats,uniqueIssues,mechanics,status)
 return {subject=binding,stats=stats,equipped=equipped,issues=uniqueIssues,issue_count=count,issues_truncated=truncated,validation=status,equipment_validity=equipmentValidity,metric_coverage=coverage,equip_order=array(order),active_weapon_set=build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1,main_skill_group=build.mainSocketGroup or 0,selected_skill=selectedSkill,full_dps_enabled=fullDpsEnabled,mechanics=mechanics,mechanic_count=mechanicCount,mechanics_truncated=mechanicCount>#mechanics,combat_scenario=combat,combat_scenario_status=combat and combat.status or nil}
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
   if c.item.socketedItems and #c.item.socketedItems>0 then
    local validRunes={}
    for _,rune in ipairs(build.itemsTab:GetValidRunesForItem(item)) do validRunes[rune.name]=true end
    for _,rune in ipairs(c.item.socketedItems) do assert(validRunes[rune.baseType]) end
   end
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
 -- Try sequential replacements, retaining other original items until their turn.
 -- Remove the current slot before checking, never crediting its own attributes.
 local function tryOrder(order)
  for _,k in ipairs(slotKeys) do selectItem(slotName(k),originals[k]) end
  refresh()
  for _,c in ipairs(order) do
   selectItem(slotName(c.slot),0);refresh()
   local id=imported[c.slot]
   if id~=0 then
    local item=build.itemsTab.items[id];local issues={}
    itemChecks(item,c.slot,build.calcsTab.mainOutput,build.calcsTab.mainEnv,issues)
    if #issues>0 or not build.itemsTab:IsItemValidForSlot(item,slotName(c.slot)) then return false end
    selectItem(slotName(c.slot),id);refresh()
   end
   -- Main-hand validity alone does not validate the retained offhand. A
   -- two-handed item can pass its own check while the existing shield fails.
   -- Prove compatibility after every transition, before trying the next one.
   for _,weaponSlot in ipairs({'weapon_main','weapon_off'}) do
    local equipped=build.itemsTab.items[selected(slotName(weaponSlot))]
    if equipped and not build.itemsTab:IsItemValidForSlot(equipped,slotName(weaponSlot)) then return false end
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
 if job.configuration and job.configuration.spirit_vessel_skill_id then
  assert(spiritVessel.configure(build,job.configuration.spirit_vessel_skill_id))
  if GlobalCache and GlobalCache.cachedData then wipeGlobalCache() end
  refresh()
 end
 return inspect(expected,order,success)
end
load()
local baseline=inspect()
local inspection=job.inspection and dofile(companionRoot..'inspection.lua').project(build,job.inspection,savedConfig,configurationAliases) or nil
local results=array()
local experimentAudit
if job.experiment then
 local function experiment()
  load()
  local edits=dofile(companionRoot..'experiments.lua')
  local audit,checks=edits.apply(build,job.experiment,job.experiment_items,slotName,selected,selectItem)
  refresh()
  selectionError=subjects.select(build,job.target,refresh)
  edits.validateSupports(checks)
  local result=inspect(nil,nil,audit.transition_validation~='requires_order_validation')
  return {audit=audit,result=result}
 end
 local ok,value=pcall(experiment)
 if ok then experimentAudit=value.audit;results[1]=value.result
 else
  if type(value)~='table' or not value.code then value={edit_index=0,code='entity_not_found'} end
  experimentAudit={status='rejected_atomically',failures=array{value},applied_edits=array(),base_unchanged=true}
 end
end
for _,changes in ipairs(job.scenarios) do
 local ok,value=pcall(scenario,changes)
 if ok then results[#results+1]=value
 else results[#results+1]={stats=array(),equipped=array(),issues=array({{code='scenario_calculation_failed'}}),issue_count=1,validation='indeterminate',equip_order=array(),active_weapon_set=baseline.active_weapon_set,main_skill_group=baseline.main_skill_group} end
end
io.stdout:write(json.encode({baseline=baseline,results=results,inspection=inspection,experiment_audit=experimentAudit}))
