"""Enumerate all adjacent ordinary/weapon paths within an explicit hop budget."""
from collections import deque
from typing import Annotated,Literal
from pydantic import Field,model_validator
from .builds import DTO,bounded_dto,tool_json_bytes
from .catalog_models import BuildRef,NativeCatalog,NodeID,PassiveRouteRequest
from .catalog import route,localized
from .engine_models import ENGINE_DATA_COMMIT,EngineError
from .game_terms import english_query


class PassiveCandidatesRequest(DTO):
    build_id: BuildRef
    tree_revision: Annotated[str,Field(max_length=24)]
    maximum_new_path_nodes: Annotated[int,Field(ge=1,le=16)] = 5
    ordinary_points_available: Annotated[int,Field(ge=0,le=64)]
    weapon_set_1_points_available: Annotated[int,Field(ge=0,le=128)] | None = None
    weapon_set_2_points_available: Annotated[int,Field(ge=0,le=128)] | None = None
    allocation_modes: Annotated[list[Literal[0,1,2]],Field(min_length=1,max_length=3)] = [0,1,2]
    query: Annotated[str,Field(max_length=100,pattern=r'^[^\x00-\x1f\x7f]*$')] = ''
    offset: Annotated[int,Field(ge=0,le=90000)] = 0
    limit: Annotated[int,Field(ge=1,le=8)] = 5

    @model_validator(mode='after')
    def modes(self):
        if len(set(self.allocation_modes))!=len(self.allocation_modes):raise ValueError('duplicate_allocation_mode')
        return self


class PassiveCandidate(DTO):
    target_node_id: NodeID
    allocation_mode: Literal[0,1,2]
    name: str
    name_ko: str | None
    translation_source: str | None
    effect_summary: str
    full_effects_require_catalog: Literal[True] = True
    start_landmark: str
    total_new_path_nodes: int
    ordinary_points_delta: int
    weapon_set_points_delta: int
    attribute_choices_required: int
    status: Literal['within_reported_budget','over_budget','weapon_point_budget_unreported']


class PassiveCandidates(DTO):
    build_id: BuildRef
    tree_revision: str
    engine_data_commit: str = ENGINE_DATA_COMMIT
    status: Literal['enumerated','base_graph_disconnected']
    candidates: Annotated[list[PassiveCandidate],Field(max_length=8)]
    total_candidates: int
    next_offset: int | None
    searched_allocation_modes: list[Literal[0,1,2]]
    maximum_new_path_nodes: int
    search_scope: Literal['all_reachable_unallocated_normal_and_notable_endpoints_within_hop_limit_and_text_filter'] = 'all_reachable_unallocated_normal_and_notable_endpoints_within_hop_limit_and_text_filter'
    special_allocation_and_ascendancy_routes_included: Literal[False] = False
    objective_scores_computed: Literal[False] = False
    global_optimum_proven: Literal[False] = False
    next_action: Literal['compare_complete_paths_with_compare_passive_paths'] = 'compare_complete_paths_with_compare_passive_paths'


def discover(catalog: NativeCatalog,request: PassiveCandidatesRequest) -> PassiveCandidates:
    if catalog.tree_version!=request.tree_revision:raise EngineError('engine_version_mismatch')
    nodes={n.node_id:n for n in catalog.nodes};allocated={n.node_id for n in catalog.nodes if n.allocated}
    result=PassiveCandidates(build_id=request.build_id,tree_revision=catalog.tree_version,status='enumerated',candidates=[],
        total_candidates=0,next_offset=None,searched_allocation_modes=request.allocation_modes,maximum_new_path_nodes=request.maximum_new_path_nodes)
    check=route(catalog,PassiveRouteRequest(build_id=request.build_id,tree_revision=request.tree_revision,
        target_node_ids=[catalog.class_start_node_id],ordinary_points_available=request.ordinary_points_available))
    if check.status=='disconnected_after_refund':result.status='base_graph_disconnected';return result
    w1=sum(n.allocated and n.allocation_mode==1 and not n.ascendancy and not n.special_allocation_rule for n in catalog.nodes)
    w2=sum(n.allocated and n.allocation_mode==2 and not n.ascendancy and not n.special_allocation_rule for n in catalog.nodes)
    query=english_query(request.query).casefold();rows=[]
    for mode in request.allocation_modes:
        sources=sorted(n for n in allocated if nodes[n].allocation_mode in (0,mode) and not nodes[n].ascendancy and not nodes[n].special_allocation_rule)
        parents: dict[int,int|None]={n:None for n in sources};distance={n:0 for n in sources};queue=deque(sources)
        while queue:
            current=queue.popleft()
            if distance[current]>=request.maximum_new_path_nodes:continue
            for identifier in sorted(nodes[current].linked_node_ids):
                node=nodes.get(identifier)
                if node is None or identifier in parents or node.ascendancy or node.special_allocation_rule:continue
                if node.type in {'ClassStart','AscendClassStart','Mastery'} or (mode and node.type in {'Keystone','Socket'}):continue
                if identifier in allocated:continue
                parents[identifier]=current;distance[identifier]=distance[current]+1;queue.append(identifier)
        for identifier,d in distance.items():
            if not d:continue
            node=nodes[identifier]
            if node.type not in {'Normal','Notable'}:continue
            if query and query not in node.name.casefold() and not any(query in s.casefold() for s in node.stats):continue
            path=[];cursor=identifier
            while parents[cursor] is not None:
                path.append(cursor);previous=parents[cursor]
                assert previous is not None
                cursor=previous
            node=localized(node)
            ordinary=d if mode==0 else d-(min(w1+(d if mode==1 else 0),w2+(d if mode==2 else 0))-min(w1,w2))
            weapon=d if mode else 0
            available=request.weapon_set_1_points_available if mode==1 else request.weapon_set_2_points_available
            status: Literal['within_reported_budget','over_budget','weapon_point_budget_unreported']='within_reported_budget'
            if ordinary>request.ordinary_points_available or (mode and available is not None and weapon>available):status='over_budget'
            elif mode and available is None:status='weapon_point_budget_unreported'
            rows.append(PassiveCandidate(target_node_id=identifier,allocation_mode=mode,name=node.name,name_ko=node.name_ko,
                translation_source=node.translation_source,effect_summary='; '.join(node.stats[:2])[:300],start_landmark=nodes[cursor].name,
                total_new_path_nodes=d,ordinary_points_delta=ordinary,weapon_set_points_delta=weapon,
                attribute_choices_required=sum(nodes[n].attribute_choice_required for n in path),status=status))
    rows.sort(key=lambda r:(r.status!='within_reported_budget',r.total_new_path_nodes,r.allocation_mode,r.target_node_id))
    result.total_candidates=len(rows);end=request.offset+request.limit
    result.candidates=rows[request.offset:end];result.next_offset=end if end<len(rows) else None
    while tool_json_bytes(result)>8192 and len(result.candidates)>1:
        result.candidates.pop();result.next_offset=request.offset+len(result.candidates)
    return bounded_dto(result)
