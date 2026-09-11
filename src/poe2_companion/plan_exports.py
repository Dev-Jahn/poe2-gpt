"""Owner-bound downloadable plan artifacts with independently checked bytes."""
import hashlib,re,secrets,time
from typing import Annotated,Literal
from pydantic import Field
from starlette.requests import Request
from starlette.responses import Response
from .access import Principal
from .builds import DTO
from .capabilities import canonical,digest
from .execution_plans import ExecutionID,ExecutionDocument
from .profiles import Digest
from .workflow_store import DecisionStore,WorkflowError

ExportID=Annotated[str,Field(pattern=r'^export_[0-9a-f]{32}$')]


class ExportRequest(DTO):
    execution_id: ExecutionID
    format: Literal['json','markdown'] = 'markdown'
    persist_export: bool = False


class ExportReference(DTO):
    export_id: ExportID


class PlanExport(DTO):
    export_id: ExportID
    execution_id: ExecutionID
    source_artifact_digest: Digest
    content_sha256: Digest
    filename: Annotated[str,Field(pattern=r'^poe2-plan-[0-9a-f]{32}\.(json|md)$')]
    media_type: Literal['application/json','text/markdown']
    content: Annotated[str,Field(max_length=480000)]
    expires_at_epoch: int


class ExportResult(DTO):
    export_id: ExportID
    filename: str
    download_url: str
    source_artifact_digest: Digest
    content_sha256: Digest
    byte_length: int
    expires_at_epoch: int
    owner_authentication_required: Literal[True] = True
    stored_bytes_verified: Literal[True] = True
    game_actions_performed: Literal[False] = False


def markdown(value: ExecutionDocument) -> str:
    def cell(text):
        return str(text).replace('\\','\\\\').replace('|','\\|').replace('[','\\[').replace(']','\\]').replace('<','&lt;').replace('>','&gt;').replace('`','\\`').replace('\n',' ')
    lines=['# PoE2 실행 계획','',f'계획 식별 해시: `{value.artifact_digest}`','',
        '이 파일은 저장된 계획입니다. 게임 적용이나 현재 캐릭터 상태의 확인이 아닙니다.','',
        '| 단계 | 할 일 | 지금 실행 가능 |','|---|---|---|']
    for step in value.steps:lines.append(f'| {step.index+1} | {cell(step.instruction)} | '+('예' if step.executable_now else '아니오')+' |')
    lines+=['','## 중단·확인 조건','']
    lines.extend('- '+cell(s) for s in [*value.blocking_reasons,*value.risk_notes])
    lines+=['','## 동일 계획의 기계 판독 원본','', '```json',canonical(value.model_dump(mode='json')),'```','']
    return '\n'.join(lines)


def create(request: ExportRequest,store: DecisionStore,owner: str,public_base: str | None,path: str) -> ExportResult:
    if public_base is None:raise WorkflowError('artifact_download_public_origin_unconfigured')
    source=store.get_artifact(owner,'execution_plan',request.execution_id,ExecutionDocument)
    if digest(source.model_dump(mode='json',exclude={'artifact_digest'}))!=source.artifact_digest:
        raise WorkflowError('artifact_content_digest_mismatch')
    content=canonical(source.model_dump(mode='json'))+'\n' if request.format=='json' else markdown(source)
    encoded=content.encode();identifier='export_'+secrets.token_hex(16)
    if len(encoded)>480000:raise WorkflowError('artifact_export_too_large_use_pages')
    value=PlanExport(export_id=identifier,execution_id=request.execution_id,source_artifact_digest=source.artifact_digest,
        content_sha256=hashlib.sha256(encoded).hexdigest(),filename='poe2-plan-'+identifier[7:]+('.json' if request.format=='json' else '.md'),
        media_type='application/json' if request.format=='json' else 'text/markdown',content=content,
        expires_at_epoch=min(source.expires_at_epoch,int(time.time())+(30*86400 if request.persist_export else 3600)))
    store.save_artifact(owner,'plan_export',identifier,value,value.expires_at_epoch,request.persist_export)
    stored=store.get_artifact(owner,'plan_export',identifier,PlanExport)
    if stored.content_sha256!=hashlib.sha256(stored.content.encode()).hexdigest() or stored.content!=content:
        raise WorkflowError('artifact_content_digest_mismatch')
    return ExportResult(export_id=identifier,filename=value.filename,download_url=public_base+path+'/'+identifier,
        source_artifact_digest=value.source_artifact_digest,content_sha256=value.content_sha256,byte_length=len(encoded),
        expires_at_epoch=value.expires_at_epoch)


async def download(request: Request,store: DecisionStore) -> Response:
    headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'"}
    principal=request.scope.get('state',{}).get('principal')
    if not isinstance(principal,Principal):return Response(status_code=403,headers=headers)
    identifier=request.path_params.get('export_id','')
    if not re.fullmatch(r'export_[0-9a-f]{32}',identifier):return Response(status_code=404,headers=headers)
    try:
        value=store.get_artifact(principal.issuer+'\0'+principal.subject,'plan_export',identifier,PlanExport)
        body=value.content.encode()
        if hashlib.sha256(body).hexdigest()!=value.content_sha256:raise WorkflowError('artifact_content_digest_mismatch')
    except (WorkflowError,ValueError):return Response(status_code=404,headers=headers)
    headers.update({'Content-Disposition':'attachment; filename="'+value.filename+'"','Content-Length':str(len(body)),
        'X-Content-SHA256':value.content_sha256})
    return Response(content=b'' if request.method=='HEAD' else body,media_type=value.media_type,headers=headers)
