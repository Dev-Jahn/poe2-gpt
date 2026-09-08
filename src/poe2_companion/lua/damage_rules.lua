-- Only bounded canonical numbers/labels leave the private engine worker.
local M = {}

local function metric(name, value)
  local number = tonumber(value)
  if not number or number ~= number or math.abs(number) > 1e15 then
    error("damage_rule_metric_unavailable")
  end
  return { name = name, value = number }
end

function M.inspect(build, env, output)
  local mechanics, issues = {}, {}
  local skill = env.player.mainSkill
  local id = skill and skill.activeEffect and skill.activeEffect.grantedEffect.id
  -- No current PoE2 skill uses the upstream combined-hand placeholder.
  -- Do not silently interpret a future merged hit as two independent hits.
  local flags = skill and skill.activeEffect.statSet and skill.activeEffect.statSet.skillFlags or {}
  if flags.bothWeaponAttack and skill.skillData.combinesHitsWhenDualWielding then
    return {
      { mechanic = "impale_extraction", skill_id = id, status = "unsupported", metrics = {} },
      { mechanic = "leech_recovery", skill_id = id, status = "unsupported", metrics = {} },
    }, { { code = "unsupported_weapon_context", skill_id = id } }
  end
  local storedHit = output.ImpaleStoredHitMagnitude or 0
  local storedCrit = output.ImpaleStoredCritMagnitude or 0
  if storedHit > 0 or storedCrit > 0 then
    mechanics[#mechanics + 1] = {
      mechanic = "impale_generation", skill_id = id, status = "calculated",
      metrics = {
        metric("impale_chance_percent", output.ImpaleChance),
        metric("impale_crit_chance_percent", output.ImpaleChanceOnCrit),
        metric("impale_hit_magnitude", storedHit),
        metric("impale_crit_magnitude", storedCrit),
        metric("impales_inflicted_per_hit", output.ImpaleInflicted),
        metric("impales_stored_cap", 60),
      },
    }
  end
  local explicit = tonumber(env.configInput.companionImpaleMagnitude)
  local extractedHit, extractedCrit = output.ImpaleExtractedOnHit or 0, output.ImpaleExtractedOnCrit or 0
  if explicit or storedHit > 0 or storedCrit > 0 then
    mechanics[#mechanics + 1] = {
      mechanic = "impale_extraction", skill_id = id,
      status = explicit and ((extractedHit > 0 or extractedCrit > 0) and "partial" or "inactive") or "requires_configuration",
      metrics = {
        metric("impale_extracted_hit_magnitude", extractedHit),
        metric("impale_extracted_crit_magnitude", extractedCrit),
      },
      required_inputs = explicit and { "impale_sustain" } or { "impale_magnitude" },
    }
    if not explicit or extractedHit > 0 or extractedCrit > 0 then
      issues[#issues + 1] = { code = "missing_combat_assumption", skill_id = id }
    end
  end
  local life, mana, es = output.LifeLeechPerHit or 0, output.ManaLeechPerHit or 0, output.EnergyShieldLeechPerHit or 0
  if life > 0 or mana > 0 or es > 0 then
    local required = { "leech_recovery_uptime" }
    local hitLeech = (output.LeechUsesHitDamage or 0) > 0
    if hitLeech and tonumber(env.configInput.companionLeechResistance) == nil then
      required[#required + 1] = "leech_resistance_percent"
    end
    local suffix = hitLeech and "_per_hit" or "_per_use"
    local metrics = {
      metric("life_leech" .. suffix, life),
      metric("mana_leech" .. suffix, mana),
      metric("energy_shield_leech" .. suffix, es),
      metric("life_leech_active_rate", output.MaxLifeLeechRate),
      metric("mana_leech_active_rate", output.MaxManaLeechRate),
      metric("energy_shield_leech_active_rate", output.MaxEnergyShieldLeechRate),
    }
    if hitLeech then
      metrics[#metrics + 1] = metric("leech_resistance_percent", output.EnemyLeechResistance)
      metrics[#metrics + 1] = metric("leech_total_hit_damage_cap", 40000)
    end
    mechanics[#mechanics + 1] = {
      mechanic = "leech_recovery", skill_id = id, status = "partial",
      metrics = metrics, required_inputs = required,
    }
    issues[#issues + 1] = { code = "missing_combat_assumption", skill_id = id }
  end
  return mechanics, issues
end

return M
