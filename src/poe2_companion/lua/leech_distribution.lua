-- Expectations under the supplied per-type post-mitigation hit distributions.
-- Each sample caps TOTAL damage and preserves each type's leech contribution.
local M={}
function M.capped_mean(a,b,cap,lucky,endpoints)
 if b<=a then return math.min(a,cap) end
 if endpoints then
  local high=0.5+0.25*(lucky or 0)
  return (1-high)*math.min(a,cap)+high*math.min(b,cap)
 end
 local t=math.max(0,math.min(1,(cap-a)/(b-a)))
 local normal=a*t+(b-a)*t*t/2+cap*(1-t)
 local luck=a*t*t+2*(b-a)*t*t*t/3+cap*(1-t*t)
 return normal*(1-(lucky or 0))+luck*(lucky or 0)
end
function M.integrate(types,cap)
 local active={}
 for _,v in ipairs(types) do if v.maximum>0 then active[#active+1]=v end end
 if #active==0 then return 0,0,0,true end
 local hasLeech,totalMaximum=false,0
 for _,v in ipairs(active) do
  hasLeech=hasLeech or v.life~=0 or v.mana~=0 or v.es~=0
  totalMaximum=totalMaximum+v.maximum
 end
 if not hasLeech then return 0,0,0,true end
 if totalMaximum<=cap then
  -- No possible hit reaches the nonlinear cap: linear expectation is exact,
  -- irrespective of cross-type correlation, without numerical quadrature.
  local life,mana,es=0,0,0
  for _,v in ipairs(active) do
   local mean=M.capped_mean(v.minimum,v.maximum,cap,v.lucky,v.endpoints)
   life,mana,es=life+mean*v.life,mana+mean*v.mana,es+mean*v.es
  end
  return life,mana,es,true
 end
 if #active==1 then
  local v=active[1]
  local mean=M.capped_mean(v.minimum,v.maximum,cap,v.lucky,v.endpoints)
  return mean*v.life,mean*v.mana,mean*v.es,true
 end
 local exact=true
 for _,v in ipairs(active) do if v.maximum>v.minimum and not v.endpoints then exact=false end end
 local life,mana,es=0,0,0
 local function visit(i,prob,total,l,m,e)
  if i>#active then
   local scale=total>0 and math.min(1,cap/total)*prob or 0
   life,mana,es=life+l*scale,mana+m*scale,es+e*scale;return
  end
  local v=active[i]
  local function sample(d,p) visit(i+1,prob*p,total+d,l+d*v.life,m+d*v.mana,e+d*v.es) end
  if v.minimum==v.maximum then sample(v.minimum,1)
  elseif v.endpoints then
   local high=0.5+0.25*(v.lucky or 0)
   sample(v.minimum,1-high);sample(v.maximum,high)
  else
   -- Bounded deterministic midpoint quadrature; explicitly marked approximate.
   for j=1,8 do
    local u=(j-0.5)/8
    sample(v.minimum+(v.maximum-v.minimum)*u,((1-(v.lucky or 0))+2*u*(v.lucky or 0))/8)
   end
  end
 end
 visit(1,1,0,0,0,0)
 return life,mana,es,exact
end
return M
