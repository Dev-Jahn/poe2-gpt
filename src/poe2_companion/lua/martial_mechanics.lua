-- Public projections contain canonical IDs and bounded numbers only.
local M = {}
local calcs = require('Modules.CalcBase')
local function array(t) return setmetatable(t or {}, {__jsontype='array'}) end
local function metric(rows,name,value)
 if type(value)=='number' and value==value and math.abs(value)<=1e15 then rows[#rows+1]={name=name,value=value} end
end
local function row(name,id,metrics,inputs,status)
 return {mechanic=name,skill_id=id,status=status or (#inputs>0 and 'partial' or 'calculated'),metrics=array(metrics),required_inputs=array(inputs)}
end
local function stats(env,active,index)
 local effect=active.activeEffect
 local set=effect.grantedEffect.statSets[index or 1]
 return calcLib.buildSkillInstanceStats(effect,effect.grantedEffect,set,env.useAltGemQualityStats)
end
local function cachedOutput(env,active)
 if active==env.player.mainSkill then return env.player.output end
 local cache=GlobalCache.cachedData[env.mode] or {}
 local entry=cache[cacheSkillUUID(active,env)]
 return entry and entry.Env and entry.Env.player and entry.Env.player.output or {}
end
local function cooldownInterval(active,base)
 local rate=calcLib.mod(active.skillModList,active.skillCfg,'CooldownRecovery')
 -- These are periodic generation timers, not a skill cooldown. Added
 -- cooldown uses and flat cooldown reductions do not change the period.
 return rate>0 and base/rate or nil
end
function M.register() end
function M.inspect(build,env,out,configuration)
 configuration=configuration or {}
 local result,issues=array(),array()
 local seen={}
 for _,active in ipairs(env.player.activeSkillList or {}) do
  local effect=active.activeEffect and active.activeEffect.grantedEffect
  local id=effect and effect.id
  if (id=='GhostDancePlayer' or id=='HollowFocusPlayer' or id=='MetaHollowFormPlayer' or id=='TempestBellPlayer' or id=='WindDancerPlayer' or id=='RefutationPlayer')
   and calcs.companionIsActiveSkill(env,active)
   and not (calcs.companionIsGrantMirror and calcs.companionIsGrantMirror(env,active))
   and not seen[active.activeEffect.srcInstance or active] then
   seen[active.activeEffect.srcInstance or active]=true
   local values,inputs={},{}
   local base=stats(env,active)
   if id=='GhostDancePlayer' then
    local interval=cooldownInterval(active,(base.base_cooldown_modifiable_repeat_interval_ms or 0)/1000)
    metric(values,'ghost_shroud_interval_seconds',interval)
    metric(values,'ghost_shroud_maximum',base.ghost_dance_max_stacks)
    metric(values,'ghost_shroud_evasion_percent_per_second',(base['skill_base_ghost_dance_grants_%_evasion_as_es_regeneration_per_minute_if_have_lost_ghost_dance_shroud_recently'] or 0)/60)
    metric(values,'ghost_shroud_base_es_regeneration_per_second',(out.Evasion or 0)*(base['skill_base_ghost_dance_grants_%_evasion_as_es_regeneration_per_minute_if_have_lost_ghost_dance_shroud_recently'] or 0)/6000)
    metric(values,'energy_shield_regeneration_per_second',out.EnergyShieldRegenRecovery or 0)
    metric(values,'recently_window_seconds',4)
    metric(values,'ghost_shroud_recent_loss_configured',env.configInput.conditionLostGhostShroudRecently and 1 or 0)
    if env.configInput.conditionLostGhostShroudRecently==nil then
     inputs={'ghost_shroud_lost_recently'}
     issues[#issues+1]={code='missing_combat_assumption',skill_id=id}
    end
    result[#result+1]=row('ghost_dance',id,values,inputs)
   elseif id=='RefutationPlayer' then
    local own=cachedOutput(env,active)
    local spent=env.configInput.refutationWardSpent
    local enabled=env.modDB:Flag(nil,'RefutationAutomaticBlock')
    local cooldown=own.Cooldown
    local duration=own.Duration
    if not duration then duration=(base.base_skill_effect_duration or 0)/1000*calcLib.mod(active.skillModList,active.skillCfg,'Duration') end
    metric(values,'refutation_stun_threshold',out.StunThreshold)
    metric(values,'refutation_stun_threshold_multiplier',env.modDB:More(nil,'RefutationStunThreshold','RefutationWardStunThreshold'))
    metric(values,'refutation_blockable_hit_block_chance',enabled and out.EffectiveAverageBlockChance or 0)
    metric(values,'refutation_light_stun_immunity',enabled and 1 or 0)
    metric(values,'refutation_buff_duration_seconds',duration)
    metric(values,'refutation_cycle_seconds',cooldown and cooldown+duration or nil)
    metric(values,'refutation_maximum_uptime_percent',cooldown and duration/(cooldown+duration)*100 or nil)
    metric(values,'refutation_ward_spent',spent)
    if enabled then
     -- Heavy stun can terminate the buff even though light stun cannot.
     -- Do not mistake a blockable-hit snapshot for sustained invulnerability.
     inputs={'incoming_hit_sequence'}
    elseif env.configInput.conditionRefutationActive==nil then
     inputs={'refutation_buff_state'}
    end
    if #inputs>0 then issues[#issues+1]={code='missing_combat_assumption',skill_id=id} end
    result[#result+1]=row('refutation',id,values,inputs)
   elseif id=='WindDancerPlayer' then
    local interval=(base.wind_dancer_stages_gained_every_x_ms or 0)/1000
    local maximum=base.wind_dancer_maximum_number_of_stages or 0
    local configured=env.configInput.windDancerStacks
    metric(values,'wind_dancer_stage_interval_seconds',interval)
    metric(values,'wind_dancer_stage_gain_rate_per_second',interval>0 and 1/interval or nil)
    metric(values,'wind_dancer_maximum_stages',maximum)
    metric(values,'wind_dancer_full_refill_seconds',maximum*interval)
    -- This is the chosen snapshot, not an assertion about hit avoidance.
    if configured~=nil then
     local count=math.min(maximum,math.max(0,configured))
     metric(values,'wind_dancer_configured_stages',count)
     metric(values,'wind_dancer_evasion_more_percent',count*(base['wind_dancer_evasion_rating_+%_final_per_stage'] or 0))
    else
     inputs={'wind_dancer_stages'}
     issues[#issues+1]={code='missing_combat_assumption',skill_id=id}
    end
    result[#result+1]=row('wind_dancer',id,values,inputs)
   elseif id=='TempestBellPlayer' then
    local limit=base.base_number_of_tempest_bells_allowed or 0
    local hits=base.bell_hit_limit or 0
    for _,instance in ipairs(active.effectList or {}) do
     if instance.grantedEffect.support then
      for _,set in ipairs(instance.grantedEffect.statSets or {}) do
       local support=calcLib.buildSkillInstanceStats(instance,instance.grantedEffect,set,env.useAltGemQualityStats)
       limit=limit+(support['base_limit_+'] or 0)
       hits=hits+(support.support_number_of_additional_uses_before_expiry or 0)
      end
     end
    end
    local shockwave=stats(env,active,3)
    local interval=(shockwave.bell_shockwave_cooldown_ms or 0)/1000
    metric(values,'tempest_bell_combo_required',base.active_skill_required_number_of_combo_stacks)
    metric(values,'tempest_bell_combo_decay_seconds',(base.base_combo_stacks_decay_delay_ms or 0)/1000)
    metric(values,'bell_active_limit',limit)
    metric(values,'bell_hits_to_destroy',hits)
    metric(values,'bell_duration_seconds',(base.base_skill_effect_duration or 0)/1000*calcLib.mod(active.skillModList,active.skillCfg,'Duration'))
    metric(values,'tempest_bell_shockwave_interval_seconds',interval)
    metric(values,'tempest_bell_shockwave_rate_limit_per_second',interval>0 and 1/interval or nil)
    inputs={'bell_hit_events','tempest_bell_combo_events'}
    local selected=active.activeEffect.statSet and active.activeEffect.statSet.statSet
    if selected==effect.statSets[3] then
     local detail,assumptions={},{}
     local own=cachedOutput(env,active)
     local hits=active.skillModList:GetMultiplier('TempestBellPriorHits',active.skillCfg)
     metric(detail,'tempest_bell_prior_hits_applied',hits)
     metric(detail,'tempest_bell_damage_more_percent',hits*(shockwave['tempest_bell_damage_+%_final_per_time_hit'] or 0))
     if env.configInput.tempestBellPriorHits==nil or active.companionTempestBellInvalidHitCount then assumptions[#assumptions+1]='bell_hit_events' end
     for _,element in ipairs({'Fire','Cold','Lightning'}) do
      local value=env.configInput['conditionTempestBell'..element..'Ailment']
      metric(detail,'tempest_bell_'..element:lower()..'_gain_percent',value and (shockwave['tempest_bell_physical_damage_%_as_elemental_per_ailment'] or 0) or 0)
      if value==nil and not assumptions.ailments then
       assumptions.ailments=true;assumptions[#assumptions+1]='tempest_bell_ailment_types'
      end
     end
     assumptions.ailments=nil
     metric(detail,'tempest_bell_knockback_area_more_percent',active.skillModList:GetMultiplier('TempestBellKnockbackUnits',active.skillCfg)*(shockwave['tempest_bell_area_of_effect_+%_final_per_1_unit_of_knockback'] or 0))
     if env.configInput.tempestBellKnockbackMetres==nil then assumptions[#assumptions+1]='tempest_bell_knockback_metres' end
     metric(detail,'bell_shockwave_average_damage',own.AverageDamage)
     metric(detail,'tempest_bell_shockwave_area_radius',own.AreaOfEffectRadius)
     result[#result+1]=row('tempest_bell_shockwave',id,detail,assumptions)
    end
    result[#result+1]=row('tempest_bell',id,values,inputs)
    issues[#issues+1]={code='missing_combat_assumption',skill_id=id}
   elseif id=='HollowFocusPlayer' then
    local interval=cooldownInterval(active,(base.base_cooldown_modifiable_repeat_interval_ms or 0)/1000)
    local limit=base.spectral_bells_maximum_active_bells or 0
    -- Overabundance adds a Limit, whereas Second Wind adds cooldown uses.
    -- Upstream aliases these to the same mod; inspect actual compatible
    -- support stats so extra cooldown uses cannot turn into extra bells.
    for _,instance in ipairs(active.effectList or {}) do
     if instance.grantedEffect.support then
      for _,set in ipairs(instance.grantedEffect.statSets or {}) do
       local support=calcLib.buildSkillInstanceStats(instance,instance.grantedEffect,set,env.useAltGemQualityStats)
       limit=limit+(support['base_limit_+'] or 0)
      end
     end
    end
    metric(values,'bell_spawn_interval_seconds',interval)
    metric(values,'bell_spawn_rate_per_second',interval and interval>0 and 1/interval or nil)
    metric(values,'bell_active_limit',limit)
    metric(values,'bell_hits_to_destroy',base.bell_hit_limit)
    metric(values,'bell_duration_seconds',(base.base_secondary_skill_effect_duration or 0)/1000*calcLib.mod(active.skillModList,active.skillCfg,'Duration','SecondaryDuration'))
    local selected=active.activeEffect.statSet and active.activeEffect.statSet.statSet
    if selected==effect.statSets[2] then metric(values,'bell_shockwave_average_damage',cachedOutput(env,active).AverageDamage) end
    inputs={'bell_hit_events'}
    result[#result+1]=row('hollow_focus',id,values,inputs)
    issues[#issues+1]={code='missing_combat_assumption',skill_id=id}
   else
    local additional=base.mantra_of_illusions_bonus_illusions_when_consuming_power_charge or 0
    local benefit=1+active.skillModList:Sum('BASE',active.skillCfg,'Multiplier:ConsumedPowerChargeEffect')/100
    local expectedImages=1+additional*benefit
    local retention=math.min(100,math.max(0,active.skillModList:Sum('BASE',active.skillCfg,'ChargeNotRemovedChance','PowerChargeNotRemovedChance')))
    local cost=(base['mantra_of_illusions_cloned_skill_mana_cost_%'] or 0)/100
    metric(values,'hollow_form_images_without_charge',1)
    metric(values,'hollow_form_expected_images_with_charge',expectedImages)
    metric(values,'hollow_form_cost_multiplier_per_image',cost)
    metric(values,'hollow_form_charge_retention_chance',retention)
    metric(values,'hollow_form_expected_charges_removed_per_charged_use',1-retention/100)
    local copies={}
    for _,candidate in ipairs(env.player.activeSkillList or {}) do
     if candidate~=active and candidate.socketGroup==active.socketGroup
      and calcs.companionIsActiveSkill(env,candidate)
      and candidate.skillTypes[SkillType.SupportedByHollowForm] then copies[#copies+1]=candidate end
    end
    metric(values,'hollow_form_socketed_attack_count',#copies)
    local selectedCopy
    if configuration.hollow_form_attack_skill_id then
     for _,candidate in ipairs(copies) do
      if candidate.activeEffect.grantedEffect.id==configuration.hollow_form_attack_skill_id then
       if selectedCopy then selectedCopy=nil;break end
       selectedCopy=candidate
      end
     end
    elseif #copies==1 then selectedCopy=copies[1] end
    local copyOutput=selectedCopy and cachedOutput(env,selectedCopy)
    -- A missing per-skill cache is not a zero-cost, zero-damage image.
    if copyOutput and (type(copyOutput.AverageDamage)~='number' or type(copyOutput.ManaCost)~='number') then copyOutput=nil end
    inputs={'hollow_form_channel_events','charge_gain_events','charge_consumption_events'}
    if copyOutput then
     -- Keep the cost before integer rounding explicit. PoE2DB specifies 80%
     -- of the socketed cost; it does not document the final rounding order.
     metric(values,'hollow_form_unrounded_mana_cost_per_image',(copyOutput.ManaCost or 0)*cost)
     metric(values,'hollow_form_average_damage_per_image',copyOutput.AverageDamage)
    else inputs[#inputs+1]='hollow_form_socketed_skill' end
    local uses=configuration.hollow_form_channel_uses_per_second
    local fraction=configuration.hollow_form_power_charge_use_fraction
    local configured=copyOutput and type(uses)=='number' and uses>=0 and uses<=30
      and type(fraction)=='number' and fraction>=0 and fraction<=1
    if configured then
     local images=uses*(1+(expectedImages-1)*fraction)
     local projection={}
     metric(projection,'hollow_form_channel_uses_per_second',uses)
     metric(projection,'hollow_form_power_charge_use_fraction',fraction)
     metric(projection,'hollow_form_images_per_second',images)
     metric(projection,'hollow_form_expected_charges_removed_per_second',uses*fraction*(1-retention/100))
     metric(projection,'hollow_form_unrounded_mana_per_second',(copyOutput.ManaCost or 0)*cost*images)
     -- AverageDamage is a single supported image hit. Never multiply an
     -- existing DPS number by another attack rate, or assume extra overlaps.
     metric(projection,'hollow_form_image_hit_dps',(copyOutput.AverageDamage or 0)*images)
     result[#result+1]=row('hollow_form_simulation',selectedCopy.activeEffect.grantedEffect.id,projection,{},'calculated')
     inputs={}
    else
     issues[#issues+1]={code='missing_combat_assumption',skill_id=id}
    end
    result[#result+1]=row('hollow_form',id,values,inputs)
   end
  end
 end
 return result,issues
end
return M
