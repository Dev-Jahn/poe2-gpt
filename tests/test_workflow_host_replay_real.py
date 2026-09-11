"""Four synthetic tasks through authenticated HTTP MCP and the real worker.

This is a scripted host-contract replay, not a historical user/LLM or gameplay
success measurement. All IDs are discovered or created in this test session.
"""
import base64,hashlib,json,time,zlib
from types import SimpleNamespace
from xml.etree import ElementTree as ET
import httpx
from jsonschema import Draft202012Validator
from poe2_companion.access import CloudflareAccessMiddleware
from poe2_companion.engine import EngineClient
from poe2_companion.engine_worker import worker_app
from poe2_companion.server import build_server
from poe2_companion.workflow_store import DecisionStore
from test_access import token,verifier
from test_engine_real import real_engine,FIXTURE,BID,MARKER


async def test_four_authenticated_mcp_tasks_with_discovered_identity_and_native_evidence(real_engine,tmp_path,caplog,record_testsuite_property):
    root=ET.fromstring(FIXTURE.read_bytes());ET.SubElement(root,'Notes').text=MARKER
    for skill in ['MeleeAtAnimationSpeed','FireballPlayer','FireballPlayer']:
        group=ET.SubElement(root.find('./Skills/SkillSet'),'Skill',{'enabled':'true','mainActiveSkill':'1'})
        ET.SubElement(group,'Gem',{'skillId':skill,'level':'1','quality':'0','enabled':'true'})
    for identifier,life in [(1,100),(2,200)]:
        ET.SubElement(root.find('Items'),'Item',{'id':str(identifier)}).text=f'Rarity: RARE\nSynthetic Ring\nIron Ring\nImplicits: 0\n+{life} to maximum Life'
    raw=base64.urlsafe_b64encode(zlib.compress(ET.tostring(root)))
    original=real_engine.private_dir/(BID+'.pob');original.write_bytes(raw)
    engine_calls=0;native=real_engine.calculate
    async def counted(request):
        nonlocal engine_calls
        engine_calls+=1;return await native(request)
    real_engine.calculate=counted
    engine=EngineClient('/unused',http=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app(real_engine)),base_url='http://pob-worker'))
    store=DecisionStore('replay',tmp_path/'workflow',tmp_path/'keys'/'key')
    base='https://replay.example.test'
    server=build_server(SimpleNamespace(),engine=engine,decisions=store,allowed_hosts=['replay.example.test'],public_base_url=base)
    app=server.streamable_http_app();access=verifier();secured=CloudflareAccessMiddleware(app,access)
    report={name:{'calls':0,'bytes':0,'errors':0,'elapsed_ms':0.} for name in ['inspect_target','compare_changes','explain_candidate','execute_observe']}
    all_schema={t.name:t.outputSchema for t in await server.list_tools()}
    try:
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=secured),base_url=base,
                headers={'Cf-Access-Jwt-Assertion':token(),'Accept':'application/json, text/event-stream'},timeout=90) as client:
            async def call(name,request,task,expected_error=False):
                row=report[task];row['calls']+=1;started=time.monotonic()
                response=await client.post('/mcp',json={'jsonrpc':'2.0','id':int(sum(r['calls'] for r in report.values())),
                    'method':'tools/call','params':{'name':name,'arguments':{'request':request}}})
                row['elapsed_ms']+=(time.monotonic()-started)*1000
                assert response.status_code==200,response.text
                value=response.json()['result'];text=json.dumps(value,allow_nan=False)
                assert MARKER not in text and raw.decode() not in text
                if value.get('isError'):
                    row['errors']+=1;assert expected_error,value
                    return value
                assert not expected_error
                data=value['structuredContent'];size=len(json.dumps(data,allow_nan=False).encode());row['bytes']+=size
                assert size<=8192,(name,size)
                Draft202012Validator(all_schema[name]).validate(data)
                assert row['calls']<=32 and row['bytes']<=131072
                return data
            async def pages(name,query,section,task):
                chunks=[];offset=0
                while True:
                    part=await call(name,{**query,'section':section,'offset':offset,'limit':1000},task)
                    chunks.append(part['content'])
                    if part['next_offset'] is None:return json.loads(''.join(chunks))
                    assert part['next_offset']>offset;offset=part['next_offset']
            task='inspect_target'
            caps=await call('get_capabilities',{},task)
            assert caps['host_inventory_status']=='unknown'
            profile=(await call('get_build_profile',{'build_id':BID},task))['result']
            fireballs=[s for s in profile['skill_instances'] if s['skill_id']=='FireballPlayer']
            assert len(fireballs)==2 and fireballs[0]['skill_instance_id']!=fireballs[1]['skill_instance_id']
            assert engine_calls==0 and profile['snapshot_digest']==hashlib.sha256(raw).hexdigest()
            target={'skill_instance_id':fireballs[0]['skill_instance_id'],'actor_ref':'player','weapon_set_id':profile['metadata']['active_weapon_set_id']}
            schema=await call('describe_tool_schema',{'tool_name':'recalculate_build'},task)
            assert schema['example_arguments_json'] is not None
            baseline=await call('recalculate_build',{'build_id':BID,'target':target},task)
            assert baseline['baseline']['subject']['status']=='matched'
            assert baseline['baseline']['subject']['evaluated']['skill_instance_id']==target['skill_instance_id']
            assert baseline['baseline']['subject']['saved']['skill_id']=='MeleeAtAnimationSpeed'
            assert engine_calls==1
            task='compare_changes';experiments=[]
            for item_id in [1,2]:
                request={'base_build_id':BID,'base_snapshot_digest':profile['snapshot_digest'],'tree_revision':profile['metadata']['tree_version'],
                    'engine_data_commit':profile['engine_data_commit'],'target':target,'edits':[
                        {'type':'equip_item','slot':'ring_left','source':{'kind':'saved_item','saved_item_id':item_id}},
                        {'type':'set_gem','skill_instance_id':target['skill_instance_id'],'native_level':1,'quality':1}]}
                experiment=await call('create_build_experiment',request,task);experiments.append(experiment)
                assert experiment['audit']['status']=='valid_changeset' and experiment['certified']
                assert experiment['subject']['evaluated']['skill_instance_id']==target['skill_instance_id']
                plan=await pages('get_build_plan',{'experiment_id':experiment['experiment_id']},'plan_json',task)
                from poe2_companion.experiment_models import ExperimentRequest
                assert plan['base_snapshot_digest']==profile['snapshot_digest']
                assert plan['edits']==ExperimentRequest.model_validate(request).model_dump(mode='json')['edits']
                state=await call('get_build_plan',{'experiment_id':experiment['experiment_id']},task)
                assert state['state']=='proposed' and not state['saved_base_is_current_character']
            assert engine_calls==3 and original.read_bytes()==raw
            task='explain_candidate';groups=[]
            for key,experiment,price in zip(['affordable','over_budget'],experiments,[1.,100.]):
                groups.append({'key':key,'experiment_ids':[experiment['experiment_id']],'costs':[
                    {'edit_index':1,'kind':'skill_gem','entity_id':target['skill_instance_id'],'evidence':'user_confirmed_owned'},
                    {'edit_index':1,'kind':'gem_quality','entity_id':target['skill_instance_id'],'evidence':'user_reported_price',
                        'unit_price':{'amount':price,'currency':'divine'},'observed_at_epoch':int(time.time())}]})
            comparison=await call('compare_build_purchase_plans',{'league':'Forbidden Rites','declared_character_league':'Forbidden Rites',
                'budget':{'amount':10.,'currency':'divine'},'weights':[{'stat':'Life','weight':1.}], 'candidates':groups},task)
            assert comparison['primary_candidate_key']=='affordable'
            excluded=next(c for c in comparison['candidates'] if c['key']=='over_budget')
            assert excluded['budget_status']=='over_budget' and excluded['total_estimated_cost']==100.
            detail=await pages('get_purchase_comparison',{'comparison_id':comparison['comparison_id']},'exact_json',task)
            candidate=next(c for c in detail['candidates'] if c['key']=='over_budget')
            assert candidate['scenarios'][0]['experiment_id']==experiments[1]['experiment_id']
            assert candidate['bill'][-1]['entity_id']==target['skill_instance_id']
            task='execute_observe';chosen=experiments[0]
            route=await call('create_build_execution_plan',{'experiment_id':chosen['experiment_id'],'comparison_id':comparison['comparison_id']},task)
            assert route['primary_route_count']==1 and route['status']=='ready_for_user_execution' and route['stop_conditions']
            exported=await call('export_build_execution_plan',{'execution_id':route['execution_id'],'format':'markdown'},task)
            downloaded=await client.get(exported['download_url']);assert downloaded.status_code==200
            assert hashlib.sha256(downloaded.content).hexdigest()==exported['content_sha256']
            revision=(await call('update_build_plan',{'experiment_id':chosen['experiment_id'],'expected_revision':1,
                'expected_plan_digest':chosen['plan_digest'],'state':'accepted'},task))['revision']
            partial=await call('update_build_plan',{'experiment_id':chosen['experiment_id'],'expected_revision':revision,
                'expected_plan_digest':chosen['plan_digest'],'state':'partially_applied','applied_edit_indices':[0]},task)
            assert partial['state']=='partially_applied' and partial['source_confirmation']=='pending_source_confirmation'
            observation=await call('record_build_observation',{'base_build_id':BID,'base_snapshot_digest':profile['snapshot_digest'],
                'related_experiment_id':chosen['experiment_id'],'observed_at_epoch':int(time.time()),'values':[{'kind':'resource_outcome','resource':'energy_shield',
                    'maximum':100.,'minimum_during_encounter':0.,'encounter':'ritual','outcome':'depleted'}]},task)
            assert observation['status']=='pending_source_confirmation'
            state=await call('get_build_plan',{'experiment_id':chosen['experiment_id']},task)
            assert state['state']=='observed' and state['source_confirmation']=='pending_source_confirmation'
            old=await call('get_build_execution_plan',{'execution_id':route['execution_id']},task);assert old['source_revision_changed']
            blocked=await call('create_build_execution_plan',{'experiment_id':chosen['experiment_id'],'comparison_id':comparison['comparison_id']},task)
            assert blocked['status']=='blocked' and blocked['primary_route_count']==0
            assert any('adverse_outcome_reported' in reason for reason in blocked['blocking_reasons'])
            client.headers['Cf-Access-Jwt-Assertion']=token(sub='other-owner')
            await call('get_build_plan',{'experiment_id':chosen['experiment_id']},task,expected_error=True)
            await call('get_build_observations',{'observation_ids':[observation['observation_id']]},task,expected_error=True)
            await call('get_build_diagnostics',{'calculation_id':chosen['calculation_id']},task,expected_error=True)
            assert (await client.get(exported['download_url'])).status_code==404
            client.headers['Cf-Access-Jwt-Assertion']=token()
            assert (await call('get_build_plan',{'experiment_id':chosen['experiment_id']},task))['state']=='observed'
            assert original.read_bytes()==raw and MARKER not in caplog.text and raw.decode() not in caplog.text
            record_testsuite_property('workflow_replay',json.dumps({'scope':'synthetic_scripted_authenticated_http_mcp_not_historical_or_gameplay',
                'tasks':report,'target_assertions':3,'wrong_subject_count':0,'source_state_assertions':5,'stale_fact_count':0,
                'primary_actionable_routes':1,'adverse_outcome_blocks':1,'user_gameplay_success_observed':False}))
    finally:await access.close();await engine.close();store.close()
