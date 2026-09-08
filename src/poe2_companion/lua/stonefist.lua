-- Numeric mechanics projections for current Stonefist/charge/Deflection rules.
-- No saved labels, raw lines, character names or payloads leave this module.
local M = {}
local calcs = require('Modules.CalcBase')
local charges = {'Power', 'Frenzy', 'Endurance'}
local function array(t) return setmetatable(t or {}, {__jsontype='array'}) end
local function chance(value) return math.min(math.max(value or 0, 0), 100) end
local function metric(rows, name, value)
 if type(value)=='number' and value==value and math.abs(value)<=1e15 then
  rows[#rows+1]={name=name,value=value}
 end
end
local function entry(name,status,metrics,inputs)
 return {mechanic=name,status=status,metrics=array(metrics),required_inputs=array(inputs)}
end
local function effective_skill(skill,env)
 return calcs.companionIsActiveSkill(env,skill)
end
function M.register()
 -- Source patches run before HeadlessWrapper initialises the passive tree.
 -- Keeping registration explicit allows callers to load the module uniformly.
end
function M.ignore_glove_attributes(item, env)
 return item and item.base and item.base.type=='Gloves' and env.modDB:Flag(nil,'IgnoreGloveAttributeRequirements')
end

function M.inspect(build, env, out)
 local mechanics,issues=array(),array()
 local modDB=env.modDB
 local glove=env.player.itemList and env.player.itemList.Gloves
 local stonefist=modDB:Flag(nil,'WayOfTheStonefist')
 local transformed=glove and (glove.baseName=='Fists of Stone' or glove.baseName=='Runeforged Fists of Stone')
 if stonefist or transformed then
  local status='inactive'
  local inputs={}
  if glove then
   if stonefist and transformed then
    status='calculated'
   elseif stonefist then
    status='unsupported';inputs={'transformed_glove_data'}
    issues[#issues+1]={code='unsupported_item_transformation',slot='gloves'}
   else
    status='unsupported';inputs={'stonefist_passive'}
    issues[#issues+1]={code='stonefist_passive_missing',slot='gloves'}
   end
  end
  mechanics[#mechanics+1]=entry('stonefist',status,{
   {name='glove_attribute_exemption',value=M.ignore_glove_attributes(glove,env) and 1 or 0},
   {name='already_transformed',value=transformed and 1 or 0},
  },inputs)
 end

 -- Gain events, retention and grants are different mechanisms. They cannot
 -- establish sustained charges without the player's event sequence; saved
 -- charge toggles still control the upstream snapshot's consumed charges.
 local gain,ally={},{}
 for _,charge in ipairs(charges) do
  local key=charge:lower()
  local gainChance=chance(modDB:Sum('BASE',nil,'Additional'..charge..'ChargeChance'))
  if gainChance>0 then metric(gain,key..'_extra_charge_chance',gainChance) end
  local allyChance=chance(modDB:Sum('BASE',nil,'GrantAlly'..charge..'ChargeOnHitChance'))
  if allyChance>0 then metric(ally,key..'_grant_chance_per_hit',allyChance) end
 end
 if #gain>0 then
  mechanics[#mechanics+1]=entry('charge_gain','partial',gain,{'charge_gain_events'})
  issues[#issues+1]={code='charge_sustain_unverified'}
 end
 if #ally>0 then
  mechanics[#mechanics+1]=entry('ally_charges','partial',ally,{'ally_presence','ally_charge_events'})
  issues[#issues+1]={code='ally_charge_state_unverified'}
 end

 local main=env.player.mainSkill
 local projectedSkills={}
 for _,active in ipairs(env.player.activeSkillList or {}) do
  local effect=active.activeEffect and active.activeEffect.grantedEffect
  local id=effect and effect.id
  if id and build.data.skills[id] and effective_skill(active,env) and not active.minion then
   local generic=chance(active.skillModList:Sum('BASE',active.skillCfg,'AdditionalChargeChance'))
   local random=chance(active.skillModList:Sum('BASE',active.skillCfg,'AdditionalRandomChargeChance'))
   local dedup=id..':'..generic..':'..random
   if active.skillTypes[SkillType.GeneratesCharges] and (generic>0 or random>0) and not projectedSkills[dedup] then
    projectedSkills[dedup]=true
    local row=entry('charge_skill_gain','partial',{
     {name='same_type_extra_charge_chance',value=generic},
     {name='random_type_extra_charge_chance',value=random},
    },{'charge_gain_events'})
    row.skill_id=id
    mechanics[#mechanics+1]=row
    issues[#issues+1]={code='charge_sustain_unverified'}
   end
   if id=='ChargeRegulationPlayer' and not projectedSkills[id] then
    projectedSkills[id]=true
    local interval=active.skillData and active.skillData.chargeRegulationInterval
    local rows={}
    if interval and interval>0 then
     metric(rows,'regulation_interval_seconds',interval)
     -- One charge of each available type is consumed per tick. This is the
     -- demand while charges are available, not observed sustained removal.
     metric(rows,'regulation_removals_per_charge_type_per_second',1/interval)
    end
    local row=entry('charge_regulation',#rows>0 and 'partial' or 'unsupported',rows,{'charge_gain_events','charge_consumption_events'})
    row.skill_id=id
    mechanics[#mechanics+1]=row
    issues[#issues+1]={code='charge_sustain_unverified'}
   end
  end
 end
 if main and effective_skill(main,env) and main.skillModList and main.skillTypes and main.skillTypes[SkillType.ConsumesCharges] then
  local rows={}
  local retention=chance(main.skillModList:Sum('BASE',main.skillCfg,'ChargeNotRemovedChance'))
  if retention>0 then
   metric(rows,'charge_retention_chance',retention)
   metric(rows,'expected_removed_fraction',1-retention/100)
   for _,charge in ipairs(charges) do
    if main.skillTypes[SkillType['SkillConsumes'..charge..'ChargesOnUse']] then
     metric(rows,charge:lower()..'_charges_configured',out[charge..'Charges'])
     metric(rows,charge:lower()..'_charges_counted_for_consumption',out['Removable'..charge..'Charges'])
    end
   end
   mechanics[#mechanics+1]=entry('charge_consumption','partial',rows,{'charge_gain_events','charge_consumption_events'})
   issues[#issues+1]={code='charge_sustain_unverified'}
  end
 end

 local recoup=modDB:Sum('BASE',nil,'DeflectedLifeRecoup')
 if recoup>0 then
  local rows={}
  metric(rows,'life_recoup_percent_per_deflected_hit',recoup*(out.LifeRecoveryRateMod or 1))
  metric(rows,'recoup_duration_seconds',(modDB:Flag(nil,'4SecondLifeRecoup') or modDB:Flag(nil,'4SecondRecoup')) and 4 or 8)
  metric(rows,'deflect_chance',out.DeflectChance)
  metric(rows,'energy_shield_recharge_delay',out.EnergyShieldRechargeDelay)
  mechanics[#mechanics+1]=entry('deflected_recoup','partial',rows,{'incoming_hit_sequence'})
  issues[#issues+1]={code='conditional_recoup_unverified'}
 end
 return mechanics,issues
end
return M
