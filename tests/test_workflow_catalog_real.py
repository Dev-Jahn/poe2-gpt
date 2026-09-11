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
    import httpx
    from poe2_companion.engine_worker import worker_app
    from poe2_companion.engine import EngineClient
    from poe2_companion.passive_execution import PassiveOrderRequest,PassiveOrderResult
    client=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://pob-worker'))
    try:
        ordered=await client.static_request('/passive-order',PassiveOrderRequest(build_id=BID,tree_revision='0_5',actions=[
            {'edit_index':0,'action':'allocate','node_ids':[target.node_id]},
            {'edit_index':1,'action':'refund','node_ids':[target.node_id]}]),PassiveOrderResult)
        assert ordered.status=='verified' and ordered.actions[0].node_ids==[target.node_id]
        assert before==real_engine.inspector.process_runs
    finally:await client.close()


async def test_native_weapon_branches_use_shared_ordinary_budget_and_explicit_unlock_evidence(real_engine):
    import hashlib
    from poe2_companion.engine_protocol import WorkerRequest,ExperimentVariantJob
    from poe2_companion.experiment_models import ExperimentRequest
    from poe2_companion.engine_models import ENGINE_DATA_COMMIT
    catalog=(await real_engine.inspector.document(BID,catalog=True))[0].catalog
    start=next(n for n in catalog.nodes if n.node_id==catalog.class_start_node_id)
    adjacent=[n for n in catalog.nodes if n.node_id in start.linked_node_ids and n.type=='Normal' and not n.special_allocation_rule]
    assert len(adjacent)>=2
    edits=[{'type':'allocate_passives','node_ids':[n.node_id],'allocation_mode':mode,
        'attribute_choices':[{'node_id':n.node_id,'attribute':'strength'}] if n.attribute_choice_required else []}
        for mode,n in enumerate(adjacent[:2],1)]
    raw=(real_engine.private_dir/(BID+'.pob')).read_bytes()
    query=ExperimentRequest(base_build_id=BID,base_snapshot_digest=hashlib.sha256(raw).hexdigest(),tree_revision='0_5',
        engine_data_commit=ENGINE_DATA_COMMIT,target={'skill_instance_id':'skill:s1:g1:n1','actor_ref':'player','weapon_set_id':1},
        edits=edits,ordinary_points_available=1)
    known=query.model_copy(update={'weapon_set_1_points_available':1,'weapon_set_2_points_available':1})
    result=await real_engine.calculate(WorkerRequest(build_id=BID,target=query.target,variant_jobs=[
        ExperimentVariantJob(request=q) for q in [query,known]]))
    missing,valid=result.experiment_variants
    assert missing.audit.status=='rejected_atomically' and missing.audit.failures[0].code=='weapon_point_budget_unreported'
    assert valid.audit.status=='valid_changeset'
    assert valid.audit.ordinary_points_delta==1
    assert valid.audit.weapon_set_1_points_delta==valid.audit.weapon_set_2_points_delta==1
