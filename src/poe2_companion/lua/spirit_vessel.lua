-- Spirit Vessel projections are per selected copied attack, not an AI rotation.
-- Only canonical pinned skill IDs and bounded numeric actor outputs leave Lua.
local M = { }
local calcs = require('Modules.CalcBase')
local function array(t) return setmetatable(t or { }, { __jsontype = 'array' }) end
local function metrics(output, mapping)
 local values = array()
 for _, pair in ipairs(mapping) do
  local value = output[pair[2]]
  if type(value) == 'number' and value == value and math.abs(value) < 1e15 then
   values[#values + 1] = { name = pair[1], value = value }
  end
 end
 return values
end

-- Select only a copied skill already present in each active Vessel. The caller
-- must clear PoB's caches and refresh after success. No skill text is accepted.
function M.configure(build, skill_id)
 local env, changes = build.calcsTab.mainEnv, { }
 if not build.data.skills[skill_id] then return false end
 for _, owner in ipairs(env.player.activeSkillList or { }) do
  if owner.activeEffect.grantedEffect.id == 'SpiritVesselPlayer'
    and calcs.companionIsActiveSkill(env, owner) and not calcs.companionIsGrantMirror(env, owner) then
   local found
   for index, skill in ipairs(owner.minion and owner.minion.activeSkillList or { }) do
    if skill.companionCopiedSkill and skill.activeEffect.grantedEffect.id == skill_id then found = index; break end
   end
   if not found then return false end
   changes[#changes + 1] = { source = owner.activeEffect.srcInstance, index = found }
  end
 end
 if #changes == 0 then return false end
 for _, change in ipairs(changes) do
  change.source.skillMinionSkill = change.index
  change.source.skillMinionSkillCalcs = change.index
 end
 return true
end

function M.inspect(build, env)
 local results, issues, seen = array(), array(), { }
 for _, owner in ipairs(env.player.activeSkillList or { }) do
  if owner.activeEffect.grantedEffect.id == 'SpiritVesselPlayer' and owner.minion
    and calcs.companionIsActiveSkill(env, owner) and not calcs.companionIsGrantMirror(env, owner)
    and not seen[owner.activeEffect.srcInstance] then
   seen[owner.activeEffect.srcInstance] = true
   local selected = env
   if owner ~= env.player.mainSkill then
    local cached = GlobalCache.cachedData[env.mode] and GlobalCache.cachedData[env.mode][cacheSkillUUID(owner, env)]
    selected = cached and cached.Env
   end
   local actor = selected and selected.minion
   local skill = actor and actor.mainSkill
   local id = skill and skill.activeEffect.grantedEffect.id
   if actor and actor.type == 'Metadata/Monsters/Companions/SpiritVessel' and skill and skill.companionCopiedSkill
     and id and build.data.skills[id] == skill.activeEffect.grantedEffect then
    local output = actor.output or { }
    results[#results + 1] = { mechanic = 'spirit_vessel_copied_attack', status = 'partial', skill_id = id,
     metrics = metrics(output, {
      { 'copied_skill_average_hit', 'AverageDamage' }, { 'copied_skill_nominal_dps', 'TotalDPS' },
      { 'copied_skill_uses_per_second', 'Speed' }, { 'copied_skill_critical_chance', 'CritChance' },
      { 'copied_skill_hit_chance', 'HitChance' },
     }), required_inputs = array({ 'companion_skill_rotation' }) }
    results[#results + 1] = { mechanic = 'spirit_vessel_defences', status = 'calculated', skill_id = 'SpiritVesselPlayer',
     metrics = metrics(output, {
      { 'spirit_vessel_life', 'Life' }, { 'spirit_vessel_armour', 'Armour' },
      { 'spirit_vessel_evasion', 'Evasion' }, { 'spirit_vessel_energy_shield', 'EnergyShield' },
      { 'spirit_vessel_fire_resist', 'FireResist' }, { 'spirit_vessel_cold_resist', 'ColdResist' },
      { 'spirit_vessel_lightning_resist', 'LightningResist' }, { 'spirit_vessel_chaos_resist', 'ChaosResist' },
     }), required_inputs = array() }
   end
  end
 end
 return results, issues
end

return M
