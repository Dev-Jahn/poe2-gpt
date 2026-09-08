-- Finite event projection over charge-count/expiry marginals.
-- No RNG, text payloads, character identifiers, or invented live event rates.
-- The declared roll model is a scenario assumption, not reverse-engineered
-- server RNG. Marginals suffice for the reported per-type expectations only.
local M = {}
local kinds = {'power','frenzy','endurance'}
local function array(t) return setmetatable(t or {},{__jsontype='array'}) end
local function finite(n,lo,hi) return type(n)=='number' and n==n and n>=lo and n<=hi end
local function probability(n) return math.max(0,math.min(n or 0,1)) end
local assumptions = {'independent_nonrecursive_bonus_rolls','uniform_random_charge_type',
 'retention_roll_per_skill_use','expiry_before_same_time_events','regulation_before_same_time_events',
 'gain_refreshes_duration_at_cap','static_build_modifiers','supplied_flicker_occupation_windows',
 'ally_results_are_grant_attempts','uncapped_potential_recoup'}
local function empty_result(s)
 return {scenario_scope='hypothetical_supplied_event_schedule',status='calculated',
  horizon_seconds=s.horizon_seconds,gain_roll_model=s.gain_roll_model,assumptions=array(assumptions),
  snapshot_dps_unchanged=true,charges=array(),ally_grants=array(),issues=array()}
end
local function issue(result,code)
 result.status='unsupported'
 for _,v in ipairs(result.issues) do if v==code then return end end
 if #result.issues<8 then result.issues[#result.issues+1]=code end
end
local function add_state(states,n,expiry,p)
 if p<=0 then return end
 if n==0 then expiry=0 end
 local byExpiry=states[n]
 if not byExpiry then byExpiry={};states[n]=byExpiry end
 byExpiry[expiry]=(byExpiry[expiry] or 0)+p
end
local function add_pmf(pmf,n,p) if p>0 then pmf[n]=(pmf[n] or 0)+p end end
local function bernoulli(pmf,p)
 local next={};p=probability(p)
 for n,v in pairs(pmf) do add_pmf(next,n,v*(1-p));add_pmf(next,n+1,v*p) end
 return next
end
local function convolve(a,b)
 local next={}
 for n,p in pairs(a) do for m,q in pairs(b) do add_pmf(next,n+m,p*q) end end
 return next
end
local function gain_pmf(base,same,random,rolls)
 -- One random extra chooses exactly one of three types. Its marginal chance
 -- for a specified type is p/3. We never infer joint all-charge probabilities.
 local single=bernoulli(bernoulli({[0]=1},same),random/3)
 local extra={[0]=1}
 for _=1,rolls do extra=convolve(extra,single) end
 local result={}
 for n,p in pairs(extra) do result[n+base]=p end
 return result
end
local function new_recoup(duration)
 return {potential_total=0,potential_by_horizon=0,potential_per_second_at_horizon=0,duration_seconds=duration}
end
local function add_recoup(result,hit,horizon,coefficient)
 local amount=hit.damage_taken*coefficient
 local elapsed=math.max(0,horizon-hit.at_seconds)
 result.potential_total=result.potential_total+amount
 result.potential_by_horizon=result.potential_by_horizon+amount*math.min(elapsed/result.duration_seconds,1)
 if elapsed<result.duration_seconds then result.potential_per_second_at_horizon=result.potential_per_second_at_horizon+amount/result.duration_seconds end
end

-- parameters contains only numeric/canonical source-derived values. Test code
-- can exercise this state machine independently of a full PoB startup.
function M.run(parameters,scenario)
 local result=empty_result(scenario)
 local horizon=scenario.horizon_seconds
 local events=scenario.events or {}
 if not finite(horizon,0.000001,120) or #events>64 or
  (scenario.gain_roll_model~='independent_nonrecursive_per_event' and scenario.gain_roll_model~='independent_nonrecursive_per_base_charge') then
  issue(result,'invalid_combat_event_schedule');return result
 end
 if parameters.unsupported then issue(result,parameters.unsupported);return result end
 local registry=parameters.skills or {}
 local last,occupied=-1,-1
 -- Validate the entire schedule before calculating. Rejected schedules must
 -- not return deceptively complete prefixes of an event projection.
 for _,event in ipairs(events) do
  if not finite(event.at_seconds,0,horizon) or event.at_seconds<last then issue(result,'invalid_combat_event_schedule');return result end
  last=event.at_seconds
  local skill=event.skill_group and registry[event.skill_group]
  if event.kind=='external_charge_gain' then
   if not parameters.charges[event.charge_type] or not finite(event.amount,1,20) or event.amount%1~=0 then issue(result,'invalid_combat_event_schedule');return result end
  elseif event.kind=='killing_palm_kill' then
   if not skill or skill.kind~='killing_palm' or not skill.gains[event.rarity] then issue(result,'invalid_scenario_skill');return result end
   if event.at_seconds<occupied then issue(result,'invalid_combat_event_schedule');return result end
  elseif event.kind=='enemy_immobilised' then
   if not parameters.mountain then issue(result,'unsupported_scenario_mechanic');return result end
   if not finite(event.enemy_power,0,100) then issue(result,'invalid_combat_event_schedule');return result end
  elseif event.kind=='mountain_attack_use' then
   if not parameters.mountain or not skill or not skill.mountain_attack then issue(result,'invalid_scenario_skill');return result end
   if event.at_seconds<occupied then issue(result,'invalid_combat_event_schedule');return result end
  elseif event.kind=='mountain_hit' then
   if not parameters.mountain then issue(result,'unsupported_scenario_mechanic');return result end
   if not finite(event.damage_after_mitigation,0,1e7) or not finite(event.other_damage_taken_multiplier,0,100) or type(event.deflected)~='boolean' then issue(result,'invalid_combat_event_schedule');return result end
  elseif event.kind=='armour_fully_broken' then
   if not skill or not finite(skill.armour_break_chance,0.000001,1) then issue(result,'invalid_scenario_skill');return result end
  elseif event.kind=='flicker_use' then
   if not skill or skill.kind~='flicker' then issue(result,'invalid_scenario_skill');return result end
   if not finite(event.duration_seconds,0.000001,30) or event.at_seconds<occupied or event.at_seconds+event.duration_seconds>horizon then issue(result,'invalid_combat_event_schedule');return result end
   occupied=event.at_seconds+event.duration_seconds
  elseif event.kind=='incoming_hit' then
   if not finite(event.damage_taken,0,1e7) or type(event.deflected)~='boolean' then issue(result,'invalid_combat_event_schedule');return result end
  elseif event.kind=='companion_redirected_hit' then
   if not skill or skill.kind~='companion' or not finite(skill.recoup,0.000001,100) then issue(result,'invalid_scenario_skill');return result end
   if not finite(event.damage_taken,0,1e7) then issue(result,'invalid_combat_event_schedule');return result end
  elseif event.kind=='ally_hit' then
   if type(event.allies_in_presence)~='boolean' then issue(result,'invalid_combat_event_schedule');return result end
  else issue(result,'invalid_combat_event_schedule');return result end
 end
 local regulation=parameters.regulation
 if regulation and not finite(scenario.regulation_first_tick_seconds,0,120) then issue(result,'missing_regulation_phase');return result end
 if regulation and not finite(regulation.interval,0.01,1e6) then issue(result,'unsupported_charge_configuration');return result end
 local recoupDuration=parameters.recoup_duration or 8
 if not finite(recoupDuration,0.000001,1e6) then issue(result,'unsupported_recoup_configuration');return result end
 local distributions, summaries={},{}
 for _,kind in ipairs(kinds) do
  local p=parameters.charges[kind]
  local initial=(scenario.initial_charges or {})[kind] or {count=0,remaining_seconds=0}
  if not p or not finite(p.maximum,0,20) or p.maximum%1~=0 or not finite(p.minimum or 0,0,p.maximum) or (p.minimum or 0)%1~=0 or not finite(p.duration,0.000001,1e6) then issue(result,'unsupported_charge_configuration');return result end
  if not finite(initial.count,0,p.maximum) or initial.count%1~=0 or initial.count<(p.minimum or 0) or (initial.count>0 and not finite(initial.remaining_seconds,0.000001,120)) then issue(result,'invalid_initial_charge_state');return result end
  distributions[kind]={}
  add_state(distributions[kind],initial.count,initial.remaining_seconds or 0,1)
  summaries[kind]={charge_type=kind,maximum=p.maximum,expected_final=0,probability_nonzero_at_end=0,
   expected_seconds_nonzero=0,expected_generated=0,expected_wasted_at_cap=0,expected_blocked=0,expected_removed=0,expected_expired=0}
 end
 local initialMountain=scenario.initial_mountain_teachings or {count=0,remaining_seconds=0}
 if initialMountain.count>0 and not parameters.mountain then issue(result,'unsupported_scenario_mechanic');return result end
 if parameters.mountain then
  local m=parameters.mountain
  if not finite(m.maximum,1,30) or m.maximum%1~=0 or not finite(m.maximum_life,1,1e9) or
   not finite(m.gain_chance,0,100) or not finite(m.duration,0.000001,20) or
   not finite(initialMountain.count,0,m.maximum) or initialMountain.count%1~=0 or
   (initialMountain.count>0 and not finite(initialMountain.remaining_seconds,0.000001,20)) then
   issue(result,'unsupported_scenario_mechanic');return result
  end
 end
 local operations=0
 local function budget(n)
  operations=operations+n
  if operations>2000000 then error('scenario_budget_exceeded',0) end
 end
 local function advance(kind,from,to)
  local next={};local row=summaries[kind];local minimum=parameters.charges[kind].minimum or 0
  for n,byExpiry in pairs(distributions[kind]) do for expiry,p in pairs(byExpiry) do
   budget(1)
   if n>0 then
    local activeUntil=minimum>0 and to or math.min(to,math.max(from,expiry))
    row.expected_seconds_nonzero=row.expected_seconds_nonzero+p*math.max(0,activeUntil-from)
   end
   if n>minimum and expiry<=to then row.expected_expired=row.expected_expired+(n-minimum)*p;add_state(next,minimum,0,p)
   else add_state(next,n,expiry,p) end
  end end
  distributions[kind]=next
 end
 local function gain(kind,pmf,time,blocked)
  local next={};local row=summaries[kind];local params=parameters.charges[kind]
  for amount,prob in pairs(pmf) do
   row.expected_generated=row.expected_generated+amount*prob
   if blocked then row.expected_blocked=row.expected_blocked+amount*prob end
  end
  if blocked then return end
  for n,byExpiry in pairs(distributions[kind]) do for expiry,p in pairs(byExpiry) do for amount,prob in pairs(pmf) do
   budget(1)
   local count=math.min(params.maximum,n+amount)
   row.expected_wasted_at_cap=row.expected_wasted_at_cap+(n+amount-count)*p*prob
   add_state(next,count,amount>0 and time+params.duration or expiry,p*prob)
  end end end
  distributions[kind]=next
 end
 local function consume(kind,amount,retain)
  local next={};local row=summaries[kind];local minimum=parameters.charges[kind].minimum or 0
  retain=probability(retain)
  local counted=0
  for n,byExpiry in pairs(distributions[kind]) do for expiry,p in pairs(byExpiry) do
   budget(1)
   local removed=math.min(math.max(0,n-minimum),amount)
   counted=counted+removed*p
   row.expected_removed=row.expected_removed+removed*p*(1-retain)
   add_state(next,n,expiry,p*retain);add_state(next,n-removed,expiry,p*(1-retain))
  end end
  distributions[kind]=next
  return counted
 end
 local function execute()
  local cursor=0
  local nextTick=regulation and scenario.regulation_first_tick_seconds or math.huge
  local blockedUntil=-1
  local flicker={uses=0,expected_charges_counted=0,expected_strikes=0,assumed_occupied_seconds=0}
  local grants={power=0,frenzy=0,endurance=0}
  local deflected,companion=new_recoup(recoupDuration),new_recoup(recoupDuration)
  local mountainStates={}
  add_state(mountainStates,initialMountain.count,initialMountain.remaining_seconds or 0,1)
  local mountain={expected_final=0,probability_active_at_end=0,expected_seconds_active=0,expected_generated=0,
   expected_wasted_at_cap=0,expected_removed=0,expected_expired=0,expected_damage_taken=0,
   expected_damage_prevented=0,expected_attacks_benefiting=0}
  local function mountain_advance(from,to)
   if not parameters.mountain then return end
   local next={}
   for n,byExpiry in pairs(mountainStates) do for expiry,p in pairs(byExpiry) do
    budget(1)
    if n>0 then mountain.expected_seconds_active=mountain.expected_seconds_active+p*math.max(0,math.min(to,expiry)-from) end
    if n>0 and expiry<=to then mountain.expected_expired=mountain.expected_expired+n*p;add_state(next,0,0,p)
    else add_state(next,n,expiry,p) end
   end end
   mountainStates=next
  end
  local function mountain_active()
   local active=0
   for n,byExpiry in pairs(mountainStates) do if n>0 then for _,p in pairs(byExpiry) do active=active+p end end end
   return probability(active)
  end
  local function mountain_gain(event)
   local chance=event.enemy_power*parameters.mountain.gain_chance
   local whole=math.floor(chance);local fraction=chance-whole
   local pmf=bernoulli({[whole]=1},fraction);local next={}
   mountain.expected_generated=mountain.expected_generated+chance
   for n,byExpiry in pairs(mountainStates) do for expiry,p in pairs(byExpiry) do for amount,q in pairs(pmf) do
    budget(1)
    local count=math.min(parameters.mountain.maximum,n+amount)
    mountain.expected_wasted_at_cap=mountain.expected_wasted_at_cap+(n+amount-count)*p*q
    add_state(next,count,amount>0 and event.at_seconds+parameters.mountain.duration or expiry,p*q)
   end end end
   mountainStates=next
  end
  local function mountain_spend(attack)
   if not parameters.mountain then return end
   local next={}
   for n,byExpiry in pairs(mountainStates) do for expiry,p in pairs(byExpiry) do
    budget(1)
    if n>0 then
     mountain.expected_removed=mountain.expected_removed+p
     if attack then mountain.expected_attacks_benefiting=mountain.expected_attacks_benefiting+p end
    end
    add_state(next,math.max(0,n-1),expiry,p)
   end end
   mountainStates=next
  end
  local function advance_all(time)
   for _,kind in ipairs(kinds) do advance(kind,cursor,time) end
   mountain_advance(cursor,time)
   cursor=time
  end
  local function tick_until(time)
   while nextTick<=time do
    budget(1)
    advance_all(nextTick)
    for _,kind in ipairs(kinds) do consume(kind,1,regulation.retention or 0) end
    nextTick=nextTick+regulation.interval
   end
   advance_all(time)
  end
  for _,event in ipairs(events) do
   tick_until(event.at_seconds)
   local skill=event.skill_group and registry[event.skill_group]
   if event.kind=='external_charge_gain' or event.kind=='killing_palm_kill' or event.kind=='armour_fully_broken' then
    local kind=event.kind=='external_charge_gain' and event.charge_type or event.kind=='armour_fully_broken' and 'endurance' or 'power'
    local amount=event.kind=='external_charge_gain' and event.amount or event.kind=='armour_fully_broken' and 1 or skill.gains[event.rarity]
    local trigger=event.kind=='armour_fully_broken' and skill.armour_break_chance or 1
    local function triggered(pmf)
     if trigger>=1 then return pmf end
     local result={[0]=1-trigger}
     for n,p in pairs(pmf) do add_pmf(result,n,p*trigger) end
     return result
    end
    local rolls=scenario.gain_roll_model=='independent_nonrecursive_per_base_charge' and amount or 1
    local globalChance=parameters.charges[kind].extra or 0
    local sameChance=skill and skill.extra or 0
    local randomChance=(skill and skill.random_extra or 0)+(parameters.random_extra or 0)
    -- Same-type chance modifiers add before a Bernoulli roll; the random
    -- extra-charge roll is independent under the declared scenario model.
    local pmf=gain_pmf(amount,probability(sameChance+globalChance),randomChance,rolls)
    gain(kind,triggered(pmf),event.at_seconds,kind=='power' and event.at_seconds<blockedUntil)
    if randomChance>0 then for _,other in ipairs(kinds) do if other~=kind then
     local extra=gain_pmf(0,0,randomChance,rolls)
     gain(other,triggered(extra),event.at_seconds,other=='power' and event.at_seconds<blockedUntil)
    end end end
   elseif event.kind=='flicker_use' then
    if skill.mountain_attack then mountain_spend(true) end
    flicker.uses=flicker.uses+1
    flicker.assumed_occupied_seconds=flicker.assumed_occupied_seconds+event.duration_seconds
    local expected,counted=0,0
    if not skill.cannot_consume then
     local minimum=parameters.charges.power.minimum or 0
     for n,byExpiry in pairs(distributions.power) do for _,p in pairs(byExpiry) do
      local available=math.max(0,n-minimum)
      local effective=available>0 and available+(skill.virtual_charges or 0) or 0
      counted=counted+effective*p
      expected=expected+effective*(skill.strikes_per_charge or 2)*(1+(skill.double_effect or 0))*p
     end end
     consume('power',20,skill.retention or 0)
    end
    flicker.expected_charges_counted=flicker.expected_charges_counted+counted
    flicker.expected_strikes=flicker.expected_strikes+1+expected
    if skill.power_gain_lockout then blockedUntil=event.at_seconds+event.duration_seconds end
   elseif event.kind=='ally_hit' and event.allies_in_presence then
    for _,kind in ipairs(kinds) do grants[kind]=grants[kind]+probability(parameters.charges[kind].ally_grant) end
   elseif event.kind=='incoming_hit' then
    mountain_spend(false)
    if event.deflected then add_recoup(deflected,event,horizon,parameters.deflected_recoup or 0) end
   elseif event.kind=='enemy_immobilised' then
    mountain_gain(event)
   elseif event.kind=='mountain_attack_use' then
    mountain_spend(true)
   elseif event.kind=='mountain_hit' then
    local baseline=event.damage_after_mitigation*event.other_damage_taken_multiplier
    local applies=event.damage_after_mitigation<=parameters.mountain.maximum_life*.3
    local prevented=applies and baseline*.4*mountain_active() or 0
    mountain.expected_damage_taken=mountain.expected_damage_taken+baseline-prevented
    mountain.expected_damage_prevented=mountain.expected_damage_prevented+prevented
    if event.deflected then add_recoup(deflected,{at_seconds=event.at_seconds,damage_taken=baseline-prevented},horizon,parameters.deflected_recoup or 0) end
    mountain_spend(false)
   elseif event.kind=='companion_redirected_hit' then
    add_recoup(companion,event,horizon,skill.recoup*(parameters.life_recovery or 1))
   end
  end
  tick_until(horizon)
  for _,kind in ipairs(kinds) do
   local row=summaries[kind]
   for n,byExpiry in pairs(distributions[kind]) do for _,p in pairs(byExpiry) do
    row.expected_final=row.expected_final+n*p
    if n>0 then row.probability_nonzero_at_end=row.probability_nonzero_at_end+p end
   end end
   row.probability_nonzero_at_end=probability(row.probability_nonzero_at_end)
   result.charges[#result.charges+1]=row
   result.ally_grants[#result.ally_grants+1]={charge_type=kind,expected_grants_per_eligible_ally=grants[kind]}
  end
  result.flicker=flicker;result.deflected_recoup=deflected;result.companion_recoup=companion
  if parameters.mountain then
   for n,byExpiry in pairs(mountainStates) do for _,p in pairs(byExpiry) do
    mountain.expected_final=mountain.expected_final+n*p
   end end
   mountain.probability_active_at_end=mountain_active()
   result.mountain_teachings=mountain
  end
 end
 local ok,err=pcall(execute)
 if not ok then
  result.charges=array();result.ally_grants=array();result.flicker=nil;result.deflected_recoup=nil;result.companion_recoup=nil;result.mountain_teachings=nil
  issue(result,err=='scenario_budget_exceeded' and err or 'unsupported_scenario_mechanic')
 end
 return result
end
return M
