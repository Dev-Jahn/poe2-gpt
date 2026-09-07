"""Internal socket protocol. Never registered as MCP arguments."""
import json
from typing import Annotated
from pydantic import Field, model_validator
from .builds import DTO
from .engine_models import EngineError, EngineSlot, BuildID, EngineSnapshot

# Only official item data consumed by PoB's importer. No sellers, whisper,
# encoded item payload, note, image, URL or arbitrary extra fields are retained.
ITEM_FIELDS = {'id','name','typeLine','baseType','frameType','ilvl','identified','properties','requirements',
    'implicitMods','explicitMods','enchantMods','runeMods','craftedMods','fracturedMods','desecratedMods','mutatedMods',
    'grantedSkills','socketedItems','sockets','corrupted','doubleCorrupted','mirrored','duplicated','sanctified','fractured','desecrated','mutated'}


def private_trade_item(item: dict) -> dict:
    if not isinstance(item, dict):
        raise EngineError('engine_invalid_request')
    # Restrict recursion, size and control characters before private Lua input.
    def walk(v, depth=0):
        if depth>8:
            raise EngineError('engine_invalid_request')
        if isinstance(v, str):
            if len(v)>2000 or any(ord(c)<32 and c not in '\n\r\t' for c in v):
                raise EngineError('engine_invalid_request')
            return v
        if isinstance(v, list) and len(v)<=100:
            return [walk(x,depth+1) for x in v]
        if isinstance(v, dict) and len(v)<=40:
            return {k:walk(x,depth+1) for k,x in v.items() if isinstance(k,str) and len(k)<=80}
        if v is None or type(v) in (bool,int,float):
            return v
        raise EngineError('engine_invalid_request')
    result=walk({k:v for k,v in item.items() if k in ITEM_FIELDS})
    if not isinstance(result.get('name'),str) or not isinstance(result.get('typeLine'),str) or result.get('frameType') not in (0,1,2,3) or type(result.get('ilvl')) is not int:
        raise EngineError('engine_invalid_request')
    if result.get('identified') is not True or item.get('veiledMods'):
        raise EngineError('engine_invalid_request')
    if len(json.dumps(result,allow_nan=False).encode())>32768:
        raise EngineError('engine_invalid_request')
    # Non-explicit mod fields in PoB's importer still expect strings.
    from .trade import plain_mod
    for key in ('implicitMods','explicitMods','enchantMods','runeMods','craftedMods','fracturedMods','desecratedMods','mutatedMods'):
        mods=result.get(key,[])
        if not isinstance(mods,list):
            raise EngineError('engine_invalid_request')
        lines=[]
        for mod in mods:
            text=mod.get('description') if isinstance(mod,dict) else mod
            if not isinstance(text,str):
                raise EngineError('engine_invalid_request')
            text=plain_mod(text)
            if key=='explicitMods' and isinstance(mod,dict):
                lines.append({'description':text,'flags':mod.get('flags',{})})
            else:
                lines.append(text)
        result[key]=lines
    if result.get('socketedItems'):
        # Socketed rune / jewel conversion needs its full PoB character API shape.
        # Refuse ambiguity instead of silently evaluating an incomplete item.
        raise EngineError('engine_invalid_request')
    return result


class WorkerChange(DTO):
    slot: EngineSlot
    saved_item_id: Annotated[int, Field(ge=0,le=1000000)] | None = None
    item: dict | None = None

    @model_validator(mode='after')
    def check(self):
        if (self.item is None)==(self.saved_item_id is None):
            raise ValueError('one_item_source_required')
        if self.item is not None:
            self.item=private_trade_item(self.item)
        return self


class WorkerRequest(DTO):
    build_id: BuildID
    scenarios: Annotated[list[Annotated[list[WorkerChange],Field(max_length=3)]],Field(max_length=64)] = Field(default_factory=list)

    @model_validator(mode='after')
    def distinct(self):
        for changes in self.scenarios:
            if len({c.slot for c in changes})!=len(changes):
                raise ValueError('duplicate_slot')
            ids=[c.saved_item_id if c.item is None else c.item.get('id') for c in changes]
            ids=[v for v in ids if v]
            if len(ids)!=len(set(ids)):
                raise ValueError('duplicate_item')
        return self


class WorkerResult(DTO):
    baseline: EngineSnapshot
    results: Annotated[list[EngineSnapshot],Field(max_length=64)]
