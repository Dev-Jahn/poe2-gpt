-- Diagnose game-visible skill stats that the pinned engine cannot calculate.
-- Only canonical identifiers leave this module; descriptions stay private.
-- This follows GemTooltip's unsupported-stat criterion, using the effective
-- selected stat set and compatible supports rather than saved gem labels.
local coverage = {}
local calcs = require('Modules.CalcBase')
local presentationOnly = {
 -- Tame Beast's category-overlay visibility changes UI only. Its captured
 -- modifier-count limit is deliberately not ignored.
 skill_can_see_monster_categories = true,
}

function coverage.inspect(build)
 local env = build.calcsTab.mainEnv
 local issues, seen, visited = {}, {}, {}
 local function inspectSet(instance, effect, statSet, extraStats)
  if not statSet or not statSet.statDescriptionScope then return end
  local stats = calcLib.buildSkillInstanceStats(instance, effect, statSet, env.useAltGemQualityStats)
  local declared = {}
  for _, stat in ipairs(statSet.stats or {}) do declared[stat] = true end
  for _, stat in ipairs(statSet.constantStats or {}) do declared[stat[1]] = true end
  local setIndex
  for index, set in ipairs(effect.statSets or {}) do if set==statSet then setIndex=index-1 end end
  local function qualityStats(list)
   for _, stat in ipairs(list or {}) do
    local targets=stat[3]
    if not targets or #targets==0 then declared[stat[1]]=true
    else for _, index in ipairs(targets) do if index==setIndex then declared[stat[1]]=true end end end
   end
  end
  qualityStats(effect.qualityStats)
  if env.useAltGemQualityStats then qualityStats(effect.altQualityStats) end
  for _, extra in ipairs(extraStats or {}) do
   -- ExtraSkillStat is internal engine data; an arbitrary custom stat must
   -- never become a public diagnostic identifier.
   if stats[extra.key] ~= nil then stats[extra.key] = stats[extra.key] + extra.value end
  end
  -- describeStats omits ignored/hidden metadata. Resolve one missing stat at
  -- a time: a combined description's lineMap otherwise names only its last
  -- stat, potentially hiding the unsupported member of a multi-stat line.
  for stat, value in pairs(stats) do
   if declared[stat] and value ~= 0 and not presentationOnly[stat] and not statSet.statMap[stat] and not build.data.skillStatMap[stat] then
    local descriptions = build.data.describeStats({[stat] = value}, statSet.statDescriptionScope)
    if #descriptions > 0 then
     local key = effect.id .. '/' .. stat
     if not seen[key] then
      seen[key] = true
      issues[#issues + 1] = {code='unsupported_skill_stat', skill_id=effect.id, skill_stat_id=stat}
     end
    end
   end
  end
 end
 local function inspectInstance(instance, selectedSet, extraStats)
  local effect = instance and instance.grantedEffect
  if not effect or build.data.skills[effect.id] ~= effect then return end
  local source=instance.srcInstance
  local sourceKey='GrantedSource/'..effect.id
  if source and source.companionGrantLevelUnresolved and (effect.fromItem or effect.fromTree) and not seen[sourceKey] then
   seen[sourceKey]=true
   issues[#issues+1]={code='granted_skill_source_unresolved',skill_id=effect.id}
  end
  if effect.id=='SupportVerglasPlayer' and env.configInput.conditionDestroyedIceCrystalPast6Seconds
    and (env.player.destroyedIceCrystalLife or 0)<=0 and not seen['VerglasAssumption'] then
   seen['VerglasAssumption']=true
   issues[#issues+1]={code='missing_combat_assumption', skill_id=effect.id,
    skill_stat_id='support_crystalshatter_buff_damage_%_gained_as_extra_cold_per_2000_crystal_life'}
  end
  if selectedSet then
   inspectSet(instance, effect, selectedSet, extraStats)
  else
   -- All support stat sets are actually merged by mergeSkillInstanceMods.
   for _, statSet in ipairs(effect.statSets or {}) do inspectSet(instance, effect, statSet) end
  end
 end
 local inspectActor
 inspectActor = function(actor)
  if not actor or visited[actor] then return end
  visited[actor] = true
  for _, skill in ipairs(actor.activeSkillList or {}) do
   if calcs.companionIsActiveSkill(env,skill) then
    local instance = skill.activeEffect
    local selected = instance and (env.mode=='CALCS' and instance.statSetCalcs or instance.statSet)
    if selected then
     inspectInstance(instance, selected.statSet, skill.skillModList and skill.skillModList:List(skill.skillCfg, 'ExtraSkillStat'))
    end
    for _, effect in ipairs(skill.effectList or {}) do
     if effect.grantedEffect and effect.grantedEffect.support then inspectInstance(effect) end
    end
    inspectActor(skill.minion)
   end
  end
 end
 inspectActor(env.player)
 inspectActor(env.minion)
 table.sort(issues, function(a,b)
  if a.skill_id~=b.skill_id then return a.skill_id<b.skill_id end
  if a.code~=b.code then return a.code<b.code end
  return (a.skill_stat_id or '')<(b.skill_stat_id or '')
 end)
 return issues
end

return coverage
