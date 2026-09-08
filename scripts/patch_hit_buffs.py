"""Explicit hit/kill-buff snapshots; random acquisition never implies uptime.

PoE2DB: /us/{Behead_II,Blindside,Culling_Strike_II,Thrill_of_the_Kill_II,
Onslaught,Maim}. Reviewed upstream PR2510 2b38244b6b3b9497e16a466a759d695dc6537a2e
and PR2499 3e9aa40b3188dd7cd4f6f746d259e5667e64e02f. In particular we do
not adopt PR2510's chance-on-kill => unconditional KilledRecently Onslaught.
"""
from pathlib import Path


def replace(path, old, new):
    source = path.read_text()
    if new in source:
        return
    if source.count(old) != 1:
        raise SystemExit('hit_buffs_patch_anchor_mismatch')
    path.write_text(source.replace(old, new, 1))


STAT_MAP = r'''
-- PoE2Companion: keep acquisition metadata separate from active buffs.
["maim_on_hit_%"] = { mod("MaimChance", "BASE", nil) },
["global_maim_on_hit"] = { mod("MaimChance", "BASE", nil), value = 100 },
["cannot_inflict_blind"] = { flag("CannotBlind") },
["support_executioner_gain_one_rare_monster_mod_on_kill_ms"] = {
 { skill("companionBeheadDuration", nil), div = 1000 }, { skill("companionBeheadCount", nil), value = 1 },
},
["support_executioner_gain_two_rare_monster_mod_on_kill_ms"] = {
 { skill("companionBeheadDuration", nil), div = 1000 }, { skill("companionBeheadCount", nil), value = 2 },
},
["support_culling_strike_threshold_+%_on_cull_for_seconds_from_code"] = {
 skill("companionCullingBuffThreshold", nil), { skill("companionCullingBuffDuration", nil), value = 20 },
},
["support_thrill_of_the_kill_buff_grant_%_added_lightning_attack_damage"] = {
 skill("companionThrillLightning", nil),
},
["support_thrill_of_the_kill_buff_base_duration_ms"] = {
 skill("companionThrillDuration", nil), div = 1000,
},
["support_thrill_of_the_kill_buff_shock_chance_+%"] = {
 skill("companionThrillShockChance", nil),
},
'''


HELPERS = r'''
-- Global player buffs require a compatible enabled source, including sources
-- in non-main groups. Native support compatibility has already been applied.
function calcs.companionApplyHitBuffs(env)
 local state = { thrillDamage = 0, thrillShock = 0, thrillDuration = 0,
  cullIncrease = 0, cullDuration = 0, beheadCount = 0, beheadDuration = 0 }
 env.player.companionHitBuffs = state
 for _, active in ipairs(env.player.activeSkillList) do
  if calcs.companionIsActiveSkill(env, active) then
   local beheadSkills = active.minion and active.minion.activeSkillList or { active }
   for _, source in ipairs(beheadSkills or { }) do
    state.beheadCount = math.max(state.beheadCount, source.skillData.companionBeheadCount or 0)
    state.beheadDuration = math.max(state.beheadDuration, source.skillData.companionBeheadDuration or 0)
   end
  end
  if calcs.companionIsActiveSkill(env, active) and not active.minion then
   local s = active.skillData
   state.thrillDamage = math.max(state.thrillDamage, s.companionThrillLightning or 0)
   state.thrillShock = math.max(state.thrillShock, s.companionThrillShockChance or 0)
   state.thrillDuration = math.max(state.thrillDuration, s.companionThrillDuration or 0)
   state.cullIncrease = math.max(state.cullIncrease, s.companionCullingBuffThreshold or 0)
   state.cullDuration = math.max(state.cullDuration, s.companionCullingBuffDuration or 0)
  end
 end
 local input = env.build.configTab.input
 state.thrillActive = env.mode_buffs and input.companionThrillOfTheKillActive == true and state.thrillDamage > 0
 state.cullActive = env.mode_buffs and input.companionCullingStrikeRecentCull == true and state.cullIncrease > 0
 if state.thrillActive then
  local effect = calcLib.mod(env.modDB, nil, "BuffEffectOnSelf")
  env.modDB:NewMod("DamageGainAsLightning", "BASE", state.thrillDamage * effect, "Thrill of the Kill", ModFlag.Attack)
  env.modDB:NewMod("EnemyShockChance", "INC", state.thrillShock * effect, "Thrill of the Kill")
 end
 if state.cullActive then
  local effect = calcLib.mod(env.modDB, nil, "BuffEffectOnSelf")
  env.modDB:NewMod("CullPercent", "INC", state.cullIncrease * effect, "Culling Strike II")
 end
end
'''


PARSER = r'''
 -- PoE2Companion: exact source chance/duration, never automatic uptime.
 ["(%d+)%% chance to gain onslaught on killing hits with this weapon"] = function(num)
  return { mod("CompanionOnslaughtSource", "LIST", { chance = tonumber(num), duration = 4, weapon = true }) }
 end,
 ["you gain onslaught for (%d+) seconds on kill"] = function(num)
  return { mod("CompanionOnslaughtSource", "LIST", { chance = 100, duration = tonumber(num) }) }
 end,
 ["gain onslaught for (%d+) seconds on kill"] = function(num)
  return { mod("CompanionOnslaughtSource", "LIST", { chance = 100, duration = tonumber(num) }) }
 end,
 ["(%d+)%% chance to gain onslaught for (%d+) seconds on kill"] = function(chance, duration)
  return { mod("CompanionOnslaughtSource", "LIST", { chance = tonumber(chance), duration = tonumber(duration) }) }
 end,
 ["(%d+)%% chance to maim on hit"] = function(num) return { mod("MaimChance", "BASE", num) } end,
 ["maim on hit"] = { mod("MaimChance", "BASE", 100) },
 ["cannot inflict blind"] = { flag("CannotBlind") },
'''


def patch_hit_buffs(destination: Path) -> None:
    stats = destination / 'src/Data/SkillStatMap.lua'
    replace(stats, 'return {\n', 'return {\n' + STAT_MAP)
    perform = destination / 'src/Modules/CalcPerform.lua'
    anchor = '-- Finalises the environment and performs the stat calculations:'
    replace(perform, anchor, HELPERS + '\n' + anchor)
    anchor = '\t-- Process misc buffs/modifiers\n'
    replace(perform, anchor, '\tcalcs.companionApplyHitBuffs(env)\n' + anchor)
    parser = destination / 'src/Modules/ModParser.lua'
    anchor = '\t["onslaught"] = { flag("Condition:Onslaught") },'
    replace(parser, anchor, PARSER + '\n' + anchor)
    cache = destination / 'src/Data/ModCache.lua'
    lines = cache.read_text().splitlines(keepends=True)
    affected = ('onslaught', 'maim on hit', 'cannot inflict blind')
    cache.write_text(''.join(line for line in lines if not (line.startswith('c[') and any(key in line.lower() for key in affected))))
    options = destination / 'src/Modules/ConfigOptions.lua'
    anchor = '\t{ var = "buffOnslaught",'
    declarations = '\t{ var = "companionThrillOfTheKillActive", type = "check", label = "Thrill of the Kill buff active?", apply = function() end },\n\t{ var = "companionCullingStrikeRecentCull", type = "check", label = "Culling Strike II buff active?", apply = function() end },\n'
    replace(options, anchor, declarations + anchor)
    # Native state already supplies 20% skill speed and 10% movement speed.
    source = options.read_text()
    source = source.replace('(Grants 20% increased Attack, Cast, and Movement Speed)', '(Grants 20% increased Skill Speed and 10% increased Movement Speed)')
    options.write_text(source)
    offence = destination / 'src/Modules/CalcOffence.lua'
    anchor = '\t\toutput.ScaledDamageEffect = 1\n'
    chance = '''\t\t-- Hit chances describe capability, never assume an enemy debuff is active.
\t\toutput.MaimChance = m_min(100, m_max(0, skillModList:Sum("BASE", cfg, "MaimChance") * calcLib.mod(skillModList, cfg, "MaimChance")))
\t\toutput.BlindChance = skillModList:Flag(cfg, "CannotBlind") and 0 or m_min(100, m_max(0, skillModList:Sum("BASE", cfg, "BlindChance") * calcLib.mod(skillModList, cfg, "BlindChance")))
'''
    replace(offence, anchor, chance + anchor)
    anchor = '\t\tcombineStat("ShockChance", "AVERAGE")\n'
    replace(offence, anchor, '\t\tcombineStat("MaimChance", "AVERAGE")\n\t\tcombineStat("BlindChance", "AVERAGE")\n' + anchor)
