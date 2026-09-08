"""Native curse eligibility, explicit Charged Mark ground, and Rite possession.

Sources: PoE2DB Temporal_Chains, Charged_Mark, Activating_Marks,
Rite_of_Passage and the nine Spirit_Of_The_* player keyword descriptions.
Reviewed upstream PR2443 head bfc0f554529ba980bd2c68833910f20ec57d95b1.
Its default-on possession settings and old Wolf coefficients are not adopted.
Periodic spirit attacks and Ox slowing potency remain explicitly partial.
"""
from pathlib import Path
import re


HELPERS = r'''
-- PoE2Companion: player possession values, distinct from haunted monsters.
local riteSpiritBonuses = {
 bear = {{"Life","INC",20},{"StunThreshold","INC",60},{"EnemyHeavyStunBuildup","INC",60},{"DamageTaken","INC",-20}},
 boar = {{"DamageGainAsFire","BASE",20},{"BleedChance","BASE",100},{"DamageTaken","INC",-20}},
 cat = {{"Evasion","INC",60},{"CritChance","INC",100},{"Speed","INC",30},{"MovementSpeed","INC",15}},
 owl = {{"EnergyShield","INC",60},{"Damage","INC",80},{"DamageGainAsCold","BASE",20}},
 ox = {{"Armour","INC",60},{"AilmentThreshold","INC",60},{"DamageTaken","INC",-20}},
 primate = {{"PhysicalCanChill","FLAG",true},{"FireCanChill","FLAG",true},{"LightningCanChill","FLAG",true},{"ChaosCanChill","FLAG",true},{"EnemyFreezeBuildup","INC",60},{"Damage","INC",80}},
 serpent = {{"FireCanPoison","FLAG",true},{"ColdCanPoison","FLAG",true},{"LightningCanPoison","FLAG",true},{"PoisonChance","BASE",100},{"Damage","INC",80}},
 stag = {{"ElementalResist","BASE",30},{"Speed","INC",30},{"MovementSpeed","INC",15},{"DamageGainAsLightning","BASE",20}},
 wolf = {{"Speed","INC",10},{"MovementSpeed","INC",5},{"ArmourBreakDamagePercent","BASE",10}},
}
function calcs.companionRiteAvailability(env)
 local result = { }
 local limit = m_min(3, env.modDB:Override(nil,"CharmLimit") or env.modDB:Sum("BASE",nil,"CharmLimit"))
 for index = 1, limit do
  local item = (env.companionEquippedCharms or { })["Charm " .. index]
  if item and item.type == "Charm" and item.title == "Rite of Passage" then
   for _, mod in ipairs(item.modList or { }) do
    if mod.name == "RiteOfPassagePossession" and type(mod.value) == "table" then
     local spirit, duration = mod.value.spirit, mod.value.duration
     if (riteSpiritBonuses[spirit] or spirit == "random") and type(duration) == "number" and duration > 0 then
      result[spirit] = m_max(result[spirit] or 0, duration)
     end
    end
   end
  end
 end
 return result
end
local function companionRitePossession(env)
 env.companionRitePossession = nil
 local spirit = env.configInput.companionRiteOfPassageSpirit
 local available = calcs.companionRiteAvailability(env)
 if not env.mode_combat or not riteSpiritBonuses[spirit] or not (available[spirit] or available.random) then return end
 for _, stat in ipairs(riteSpiritBonuses[spirit]) do
  env.modDB:NewMod(stat[1],stat[2],stat[3],"Rite of Passage:" .. spirit)
 end
 env.companionRitePossession = {spirit=spirit,duration=available[spirit] or available.random}
end

function calcs.companionChargedMarkSource(env, trigger)
 if trigger.activeEffect.grantedEffect.id ~= "TriggeredChargedMarkPlayer" then return nil end
 for _, skill in ipairs(env.player.activeSkillList) do
  if skill.socketGroup == trigger.socketGroup and skill.skillTypes[SkillType.Mark]
   and skill.skillData.chargedMarkTriggerOnActivation and calcs.companionIsActiveSkill(env,skill) then
   return skill
  end
 end
end
local function companionChargedMarkGround(env)
 env.companionChargedMarkGround = false
 if not env.mode_effective or env.configInput.companionChargedMarkGroundActive ~= true then return end
 for _, trigger in ipairs(env.player.activeSkillList) do
  local source = calcs.companionChargedMarkSource(env,trigger)
  if source and (trigger.skillData.chargedMarkTriggerChance or 0) > 0
   and not trigger.skillModList:Flag(trigger.skillCfg,"CannotShock") then
   local magnitude = data.nonDamagingAilment.Shock.default * calcLib.mod(trigger.skillModList,trigger.skillCfg,"EnemyShockMagnitude")
   env.modDB:NewMod("ShockOverride","BASE",magnitude,"Charged Mark")
   env.enemyDB:NewMod("Condition:Shocked","FLAG",true,"Charged Mark")
   env.enemyDB:NewMod("Condition:OnShockedGround","FLAG",true,"Charged Mark")
   env.companionChargedMarkGround = true
  end
 end
end

'''


def replace(path: Path, old: str, new: str) -> None:
    source = path.read_text()
    if new in source:
        return
    if source.count(old) != 1:
        raise SystemExit('curse_mechanics_patch_anchor_mismatch:' + path.name + ':' + str(source.count(old)))
    path.write_text(source.replace(old, new, 1))


def patch_curse_mechanics(destination: Path) -> None:
    setup = destination / 'src/Modules/CalcSetup.lua'
    replace(setup, '\t\tlocal items = {}\n\t\tlocal jewelLimits = {}',
            '\t\tenv.companionEquippedCharms = { }\n\t\tlocal items = {}\n\t\tlocal jewelLimits = {}')
    replace(setup, '\t\t\telseif item and item.type == "Charm" then\n\t\t\t\tif slot.active then',
            '\t\t\telseif item and item.type == "Charm" then\n\t\t\t\tenv.companionEquippedCharms[slotName] = item\n\t\t\t\tif slot.active then')
    maps = {
        'skill_curses_cannot_apply_to_targets_above_level': 'skill("curseTargetLevelLimit", nil)',
        'curse_apply_as_aura': 'skill("curseAppliesAsAura", true)',
        'number_of_marks_allowed_per_type': 'skill("markTargetsPerType", nil)',
        'support_trigger_shocked_ground_on_mark_activate': 'skill("chargedMarkTriggerOnActivation", true)',
        # Charged Mark creates ground; added spell damage cannot invent a hit.
        'chance_to_trigger_shocked_ground_on_mark_activated_%': 'skill("chargedMarkTriggerChance", nil), flag("DealNoDamage")',
    }
    path = destination / 'src/Data/SkillStatMap.lua'
    anchor = '["base_skill_effect_duration"] = {'
    addition = ''.join(f'\t["{key}"] = {{ {value} }},\n' for key, value in maps.items())
    replace(path, anchor, addition + anchor)
    perform = destination / 'src/Modules/CalcPerform.lua'
    replace(perform, 'function calcs.perform(env, skipEHP)', HELPERS + 'function calcs.perform(env, skipEHP)')
    anchor = '\t-- Calculate attributes\n\tdoActorAttribsConditions(env, env.player)'
    replace(perform, anchor, '\tcompanionRitePossession(env)\n\tcompanionChargedMarkGround(env)\n\n' + anchor)
    old = '\t\t\t\tif env.mode_effective and (not enemyDB:Flag(nil, "Hexproof") or modDB:Flag(nil, "CursesIgnoreHexproof") or activeSkill.skillData.ignoreCurseLimit or activeSkill.skillData.ignoreHexproof) or mark then'
    new = '\t\t\t\tlocal levelLimit = activeSkill.skillData.curseTargetLevelLimit or 0\n\t\t\t\tlocal targetAllowed = levelLimit <= 0 or env.enemyLevel <= levelLimit\n\t\t\t\tif targetAllowed and (env.mode_effective and (not enemyDB:Flag(nil, "Hexproof") or modDB:Flag(nil, "CursesIgnoreHexproof") or activeSkill.skillData.ignoreCurseLimit or activeSkill.skillData.ignoreHexproof) or mark) then'
    replace(perform, old, new)
    # Keep the selected source instance private so duplicate gems cannot claim
    # that a different level's successfully applied curse was their own.
    old = '\t\t\t\t\t\tpriority = determineCursePriority(buff.name, activeSkill),'
    replace(perform, old, old + '\n\t\t\t\t\t\tsourceInstance = activeSkill.activeEffect.srcInstance,')
    # Aura type is already conferred by the hidden Blasphemy support. Consume
    # the generated alias for curse effect too, without applying AuraEffect twice.
    old = '\t\t\t\t\tif activeSkill.skillTypes[SkillType.Aura] then\n\t\t\t\t\t\tinc = inc + skillModList:Sum("INC", skillCfg, "AuraEffect")'
    new = old.replace('activeSkill.skillTypes[SkillType.Aura] then', '(activeSkill.skillTypes[SkillType.Aura] or activeSkill.skillData.curseAppliesAsAura) then')
    replace(perform, old, new)
    parser = destination / 'src/Modules/ModParser.lua'
    anchor = '\t["unique tamed beasts are possessed by random azmeri spirits, changing every 20 seconds"]'
    source = parser.read_text()
    if 'PoE2Companion: Rite possession availability' not in source:
        lines = '\t-- PoE2Companion: Rite possession availability; effects require explicit state.\n'
        for spirit in ('bear', 'boar', 'cat', 'owl', 'ox', 'primate', 'serpent', 'stag', 'wolf'):
            lines += f'\t["possessed by spirit of the {spirit} for (%d+) seconds on use"] = function(num) return {{ mod("RiteOfPassagePossession", "LIST", {{spirit="{spirit}", duration=num}}) }} end,\n'
        lines += '\t["possessed by a random spirit for (%d+) seconds on use"] = function(num) return { mod("RiteOfPassagePossession", "LIST", {spirit="random", duration=num}) } end,\n'
        replace(parser, anchor, lines + anchor)
    cache = destination / 'src/Data/ModCache.lua'
    source = cache.read_text()
    cache.write_text(re.sub(r'^c\["[^"\n]*[Pp]ossessed by (?:[Ss]pirit [Oo]f [Tt]he|a random [Ss]pirit)[^\n]*\n', '', source, flags=re.M))


if __name__ == '__main__':
    import sys
    patch_curse_mechanics(Path(sys.argv[1]))
