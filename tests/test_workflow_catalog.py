from poe2_companion.catalog import route
from poe2_companion.catalog_models import NativeCatalog, PassiveNode, PassiveRouteRequest

BID='bld_'+'1'*32


def node(identifier,links,allocated=False,mode=0,asc=None):
    return PassiveNode(node_id=identifier,name=f'Node {identifier}',type='ClassStart' if identifier==1 else 'Normal',
        stats=[],linked_node_ids=links,x=identifier,y=0,group_id=1,allocated=allocated,allocation_mode=mode,
        ascendancy=asc,attribute_choice_required=False,special_allocation_rule=False,recipe=[])


def test_entire_weapon_cluster_is_a_path_source_and_refunds_keep_connectivity():
    nodes=[node(1,[10],True),node(10,[1,11],True,1),node(11,[10,12],True,1)]
    nodes.extend(node(i,[i-1]+([i+1] if i<16 else [])) for i in range(12,17))
    catalog=NativeCatalog(tree_version='0_5',nodes=nodes,gems=[],runes=[],class_start_node_id=1)
    request=PassiveRouteRequest(build_id=BID,tree_revision='0_5',target_node_ids=[16],ordinary_points_available=5,allocation_mode=1,weapon_set_points_available=5)
    result=route(catalog,request)
    assert result.status=='route_found' and result.ordinary_points_cost==5
    assert [s.node_id for s in result.steps]==[12,13,14,15,16]
    assert result.steps[0].connected_from_node_id==11
    assert not result.global_optimum_proven
    assert route(catalog,request.model_copy(update={'weapon_set_points_available':None})).status=='weapon_point_budget_unreported'
    assert route(catalog,request.model_copy(update={'ordinary_points_available':4})).status=='over_budget'
    disconnected=route(catalog,request.model_copy(update={'refund_node_ids':[10]}))
    assert disconnected.status=='disconnected_after_refund' and disconnected.disconnected_node_ids==[11]


def test_matching_weapon_branches_share_ordinary_points():
    catalog=NativeCatalog(tree_version='0_5',nodes=[node(1,[2,3],True),node(2,[1],True,1),node(3,[1])],
        gems=[],runes=[],class_start_node_id=1)
    result=route(catalog,PassiveRouteRequest(build_id=BID,tree_revision='0_5',target_node_ids=[3],
        ordinary_points_available=0,allocation_mode=2,weapon_set_points_available=1))
    assert result.status=='route_found' and result.ordinary_points_delta==0 and result.weapon_set_points_delta==1


def test_other_weapon_branch_cannot_be_used_as_free_travel():
    catalog=NativeCatalog(tree_version='0_5',nodes=[node(1,[2],True),node(2,[1,3],True,2),node(3,[2,4]),node(4,[3])],
        gems=[],runes=[],class_start_node_id=1)
    query=PassiveRouteRequest(build_id=BID,tree_revision='0_5',target_node_ids=[4],ordinary_points_available=5,
        allocation_mode=1,weapon_set_points_available=5)
    assert route(catalog,query).status=='no_route'


def test_candidate_generation_includes_full_regular_and_existing_weapon_branches():
    from poe2_companion.passive_candidates import PassiveCandidatesRequest,discover
    nodes=[node(1,[2,10],True),node(2,[1,3]),node(3,[2]),node(10,[1,11],True,1),node(11,[10,12],True,1),node(12,[11])]
    catalog=NativeCatalog(tree_version='0_5',nodes=nodes,gems=[],runes=[],class_start_node_id=1)
    query=PassiveCandidatesRequest(build_id=BID,tree_revision='0_5',ordinary_points_available=5,weapon_set_1_points_available=5,limit=2)
    rows=[]
    while True:
        page=discover(catalog,query);rows+=page.candidates
        if page.next_offset is None:break
        query.offset=page.next_offset
    found={(r.target_node_id,r.allocation_mode):r for r in rows}
    assert (3,0) in found and (12,1) in found
    assert found[3,0].total_new_path_nodes==2
    assert found[12,1].total_new_path_nodes==1 and found[12,1].start_landmark=='Node 11'
    assert (12,0) not in found and (12,2) not in found
    assert found[3,2].status=='weapon_point_budget_unreported'
    assert len(found)==len(rows)==page.total_candidates
