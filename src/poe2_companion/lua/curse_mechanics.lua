-- Canonical bounded projections; export bodies and item text stay private.
local M = {}
local calcs = require('Modules.CalcBase')
local function array(t) return setmetatable(t or {}, {__jsontype='array'}) end
local function metric(rows,name,value)
 if type(value)=='number' and value==value and math.abs(value)<1e15 then rows[#rows+1]={name=name,value=value} end
end
local function cachedOutput(env,skill)
 if env.player.mainSkill==skill then return env.player.output end
 local cached=(GlobalCache.cachedData[env.mode] or {})[cacheSkillUUID(skill,env)]
 return cached and cached.Env and cached.Env.player and cached.Env.player.output or {}
end
function M.apply_configuration(build,configuration)
 configuration=configuration or {}
 if configuration.charged_mark_ground_active~=nil then build.configTab.input.companionChargedMarkGroundActive=configuration.charged_mark_ground_active end
 if configuration.rite_of_passage_spirit~=nil then build.configTab.input.companionRiteOfPassageSpirit=configuration.rite_of_passage_spirit end
end
function M.inspect(build,env,out,configuration)
 local rows,issues=array(),array()
 local function add(name,id,metrics,inputs,status)
  rows[#rows+1]={mechanic=name,skill_id=id,metrics=array(metrics),required_inputs=array(inputs),status=status or (#inputs>0 and 'partial' or 'calculated')}
 end
 local seen={}
 for _,skill in ipairs(env.player.activeSkillList or {}) do
  local id=skill.activeEffect.grantedEffect.id
  if calcs.companionIsActiveSkill(env,skill) and not seen[skill.activeEffect.srcInstance]
   and (skill.skillTypes[SkillType.AppliesCurse] or skill.skillTypes[SkillType.Mark]) then
   seen[skill.activeEffect.srcInstance]=true
   local metrics={}
   local maximum=skill.skillData.curseTargetLevelLimit or 0
   local allowed=maximum<=0 or env.enemyLevel<=maximum
   local applied=false
   for _,buff in ipairs(skill.buffList or {}) do
    for _,curse in ipairs(env.curseSlots or {}) do
     if allowed and curse.name==buff.name and curse.sourceInstance==skill.activeEffect.srcInstance then applied=true end
    end
   end
   metric(metrics,'curse_maximum_target_level',maximum)
   metric(metrics,'curse_target_level',env.enemyLevel)
   metric(metrics,'curse_target_level_allowed',allowed and 1 or 0)
   metric(metrics,'curse_applied',applied and 1 or 0)
   metric(metrics,'curse_applies_as_aura',(skill.skillTypes[SkillType.Aura] or skill.skillData.curseAppliesAsAura) and 1 or 0)
   metric(metrics,'mark_targets_per_type',skill.skillData.markTargetsPerType)
   add('curse_application',id,metrics,{})
  end
  local source=calcs.companionChargedMarkSource and calcs.companionChargedMarkSource(env,skill)
  if source then
   local metrics,inputs={},{}
   local own=cachedOutput(env,skill)
   local duration=own.Duration
   if not duration then
    local base=(skill.skillData.duration or 0)+skill.skillModList:Sum('BASE',skill.skillCfg,'Duration','PrimaryDuration')
    duration=math.ceil(base*math.max(0,calcLib.mod(skill.skillModList,skill.skillCfg,'Duration','PrimaryDuration','DamagingAilmentDuration'))*data.misc.ServerTickRate)/data.misc.ServerTickRate
   end
   local radius=own.AreaOfEffectRadiusMetres
   if not radius then
    -- Match CalcOffence's integer radius breakpoints, including flat radius.
    local base=(skill.skillData.radius or 0)+(skill.skillData.radiusExtra or 0)+skill.skillModList:Sum('BASE',skill.skillCfg,'AreaOfEffect')
    local percent=math.floor(100*math.sqrt(math.max(0,calcLib.mod(skill.skillModList,skill.skillCfg,'AreaOfEffect'))))
    percent=math.floor(percent*calcLib.mod(skill.skillModList,skill.skillCfg,'AreaOfEffectRadius'))
    radius=math.floor(base*percent/100)/10
   end
   metric(metrics,'charged_mark_trigger_chance_percent',skill.skillData.chargedMarkTriggerChance)
   metric(metrics,'charged_mark_ground_duration_seconds',duration)
   metric(metrics,'charged_mark_ground_radius_metres',radius)
   metric(metrics,'charged_mark_ground_active',env.companionChargedMarkGround and 1 or 0)
   metric(metrics,'charged_mark_triggered_skill_level',skill.activeEffect.level)
   if env.configInput.companionChargedMarkGroundActive==nil then inputs={'charged_mark_ground_active'} end
   add('charged_mark','TriggeredChargedMarkPlayer',metrics,inputs)
  end
 end
 local available=calcs.companionRiteAvailability and calcs.companionRiteAvailability(env) or {}
 if next(available) then
  local metrics,inputs={},{}
  local state=env.companionRitePossession
  metric(metrics,'rite_of_passage_possession_active',state and 1 or 0)
  metric(metrics,'rite_of_passage_base_possession_duration_seconds',state and state.duration)
  if env.configInput.companionRiteOfPassageSpirit=='none' then
   add('rite_of_passage',nil,metrics,inputs,'inactive')
  elseif not state then
   add('rite_of_passage',nil,metrics,{'rite_of_passage_spirit'},'requires_configuration')
  else
   inputs[#inputs+1]='spirit_summon_rotation'
   if state.spirit=='ox' then inputs[#inputs+1]='slowing_debuffs' end
   add('rite_of_passage',nil,metrics,inputs,'partial')
  end
 end
 return rows,issues
end
return M
