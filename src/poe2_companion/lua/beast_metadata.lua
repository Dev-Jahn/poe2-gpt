-- Canonical private supplement bound to immutable export bytes by the worker.
-- Coordinates are the result of a unique signature join, never Ninja positions.
local M = {}
function M.apply(build, metadata)
 if not metadata then return false end
 assert(metadata.schema_version==1 and metadata.species_verified==true)
 local prepared={}
 for _,row in ipairs(metadata.gems or {}) do
  local set=build.skillsTab.skillSets[row.skill_set_id]
  assert(set)
  local group=set.socketGroupList[row.skill_group]
  local gem=group and group.gemList[row.gem_index]
  assert(gem and gem.skillId==row.skill_id and row.skill_id=='SummonBeastPlayer')
  assert(gem.level==row.level and gem.quality==row.quality and gem.skillMinion==row.species_id)
  local entries={}
  for _,id in ipairs(row.mod_ids) do
   assert(build.data.tamedBeastMods[id])
   entries[#entries+1]={modId=id,enabled=true}
  end
  assert(#entries<=4)
  prepared[#prepared+1]={gem=gem,entries=entries,complete=row.complete==true,species=row.species_id}
 end
 -- Validate all identities before mutating even a temporary calculation.
 for _,entry in ipairs(prepared) do
  entry.gem.tamedBeastModList=entry.entries
  entry.gem.companionCapturedModsComplete=entry.complete
  -- Python already rejects conflicting explicit CALCS selectors in the
  -- immutable XML. Initial native calculation fills an absent selector with
  -- the first beast, so bind the temporary CALCS view to the verified species.
  entry.gem.skillMinionCalcs=entry.species
 end
 return #prepared>0
end
return M
