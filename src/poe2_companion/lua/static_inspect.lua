-- No combat calculations, even for cold inspection. Private source never exits.
print=function() end
local json=require('dkjson')
local job=assert(json.decode(io.stdin:read('*a')))
dofile('HeadlessWrapper.lua')
local root=assert(arg[0]:match('^(.*[/\\])'))
dofile(root..'stonefist.lua').register()
dofile(root..'companions.lua').register()
dofile(root..'static_load.lua').load(job.xml)
local project=dofile(root..'inspection.lua').project
local function array(t) return setmetatable(t or {},{__jsontype='array'}) end
local query=job.inspection
if query and query.section=='configuration' and query.set_id then
 assert(build.configTab.configSets[query.set_id])
 build.configTab:SetActiveConfigSet(query.set_id)
end
local aliases={ghost_shroud_lost_recently='conditionLostGhostShroudRecently',
 refutation_active='conditionRefutationActive',refutation_ward_spent='refutationWardSpent',
 tempest_bell_prior_hits='tempestBellPriorHits',tempest_bell_knockback_metres='tempestBellKnockbackMetres',
 enemy_maimed='conditionEnemyMaimed',enemy_blinded='conditionEnemyBlinded',
 wind_dancer_stages='windDancerStacks',impale_magnitude='companionImpaleMagnitude',
 leech_resistance_percent='companionLeechResistance',onslaught_active='buffOnslaught',
 thrill_of_the_kill_active='companionThrillOfTheKillActive',culling_strike_recent_cull='companionCullingStrikeRecentCull'}
local saved={};for k,v in pairs(build.configTab.input) do saved[k]=v end
for public,key in pairs(aliases) do
 if query and query.configuration and query.configuration[public]~=nil then build.configTab.input[key]=query.configuration[public] end
end
local records=array()
if query then
 query.offset=0;query.limit=100000
 records=project(build,query,saved,aliases).records
end
local skills=array()
local count={saved_items=0,saved_skill_groups=0,saved_gems=0,saved_tree_specs=#build.treeTab.specList}
for _ in pairs(build.itemsTab.items) do count.saved_items=count.saved_items+1 end
local activeSkillSet
for setId,set in pairs(build.skillsTab.skillSets) do
 local active=set.socketGroupList==build.skillsTab.socketGroupList
 if active then activeSkillSet=setId end
 for groupId,group in ipairs(set.socketGroupList or {}) do
  count.saved_skill_groups=count.saved_skill_groups+1
  for gemId,gem in ipairs(group.gemList or {}) do
   count.saved_gems=count.saved_gems+1
   local effect=build.data.skills[gem.skillId or '']
   if effect then
    skills[#skills+1]={skill_instance_id='skill:s'..setId..':g'..groupId..':n'..gemId,
     skill_id=effect.id,name=effect.name,skill_set_id=setId,group_index=groupId,gem_index=gemId,
     gem_catalog_id=gem.gemData and gem.gemData.id or nil,
     native_character_level_required=gem.reqLevel,
     native_attributes_before_modifiers={strength=gem.reqStr or 0,dexterity=gem.reqDex or 0,intelligence=gem.reqInt or 0},
     native_level=gem.level,quality=gem.quality or 0,enabled=group.enabled~=false and gem.enabled~=false,
     active_set=active,saved_main_group=active and build.mainSocketGroup==groupId,support=not not effect.support,
     origin=(gem.fromItem or gem.fromTree) and 'granted' or 'socketed'}
   end
  end
 end
end
table.sort(skills,function(a,b) return a.skill_instance_id<b.skill_instance_id end)
local itemSet,treeSet
for id,set in pairs(build.itemsTab.itemSets) do if set==build.itemsTab.activeItemSet then itemSet=id end end
for id,spec in ipairs(build.treeTab.specList) do if spec==build.spec then treeSet=id end end
local equipmentSlots=array()
for _,name in ipairs({'Helmet','Body Armour','Gloves','Boots','Belt','Amulet','Ring 1','Ring 2','Weapon 1','Weapon 2'}) do
 local actual=name
 if name:match('^Weapon') and build.itemsTab.activeItemSet.useSecondWeaponSet then actual=actual..' Swap' end
 local slot=build.itemsTab.activeItemSet[actual];local id=slot and slot.selItemId or 0
 local item=build.itemsTab.items[id];local sockets=item and item.itemSocketCount or 0
 local empty=0
 for i=1,sockets do if not item.runes[i] or item.runes[i]=='None' then empty=empty+1 end end
 equipmentSlots[#equipmentSlots+1]={slot=name,saved_item_id=id~=0 and id or nil,empty=id==0,
  augment_socket_capacity=sockets,empty_augment_sockets=empty}
end
local catalog=job.catalog and dofile(root..'catalog.lua').project(build) or nil
io.write(json.encode({catalog=catalog,records=records,skills=skills,metadata={level=build.characterLevel,
 tree_version=build.spec.treeVersion,active_item_set_id=itemSet,active_skill_set_id=activeSkillSet,
 active_tree_set_id=treeSet,active_configuration_set_id=build.configTab.activeConfigSetId,
 active_weapon_set_id=build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1,
 saved_main_group=build.mainSocketGroup,counts=count,equipment_slots=equipmentSlots}}))
