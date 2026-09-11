"""Download existence/content hashes and owner checks over authenticated HTTP MCP."""
import hashlib,json,time
from types import SimpleNamespace
import httpx,pytest
from jsonschema import Draft202012Validator
from poe2_companion.access import CloudflareAccessMiddleware
from poe2_companion.account_ui import AccountUI
from poe2_companion.capabilities import digest
from poe2_companion.execution_plans import ExecutionDocument
from poe2_companion.plan_exports import ExportRequest,create
from poe2_companion.workflow_store import DecisionStore,WorkflowError
from poe2_companion.server import build_server
from test_access import CONFIG,token,verifier
from test_accounts import call

OWNER=CONFIG.issuer+'\0owner-subject';BASE='https://accounts.example.test'


def source(store):
    value=ExecutionDocument(execution_id='route_'+'1'*32,request={'experiment_id':'exp_'+'2'*32},experiment_revision=1,
        source_artifact_digest='a'*64,artifact_digest='0'*64,created_at_epoch=int(time.time()),expires_at_epoch=int(time.time())+3600,
        blocking_reasons=[],risk_notes=['EnergyShield: 1000 → 900'],steps=[{'index':0,'phase':'apply','instruction':'Fireball의 기본 레벨을 2로 맞추세요.',
            'edit_index':0,'entity_refs':['skill:s1:g1:n1'],'executable_now':True}])
    value.artifact_digest=digest(value.model_dump(mode='json',exclude={'artifact_digest'}))
    store.save_artifact(OWNER,'execution_plan',value.execution_id,value,value.expires_at_epoch,True)
    return value


async def test_authenticated_download_matches_mcp_hash_and_rejects_other_owner(tmp_path):
    store=DecisionStore('member',tmp_path/'state',tmp_path/'keys'/'key');value=source(store)
    server=build_server(SimpleNamespace(),engine=SimpleNamespace(),decisions=store,allowed_hosts=['accounts.example.test'],public_base_url=BASE)
    app=server.streamable_http_app();access=verifier()
    # Account UI must pass the artifact route to its independent owner check.
    secured=CloudflareAccessMiddleware(AccountUI(app,SimpleNamespace(),BASE,'/accounts','__Secure-test'),access)
    schemas={t.name:t.outputSchema for t in await server.list_tools()}
    try:
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=secured),base_url=BASE,
                headers={'Cf-Access-Jwt-Assertion':token(),'Accept':'application/json, text/event-stream'}) as client:
            for format in ['json','markdown']:
                result=await call(client,'export_build_execution_plan',{'execution_id':value.execution_id,'format':format,'persist_export':True})
                assert not result.get('isError'),result
                export=result['structuredContent'];Draft202012Validator(schemas['export_build_execution_plan']).validate(export)
                response=await client.get(export['download_url']);assert response.status_code==200
                assert len(response.content)==export['byte_length']
                assert hashlib.sha256(response.content).hexdigest()==export['content_sha256']==response.headers['X-Content-SHA256']
                assert export['filename'] in response.headers['Content-Disposition'] and response.headers['Cache-Control']=='no-store'
                if format=='json':assert response.json()==value.model_dump(mode='json')
                else:
                    exact=json.loads(response.text.split('```json\n')[1].split('\n```')[0])
                    assert exact==value.model_dump(mode='json') and '기본 레벨을 2' in response.text
                client.headers['Cf-Access-Jwt-Assertion']=token(sub='different-owner')
                assert (await client.get(export['download_url'])).status_code==404
                await call(client,'delete_build_plan_export',{'export_id':export['export_id']})
                client.headers['Cf-Access-Jwt-Assertion']=token()
                assert (await client.head(export['download_url'])).status_code==200
                await call(client,'delete_build_plan_export',{'export_id':export['export_id']})
                assert (await client.get(export['download_url'])).status_code==404
            client.headers.pop('Cf-Access-Jwt-Assertion')
            assert (await client.get('/accounts/artifacts/export_'+'1'*32)).status_code==403
    finally:await access.close();store.close()
    assert b'Fireball' not in (tmp_path/'state'/'decisions.sqlite3').read_bytes()


def test_changed_render_object_cannot_export_under_old_plan_hash(tmp_path):
    store=DecisionStore('m',tmp_path/'state',tmp_path/'keys'/'key');value=source(store)
    store.delete_artifact(OWNER,'execution_plan',value.execution_id)
    value.steps[0].instruction='Fireball의 기본 레벨을 20으로 맞추세요.'
    store.save_artifact(OWNER,'execution_plan',value.execution_id,value,value.expires_at_epoch,True)
    with pytest.raises(WorkflowError,match='artifact_content_digest_mismatch'):
        create(ExportRequest(execution_id=value.execution_id),store,OWNER,BASE,'/accounts/artifacts')
    store.close()
