from poe2_companion.catalog import page,route
from poe2_companion.catalog_models import CatalogRequest, PassiveRouteRequest
from test_engine_real import real_engine,BID


async def test_full_native_catalog_and_requirements_without_calculation(real_engine):
    document,_=await real_engine.inspector.document(BID,catalog=True)
    catalog=document.catalog
    assert catalog is not None and len(catalog.nodes)>1000 and len(catalog.gems)>100
    assert len([n for n in catalog.nodes if n.allocated])<len(catalog.nodes)
    start=next(n for n in catalog.nodes if n.node_id==catalog.class_start_node_id)
    target=next(n for n in catalog.nodes if n.node_id in start.linked_node_ids and not n.special_allocation_rule)
    result=route(catalog,PassiveRouteRequest(build_id=BID,tree_revision='0_5',target_node_ids=[target.node_id],ordinary_points_available=1))
    assert result.ordinary_points_cost==1 and result.steps[0].connected_from_node_id==start.node_id
    gems=page(catalog,CatalogRequest(build_id=BID,entity_type='gem',query='Fireball',level_limit=2))
    assert gems.gems and all(len(g.levels)<=2 for g in gems.gems)
    assert any(g.next_level_offset==2 for g in gems.gems)
    before=real_engine.inspector.process_runs
    await real_engine.inspector.document(BID,catalog=True)
    assert before==real_engine.inspector.process_runs
