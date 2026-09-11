-- Full pinned graph and native requirements, not just allocated passive IDs.
local M={}
local function array(t) return setmetatable(t or {},{__jsontype='array'}) end
function M.project(build)
 local nodes,gems,runes=array(),array(),array()
 local classStart,ascendStart
 for id,node in pairs(build.spec.nodes) do
  local stats=array();for _,line in ipairs(node.sd or {}) do stats[#stats+1]=line end
  local links=array();for _,other in ipairs(node.linked or {}) do links[#links+1]=other.id end;table.sort(links)
  local recipe=array();for _,name in ipairs(node.recipe or {}) do recipe[#recipe+1]=name end
  nodes[#nodes+1]={node_id=id,name=node.name,type=node.type,stats=stats,linked_node_ids=links,
   x=node.x or 0,y=node.y or 0,group_id=tonumber(node.g) or 0,ascendancy=node.ascendancyName,
   allocated=not not node.alloc,allocation_mode=node.allocMode or 0,attribute_choice_required=not not node.isAttribute,
   special_allocation_rule=not not (node.isMultipleChoice or node.isMultipleChoiceOption or node.type=='Mastery' or node.isFreeAllocate or node.isProxy),
   recipe=recipe,recipe_catalog_id=#recipe>0 and 'instill:'..id or nil}
  if node.alloc and node.type=='ClassStart' then classStart=id end
  if node.alloc and node.type=='AscendClassStart' then ascendStart=id end
 end
 for id,gem in pairs(build.data.gems) do
  local effect=gem.grantedEffect
  if effect and effect.id then
   local levels=array()
   for level,row in pairs(effect.levels or {}) do
    if type(level)=='number' and level>=1 and level<=100 and type(row.levelRequirement)=='number' then
     levels[#levels+1]={native_level=level,character_level_required=row.levelRequirement,
      strength_required=calcLib.getGemStatRequirement(row.levelRequirement,gem.reqStr,effect.support),
      dexterity_required=calcLib.getGemStatRequirement(row.levelRequirement,gem.reqDex,effect.support),
      intelligence_required=calcLib.getGemStatRequirement(row.levelRequirement,gem.reqInt,effect.support)}
    end
   end
   table.sort(levels,function(a,b) return a.native_level<b.native_level end)
   gems[#gems+1]={catalog_id=id,skill_id=effect.id,name=gem.name,support=not not effect.support,
    natural_max_level=gem.naturalMaxLevel or 1,levels=levels}
  end
 end
 for name,definition in pairs(build.data.itemMods.Runes) do
  local types=array()
  for key,value in pairs(definition) do if type(key)=='string' and type(value)=='table' then types[#types+1]=key end end
  table.sort(types)
  runes[#runes+1]={catalog_id=name,name=name,slot_types=types}
 end
 table.sort(nodes,function(a,b) return a.node_id<b.node_id end)
 table.sort(gems,function(a,b) return a.catalog_id<b.catalog_id end)
 table.sort(runes,function(a,b) return a.catalog_id<b.catalog_id end)
 return {tree_version=build.spec.treeVersion,nodes=nodes,gems=gems,runes=runes,
  class_start_node_id=assert(classStart),ascendancy_start_node_id=ascendStart}
end
return M
