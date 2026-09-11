"""Versioned graph search and bounded entity projections; no web-node guessing."""
from collections import deque
from collections.abc import Sequence
from .builds import bounded_dto, BuildError
from .catalog_models import (NativeCatalog, CatalogRequest, CatalogPage, PassiveRouteRequest,
    PassiveRoute, RouteStep, PassiveNode, GemDefinition, RuneDefinition)
from .engine_models import ENGINE_DATA_COMMIT, EngineError
from .game_terms import name_fields, english_query


def localized(node: PassiveNode) -> PassiveNode:
    labels=name_fields(node.name)
    return node.model_copy(update={'name_ko':labels['name_ko'],'translation_source':labels['name_source_ko']})


def page(catalog: NativeCatalog, request: CatalogRequest) -> CatalogPage:
    query=english_query(request.query).casefold()
    source: Sequence[PassiveNode | GemDefinition | RuneDefinition] = catalog.nodes if request.entity_type=='passive' else catalog.gems if request.entity_type=='gem' else catalog.runes
    rows=[]
    for row in source:
        if request.node_ids and (not isinstance(row,PassiveNode) or row.node_id not in request.node_ids): continue
        identifier=str(row.node_id) if isinstance(row,PassiveNode) else row.catalog_id
        if request.catalog_id is not None and request.catalog_id!=identifier: continue
        if request.catalog_ids and identifier not in request.catalog_ids: continue
        if query and query not in row.name.casefold() and query not in identifier.casefold(): continue
        rows.append(row)
    selected=rows[request.offset:request.offset+request.limit]
    result=CatalogPage(build_id=request.build_id,entity_type=request.entity_type,tree_version=catalog.tree_version,
        data_revision=ENGINE_DATA_COMMIT,total=len(rows),next_offset=None)
    if request.entity_type=='passive': result.passives=[localized(row) for row in selected if isinstance(row,PassiveNode)]
    elif request.entity_type=='gem':
        for row in selected:
            if not isinstance(row,GemDefinition): continue
            end=request.level_offset+request.level_limit
            levels = [level for level in row.levels if level.native_level == request.native_level] if request.native_level is not None else row.levels[request.level_offset:end]
            result.gems.append(row.model_copy(update={'levels':levels,
                'level_count':len(row.levels),'next_level_offset':end if request.native_level is None and end<len(row.levels) else None}))
    else: result.runes=[row for row in selected if isinstance(row,RuneDefinition)]
    entries: list[PassiveNode] | list[GemDefinition] | list[RuneDefinition] = result.passives if request.entity_type=='passive' else result.gems if request.entity_type=='gem' else result.runes
    while True:
        end=request.offset+len(entries)
        result.next_offset=end if end<len(rows) else None
        try: return bounded_dto(result)
        except BuildError:
            if len(entries)<=1: raise
            entries.pop()


def route(catalog: NativeCatalog, request: PassiveRouteRequest) -> PassiveRoute:
    if request.tree_revision!=catalog.tree_version: raise EngineError('engine_version_mismatch')
    nodes={node.node_id:node for node in catalog.nodes}
    allocated={node.node_id for node in catalog.nodes if node.allocated}
    original=set(allocated)
    modes={node.node_id:node.allocation_mode for node in catalog.nodes}
    original_modes=dict(modes)
    roots={catalog.class_start_node_id}
    if catalog.ascendancy_start_node_id is not None: roots.add(catalog.ascendancy_start_node_id)
    if not set(request.refund_node_ids)<=allocated or roots & set(request.refund_node_ids):
        raise EngineError('engine_invalid_request')
    allocated-=set(request.refund_node_ids)
    result=PassiveRoute(build_id=request.build_id,tree_revision=catalog.tree_version,data_revision=ENGINE_DATA_COMMIT,
        status='route_found',steps=[],total_steps=0,refund_node_ids=request.refund_node_ids,
        ordinary_points_cost=0,ascendancy_points_cost=0,requested_targets=request.target_node_ids)
    def reachable(mode):
        found=set(roots);queue=deque(sorted(roots))
        while queue:
            node=nodes[queue.popleft()]
            for identifier in node.linked_node_ids:
                other=nodes.get(identifier)
                if (identifier in allocated and identifier not in found and other is not None
                        and other.allocation_mode in (0,mode) and node.ascendancy==other.ascendancy):
                    found.add(identifier);queue.append(identifier)
        return found
    reach={mode:reachable(mode) for mode in (0,1,2)}
    disconnected=sorted(identifier for identifier in allocated if identifier not in reach[nodes[identifier].allocation_mode]
        and not nodes[identifier].special_allocation_rule)
    if disconnected:
        result.status='disconnected_after_refund';result.disconnected_node_ids=disconnected[:32];return result
    steps=[]
    for target in request.target_node_ids:
        if target not in nodes: raise EngineError('engine_invalid_request')
        goal=nodes[target]
        if target in allocated: continue
        if goal.special_allocation_rule or (request.allocation_mode and goal.type in {'Keystone','Socket'}):
            result.status='unsupported_node_rule';break
        sources=sorted(identifier for identifier in allocated if nodes[identifier].allocation_mode in (0,request.allocation_mode)
            and nodes[identifier].ascendancy==goal.ascendancy)
        queue=deque(sources)
        parent: dict[int,int | None] = {identifier:None for identifier in sources}
        while queue and target not in parent:
            identifier=queue.popleft()
            for other_id in sorted(nodes[identifier].linked_node_ids):
                other=nodes.get(other_id)
                if (other is None or other_id in parent or other.special_allocation_rule
                        or (other_id in allocated and modes[other_id] not in (0,request.allocation_mode))
                        or (request.allocation_mode and other.type in {'Keystone','Socket'})
                        or other.ascendancy!=goal.ascendancy or other.type in {'ClassStart','AscendClassStart'}): continue
                parent[other_id]=identifier;queue.append(other_id)
        if target not in parent:
            result.status='no_route';break
        path=[];cursor=target
        while cursor not in allocated:
            path.append(cursor)
            previous_id=parent[cursor]
            assert previous_id is not None
            cursor=previous_id
        for identifier in reversed(path):
            previous_id=parent[identifier]
            assert previous_id is not None
            node=localized(nodes[identifier]);previous=nodes[previous_id]
            steps.append(RouteStep(node_id=identifier,name=node.name,name_ko=node.name_ko,
                translation_source=node.translation_source,connected_from_node_id=previous.node_id,
                landmark=previous.name,point_pool='ascendancy' if node.ascendancy else 'ordinary',
                attribute_choice_required=node.attribute_choice_required,allocation_mode=request.allocation_mode,stats=node.stats))
            allocated.add(identifier)
            modes[identifier]=request.allocation_mode
            if node.ascendancy: result.ascendancy_points_cost+=1
            else: result.ordinary_points_cost+=1
    def point_counts(active,state_modes):
        ordinary=[n for n in active if n not in roots and not nodes[n].ascendancy and not nodes[n].special_allocation_rule]
        weapon1=sum(state_modes[n]==1 for n in ordinary);weapon2=sum(state_modes[n]==2 for n in ordinary)
        return len(ordinary)-min(weapon1,weapon2),sum(bool(nodes[n].ascendancy) and n not in roots for n in active),weapon1,weapon2
    before=point_counts(original,original_modes);after=point_counts(allocated,modes)
    result.ordinary_points_delta=after[0]-before[0];result.ascendancy_points_delta=after[1]-before[1]
    result.weapon_set_points_delta=after[request.allocation_mode+1]-before[request.allocation_mode+1] if request.allocation_mode else 0
    if result.status=='route_found':
        if result.ordinary_points_delta>request.ordinary_points_available or result.ascendancy_points_delta>request.ascendancy_points_available:result.status='over_budget'
        elif result.weapon_set_points_delta>0 and request.weapon_set_points_available is None:result.status='weapon_point_budget_unreported'
        elif result.weapon_set_points_delta>(request.weapon_set_points_available or 0):result.status='over_budget'
    result.total_steps=len(steps)
    end=request.offset+request.limit
    result.steps=steps[request.offset:end]
    result.next_offset=end if end<len(steps) else None
    while True:
        try:return bounded_dto(result)
        except BuildError:
            if len(result.steps)<=1:raise
            result.steps.pop();result.next_offset=request.offset+len(result.steps)
