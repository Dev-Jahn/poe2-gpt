-- Explicit ally-aura snapshots. No raw imported beast labels are projected.
local M = {}
local calcs = require('Modules.CalcBase')
local function array(t) return setmetatable(t or {}, {__jsontype = 'array'}) end
local function metric(name, value) return {name = name, value = value} end
function M.register() end
function M.apply_configuration(build, configuration)
 if not configuration or configuration.companion_aura_sources == nil then return false end
 local planned = {}
 for _, state in ipairs(configuration.companion_aura_sources) do
  local group = assert(build.skillsTab.socketGroupList[state.skill_group], 'beast_aura_source_invalid')
  local count = 0
  for _, gem in ipairs(group.gemList) do
   local effect = gem.gemData and gem.gemData.grantedEffect
   if gem.enabled ~= false and (gem.skillId == 'SummonBeastPlayer' or effect and effect.id == 'SummonBeastPlayer') then count = count + 1 end
  end
  assert(count == 1 and group.enabled ~= false, 'beast_aura_source_invalid')
  for _, recipient in ipairs(state.minion_recipients) do
   assert(build.skillsTab.socketGroupList[recipient.skill_group], 'beast_aura_recipient_invalid')
  end
  planned[#planned + 1] = state
 end
 build.companionAuraConfiguration = planned
 return true
end
function M.inspect(build, env, out)
 local mechanics, issues = array(), array()
 local sources = calcs.companionAuraSources(env)
 local configured, alive, unresolved = 0, 0, 0
 local stateByGroup = {}
 for _, state in ipairs(build.companionAuraConfiguration or {}) do stateByGroup[state.skill_group] = state end
 local minionGroups = {}
 for _, skill in ipairs(env.player.activeSkillList) do
  local count, enabled = calcs.getActiveSkillCount(skill)
  if skill.minion and enabled and count > 0 and calcs.companionIsActiveSkill(env, skill) and not calcs.companionIsGrantMirror(env, skill) then
   local group = calcs.companionAuraGroup(env, skill)
   if group then minionGroups[group] = true end
  end
 end
 for _, source in ipairs(sources) do
  local state = stateByGroup[source.group]
  if state then
   configured = configured + 1
   if state.source_alive then alive = alive + 1 end
   stateByGroup[source.group] = nil
   local recipients = {}
   for _, recipient in ipairs(state.minion_recipients) do
    recipients[recipient.skill_group] = true
    if not minionGroups[recipient.skill_group] then unresolved = unresolved + 1 end
   end
   if state.source_alive then
    for group in pairs(minionGroups) do
     if group ~= source.group and not recipients[group] then unresolved = unresolved + 1 end
    end
   end
  else unresolved = unresolved + 1 end
 end
 for _ in pairs(stateByGroup) do unresolved = unresolved + 1 end
 if #sources > 0 or configured > 0 or unresolved > 0 then
  local function sum(bucket, stat, flags)
   local value = 0
   for name, list in pairs(bucket or {}) do
    if name:match('^Captured Beast Aura:') then value = value + list:Sum('INC', flags and {flags=flags} or nil, stat) end
   end
   return value
  end
  mechanics[#mechanics + 1] = {mechanic='companion_ally_auras', status=unresolved > 0 and 'partial' or 'calculated',
   metrics=array({metric('companion_aura_sources', #sources), metric('companion_aura_sources_configured', configured),
    metric('companion_aura_sources_alive', alive), metric('companion_aura_radius_metres', 5),
    metric('player_beast_aura_physical_damage_increase', sum(env.buffs,'PhysicalDamage')),
    metric('player_beast_aura_attack_speed_increase', sum(env.buffs,'Speed',ModFlag.Attack)),
    metric('minion_beast_aura_physical_damage_increase', sum(env.minionBuffs,'PhysicalDamage')),
    metric('minion_beast_aura_attack_speed_increase', sum(env.minionBuffs,'Speed',ModFlag.Attack))}),
   required_inputs=array(unresolved > 0 and {'companion_aura_sources'} or {})}
  if unresolved > 0 then issues[#issues + 1] = {code='missing_combat_assumption'} end
 end
 if out.Minion and (out.Minion.CompanionChillMinimum or 0) > 0 then
  mechanics[#mechanics + 1] = {mechanic='companion_chill', status='partial', metrics=array({
   metric('companion_chill_minimum_percent', out.Minion.CompanionChillMinimum),
   metric('companion_chill_hit_candidate_percent', out.Minion.CompanionChillHitCandidate or 0),
   metric('companion_chill_crit_candidate_percent', out.Minion.CompanionChillCritCandidate or 0)}), required_inputs=array()}
  issues[#issues + 1] = {code='unsupported_companion_mechanic'}
 end
 return mechanics, issues
end
return M
