-- Narrow, inspected dependency proofs; absence of a proof keeps a metric blocked.
local M={}
local array=function(t) return setmetatable(t or {},{__jsontype='array'}) end
local equipmentFailures={level_requirement=true,attribute_requirement=true,class_requirement=true,slot_incompatible=true,
 item_not_equipped=true,gem_level_requirement=true,reservation_invalid=true,duplicate_physical_item=true,
 companion_limit_exceeded=true,duplicate_companion_type=true,unique_companion_limit_exceeded=true,unique_companion_not_allowed=true}
local scopedIssues={missing_combat_assumption=true,charge_sustain_unverified=true,conditional_recoup_unverified=true}
local scopedMechanics={leech_recovery=true,leech_uptime_scenario=true,charge_gain=true,charge_consumption=true,charge_regulation=true,charge_skill_gain=true,
 ghost_dance=true,deflected_recoup=true,impale_generation=true,impale_extraction=true}
local dependencies={
 Life={'Life','ExtraLife','LifeTotal','LifeConvertToEnergyShield','LifeConvertToArmour','LifeConvertToEvasion','ChaosInoculation','Str','StrExtra','All','AllExtra','Devotion'},
 Mana={'Mana','ExtraMana','ManaTotal','ManaConvertToEnergyShield','ManaConvertToArmour','ManaConvertToEvasion','Int','IntExtra','All','AllExtra','Devotion'},
 EnergyShield={'EnergyShield','EnergyShieldTotal','Defences','Int','IntExtra','All','AllExtra','Devotion','CannotHaveES'},
}
for _,names in pairs(dependencies) do
 for _,name in ipairs({'NoAttributeBonuses','DoubledInherentAttributeBonuses','NoStrengthAttributeBonuses','NoStrBonusToLife',
  'HalvesLifeFromStrength','NoIntelligenceAttributeBonuses','NoIntBonusToMana','Dex','DexExtra','Attributes','Omniscience',
  'DoubleBodyArmourDefence','EnergyShieldToWard'}) do names[#names+1]=name end
 for _,source in ipairs({'Life','Mana','Ward','Armour','Evasion','EnergyShield'}) do
  for _,target in ipairs({'Life','Mana','Ward','Armour','Evasion','EnergyShield'}) do
   names[#names+1]=source..'ConvertTo'..target;names[#names+1]=source..'GainAs'..target
  end
 end
end
local function unconditional(modDB,names)
 local wanted={};for _,name in ipairs(names) do wanted[name]=true end
 local function check(store)
  if not store then return true end
  for name,list in pairs(store.mods or {}) do
   if wanted[name] then
    for _,mod in ipairs(list) do
     -- Tags encode conditional, per-stat and actor dependencies. None may be
     -- dismissed merely because the current combat assumption selects false.
     if type(mod.value)=='table' then return false end
     for _,tag in ipairs(mod) do
      -- The pinned engine's base resource growth depends only on character
      -- level, which equipment scenarios cannot change. Other tags need a
      -- separately proved graph and remain blocked.
      if not (mod.source=='Base' and tag.type=='Multiplier' and tag.var=='Level') then return false end
     end
    end
   end
  end
  return check(store.parent)
 end
 return check(modDB)
end
function M.inspect(env,out,stats,issues,mechanics,validation)
 local equipment='pass';local scoped=true
 for _,issue in ipairs(issues) do
  if equipmentFailures[issue.code] then equipment='fail' end
  if not equipmentFailures[issue.code] and not scopedIssues[issue.code] and equipment~='fail' then equipment='indeterminate' end
  if issue.code=='equip_sequence_unverified' and equipment~='fail' then equipment='indeterminate' end
  if not scopedIssues[issue.code] then scoped=false end
 end
 for _,m in ipairs(mechanics) do
  if (m.status=='partial' or m.status=='unsupported' or m.status=='requires_configuration') and not scopedMechanics[m.mechanic] then scoped=false end
 end
 local coverage=array()
 for _,stat in ipairs(stats) do
  local reason='unresolved_dependency';local status='indeterminate'
  if validation=='pass' then status='pass';reason='all_rules_validated'
  elseif scoped and dependencies[stat.name] and unconditional(env.modDB,dependencies[stat.name]) then
   -- Reject transformations/overrides; their dependency graphs are separate.
   local name=stat.name
   local db=env.modDB
   local conv=db:Sum('BASE',nil,name..'ConvertToEnergyShield',name..'ConvertToArmour',name..'ConvertToEvasion')
   local extra=db:Sum('BASE',nil,'Extra'..name,name..'Total')
   local override=db:Override(nil,name)
   if name=='EnergyShield' then
    local transformed=false
    for _,source in ipairs({'Life','Mana','Ward','Armour','Evasion','EnergyShield'}) do
     for _,target in ipairs({'Life','Mana','Ward','Armour','Evasion','EnergyShield'}) do
      if db:Sum('BASE',nil,source..'ConvertTo'..target,source..'GainAs'..target)~=0 then transformed=true end
     end
    end
    if not transformed and override==nil and not db:Flag(nil,'CannotHaveES') then
     local base=db:Sum('BASE',nil,'EnergyShield')
     for _,slot in ipairs({'Helmet','Gloves','Boots','Body Armour','Weapon 2','Weapon 3'}) do
      local item=env.player.itemList[slot]
      if item and item.armourData then base=base+item:GetArmourDataValue('EnergyShield',env.player.level) end
     end
     local expected=math.max(round(base*(1+db:Sum('INC',nil,'EnergyShield','Defences')/100)*db:More(nil,'EnergyShield','Defences')+db:Sum('BASE',nil,'EnergyShieldTotal')),0)
     if expected==out.EnergyShield then status='pass';reason='unconditional_resource_dependency_verified' end
    end
   elseif conv==0 and extra==0 and override==nil and not db:Flag(nil,'ChaosInoculation') then
    local expected=math.max(round(db:Sum('BASE',nil,name)*(1+db:Sum('INC',nil,name)/100)*db:More(nil,name)),1)
    if expected==out[name] then status='pass';reason='unconditional_resource_dependency_verified' end
   end
  end
  coverage[#coverage+1]={stat=stat.name,status=status,reason=reason}
 end
 return equipment,coverage
end
return M
