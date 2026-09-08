-- Bounded projections for Offering life and Companion composition.
-- No saved labels, raw gem/item text or guessed Azmeri uptime leave this module.
local M = { }
local calcs = require("Modules.CalcBase")
local function array(t) return setmetatable(t or { }, { __jsontype = 'array' }) end
local function metric(name, value) return { name = name, value = value } end
local function row(key, status, metrics, inputs)
 return { mechanic = key, status = status, metrics = array(metrics), required_inputs = array(inputs) }
end
function M.register() end -- All parser/calculator patches are installed at image build.
function M.inspect(build, env, out)
 local mechanics, issues = array(), array()
 local function issue(code) issues[#issues + 1] = { code = code } end
 local ids = { BoneOfferingPlayer = 'bone_offering_life', PainOfferingPlayer = 'pain_offering_life', SoulOfferingPlayer = 'soul_offering_life' }
 local offeringValues, offeringCounts = { }, { }
 for _, spike in ipairs(env.player.companionOfferingLifeList or { }) do
  local key = ids[spike.skill_id]
  if key then
   offeringCounts[key] = (offeringCounts[key] or 0) + 1
   -- Equal-type duplicate instances can have different supports/levels. Report
   -- their range, never silently select the higher-life version.
   offeringValues[key] = offeringValues[key] or { min = spike.life, max = spike.life }
   offeringValues[key].min = math.min(offeringValues[key].min, spike.life)
   offeringValues[key].max = math.max(offeringValues[key].max, spike.life)
  end
 end
 local offeringMetrics = { }
 for _, key in ipairs({ 'bone_offering_life', 'pain_offering_life', 'soul_offering_life' }) do
  local v = offeringValues[key]
  if v then
   offeringMetrics[#offeringMetrics + 1] = metric(key .. '_minimum', v.min)
   offeringMetrics[#offeringMetrics + 1] = metric(key .. '_maximum', v.max)
  end
 end
 if #offeringMetrics > 0 then mechanics[#mechanics + 1] = row('offering_life', 'calculated', offeringMetrics) end

 local vessels = env.player.companionSpiritVesselLifeList or { }
 if #vessels > 0 then
  local ranges, metrics = { }, { }
  for _, vessel in ipairs(vessels) do
   for _, pair in ipairs({ { 'spirit_vessel_life', vessel.life }, { 'spirit_vessel_socketed_skills', vessel.socketed_skill_count }, { 'spirit_vessel_damage_more', vessel.damage_more_percent } }) do
    local key, value = pair[1], pair[2]
    ranges[key] = ranges[key] or { min = value, max = value }
    ranges[key].min, ranges[key].max = math.min(ranges[key].min, value), math.max(ranges[key].max, value)
   end
  end
  for _, key in ipairs({ 'spirit_vessel_life', 'spirit_vessel_socketed_skills', 'spirit_vessel_damage_more' }) do
   metrics[#metrics + 1] = metric(key .. '_minimum', ranges[key].min)
   metrics[#metrics + 1] = metric(key .. '_maximum', ranges[key].max)
  end
  mechanics[#mechanics + 1] = row('spirit_vessel', 'partial', metrics)
  issue('unsupported_companion_mechanic')
 end
 local packMetrics = { }
 for _, pair in ipairs({ { 'wolf_pack_size', out.WolfLimit }, { 'hyena_pack_size', out.HyenaLimit } }) do
  if pair[2] and pair[2] > 0 then packMetrics[#packMetrics + 1] = metric(pair[1], pair[2]) end
 end
 if #packMetrics > 0 then mechanics[#mechanics + 1] = row('companion_pack_size', 'calculated', packMetrics) end

 local unlimited = env.modDB:Flag(nil, 'CompanionLimitUnlimited')
 local limit = env.modDB:Flag(nil, 'CompanionLimitTwo') and 2 or 1
 local active, exempt, unique, seenInstances, types = 0, 0, 0, { }, { }
 local unknown, violation, sawBeast, unverifiedBeasts = false, false, false, 0
 for _, skill in ipairs(env.player.activeSkillList or { }) do
  local effect = skill.activeEffect
  local flags = env.mode == 'CALCS' and effect.statSetCalcs.skillFlags or effect.statSet.skillFlags
  local instance = effect.srcInstance
  local count, enabled = calcs.getActiveSkillCount(skill)
  if skill.skillTypes[SkillType.CreatesCompanion] and calcs.companionIsActiveSkill(env, skill) and enabled and count > 0 and not seenInstances[instance] and not calcs.companionIsGrantMirror(env, skill) then
   seenInstances[instance] = true
   local id = effect.grantedEffect.id
   local identity = id
   if id == 'SummonBeastPlayer' then
    sawBeast = true
    identity = skill.minion and skill.minion.type
    if not identity or not build.data.minions[identity] then unknown = true
    elseif skill.minion.minionData.companionUnique then unique = unique + 1
    else unverifiedBeasts = unverifiedBeasts + 1 end
   end
   if id == 'WildProtectorPlayer' then
    exempt = exempt + 1
   else active = active + 1 end
   if identity then
    if types[identity] then issue('duplicate_companion_type'); violation = true end
    types[identity] = true
   end
  end
 end
 if unverifiedBeasts > 0 then
  mechanics[#mechanics + 1] = row('tamed_beast_modifiers', 'requires_configuration', { metric('unverified_tamed_beasts', unverifiedBeasts) }, { 'captured_beast_modifiers' })
  issue('missing_companion_data')
 end
 if not unlimited and active > limit then issue('companion_limit_exceeded'); violation = true end
 if unique > 1 then issue('unique_companion_limit_exceeded'); violation = true end
 if unique > 0 and not env.modDB:Flag(nil, 'CanCaptureUniqueBeasts') then issue('unique_companion_not_allowed'); violation = true end
 if unknown then issue('companion_identity_unverified') end
 if active + exempt > 0 or unlimited or limit == 2 then
  local metrics = { metric('active_companion_types', active), metric('exempt_companion_types', exempt), metric('unique_tamed_beasts', unique) }
  metrics[#metrics + 1] = unlimited and metric('unlimited_companion_types', 1) or metric('companion_limit', limit)
  mechanics[#mechanics + 1] = row('companion_composition', (unknown or violation) and 'partial' or 'calculated', metrics)
 end
 if env.modDB:Flag(nil, 'UniqueTamedBeastRandomAzmeriSpirits') then
  local status = unique > 0 and 'requires_configuration' or unknown and sawBeast and 'partial' or 'inactive'
  local metrics = { metric('unique_tamed_beasts', unique) }
  local inputs = { }
  if unique > 0 then
   metrics[#metrics + 1] = metric('unique_tamed_beast_movement_speed_increase', 30)
   inputs[1] = 'azmeri_spirit'
   issue('unsupported_companion_mechanic')
  elseif unknown and sawBeast then issue('companion_identity_unverified') end
  mechanics[#mechanics + 1] = row('natural_order', status, metrics, inputs)
 end
 local gold = env.modDB:Sum('INC', nil, 'GoldQuantity')
 if gold ~= 0 then mechanics[#mechanics + 1] = row('economy_effects', 'calculated', { metric('gold_quantity_increase', gold) }) end
 return mechanics, issues
end
return M
