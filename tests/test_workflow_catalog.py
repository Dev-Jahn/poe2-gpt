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
