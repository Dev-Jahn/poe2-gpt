-- Canonical, bounded hit capabilities and explicitly selected buff snapshots.
-- Random stolen modifiers and acquisition uptime are never guessed.
local M = { }
local function array(t) return setmetatable(t or { }, { __jsontype = 'array' }) end
local function metric(name, value) return { name = name, value = value } end
local function row(name, status, metrics, inputs)
 local bounded = array()
 for _, value in ipairs(metrics or { }) do
  if type(value.value) == 'number' and value.value == value.value and math.abs(value.value) <= 1e15 then
   bounded[#bounded+1] = value
  end
 end
 return { mechanic = name, status = status, metrics = bounded, required_inputs = array(inputs) }
end
function M.register() end
function M.inspect(build, env, out)
 local rows, issues = array(), array()
 local missing = false
 local function assumption()
  if not missing then issues[#issues+1] = { code = 'missing_combat_assumption' }; missing = true end
 end
 local state = env.player.companionHitBuffs or { }
 local input = build.configTab.input
 local actor = env.minion or env.player
 local actorOut = (env.minion and out.Minion or out) or { }
 local active = actor.mainSkill
 local mods = active and active.skillModList
 local cannotBlind = mods and mods:Flag(active.skillCfg, 'CannotBlind')
 local maim, blind = actorOut.MaimChance or 0, actorOut.BlindChance or 0
 if maim > 0 or blind > 0 or cannotBlind or input.conditionEnemyMaimed or input.conditionEnemyBlinded then
  rows[#rows+1] = row('hit_effects', 'calculated', {
   metric('maim_chance_percent', maim), metric('blind_chance_percent', blind),
   metric('cannot_inflict_blind', cannotBlind and 1 or 0),
   metric('enemy_maimed', env.enemy.modDB:Flag(nil, 'Condition:Maimed') and 1 or 0),
   metric('enemy_blinded', env.enemy.modDB:Flag(nil, 'Condition:Blinded') and 1 or 0),
   metric('maim_base_duration_seconds', 4),
  })
 end
 if (state.thrillDamage or 0) > 0 then
  if input.companionThrillOfTheKillActive == nil then assumption() end
  rows[#rows+1] = row('thrill_of_the_kill', state.thrillActive and 'calculated' or (input.companionThrillOfTheKillActive == false and 'inactive' or 'requires_configuration'), {
   metric('thrill_added_lightning_attack_percent', state.thrillDamage),
   metric('thrill_shock_chance_increased_percent', state.thrillShock),
   metric('thrill_base_duration_seconds', state.thrillDuration),
   metric('thrill_buff_active', state.thrillActive and 1 or 0),
  }, input.companionThrillOfTheKillActive == nil and { 'thrill_of_the_kill_active' } or { })
 end
 if (state.cullIncrease or 0) > 0 then
  if input.companionCullingStrikeRecentCull == nil then assumption() end
  rows[#rows+1] = row('culling_strike_buff', state.cullActive and 'calculated' or (input.companionCullingStrikeRecentCull == false and 'inactive' or 'requires_configuration'), {
   metric('culling_threshold_increased_percent', state.cullIncrease),
   metric('culling_buff_base_duration_seconds', state.cullDuration),
   metric('culling_buff_active', state.cullActive and 1 or 0),
   metric('culling_threshold_percent', out.CullPercent or 0),
  }, input.companionCullingStrikeRecentCull == nil and { 'culling_strike_recent_cull' } or { })
 end
 if (state.beheadCount or 0) > 0 then
  assumption()
  rows[#rows+1] = row('behead', 'partial', {
   metric('behead_modifiers_per_rare_kill', state.beheadCount),
   metric('behead_base_duration_seconds', state.beheadDuration),
  }, { 'stolen_rare_modifiers' })
 end
 local sources = env.modDB:List(env.player.mainSkill and env.player.mainSkill.skillCfg, 'CompanionOnslaughtSource')
 local onslaught = env.modDB:Flag(nil, 'Onslaught')
 if #sources > 0 or onslaught or input.buffOnslaught ~= nil then
  if not onslaught and input.buffOnslaught == nil then assumption() end
  local chance, duration = 0, 0
  for _, source in ipairs(sources) do
   chance = math.max(chance, math.min(source.chance or 0, 100))
   duration = math.max(duration, source.duration or 0)
  end
  rows[#rows+1] = row('onslaught', onslaught and 'calculated' or (input.buffOnslaught == false and 'inactive' or 'requires_configuration'), {
   metric('onslaught_active', onslaught and 1 or 0),
   metric('onslaught_source_count', #sources),
   metric('onslaught_highest_source_chance_percent', chance),
   metric('onslaught_longest_source_base_duration_seconds', duration),
  }, not onslaught and input.buffOnslaught == nil and { 'onslaught_active' } or { })
 end
 return rows, issues
end
return M
