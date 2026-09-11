"""Private PoB worker; never registered as an MCP tool or mounted into MCP.

Deploy with network_mode:none and a shared Unix socket, raw store read-only.
Only this process decodes the operator's PoB file. Each request gets a fresh
LuaJIT process; failures discard all private diagnostics.
"""
from __future__ import annotations
import asyncio
from contextlib import contextmanager
import fcntl
import json
import os
import resource
import signal
import tempfile
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .builds import DTO, read_regular_file, BuildOrigin
from .pob_io import MAX_CODE_BYTES, decode_pob, project_pob
from .beast_metadata import MAX_BEAST_METADATA_BYTES, validate_beast_metadata
from .engine_models import ENGINE_COMMIT, ENGINE_DATA_COMMIT, ENGINE_COMPATIBILITY, EngineError, EngineSlot, BuildID, EngineSnapshot, SAFE_ENGINE_ERRORS

MAX_REQUEST = 2 * 1024 * 1024
MAX_RESULT = 16 * 1024 * 1024
from .engine_protocol import WorkerRequest, WorkerResult
from .workflow_metrics import CURRENT, Measurements, measured, count


def limits():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_CPU,(80,80))
    resource.setrlimit(resource.RLIMIT_AS,(3*1024**3,3*1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE,(MAX_RESULT,MAX_RESULT))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))


class PrivateEngine:
    def __init__(self, private_dir: Path, engine_dir: Path, luajit='luajit', timeout=85, lock_file: Path | None = None):
        self.private_dir,self.engine_dir=Path(private_dir),Path(engine_dir)
        self.luajit,self.timeout=luajit,timeout
        self.lock=asyncio.Lock()
        self.lock_file = lock_file
        from .private_inspection import StaticInspector
        self.inspector = StaticInspector(self)

    @contextmanager
    def compute_lease(self):
        """One calculation across isolated workers; the file contains no user data."""
        fd = None
        try:
            if self.lock_file is not None:
                try:
                    fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise EngineError('engine_busy') from None
            yield
        finally:
            if fd is not None:
                os.close(fd)

    def check_version(self):
        try:
            expected={'COMPANION_COMMIT':ENGINE_COMMIT, 'COMPANION_DATA_COMMIT':ENGINE_DATA_COMMIT,
                      'COMPANION_COMPATIBILITY':ENGINE_COMPATIBILITY}
            valid=all(read_regular_file(self.engine_dir/name,100).decode().strip()==value for name,value in expected.items())
        except Exception:
            raise EngineError('engine_version_mismatch') from None
        if not valid:
            raise EngineError('engine_version_mismatch')

    async def calculate(self, request: WorkerRequest) -> WorkerResult:
        self.check_version()
        if self.lock.locked():
            count('queue_rejected')
            raise EngineError('engine_busy')
        async with self.lock:
            with self.compute_lease():
                return await self._calculate(request)

    @measured('worker_execution')
    async def _calculate(self, request: WorkerRequest) -> WorkerResult:
        try:
            code=read_regular_file(self.private_dir/(request.build_id+'.pob'),MAX_CODE_BYTES)
            xml=decode_pob(code)
            projection=project_pob(xml,request.build_id)
            # PoB's build format target is 0_1; the current passive tree is
            # 0_5. These are distinct version fields in GameVersions.lua.
            if projection.summary.target_version != [0,1]:
                raise EngineError('engine_version_mismatch')
            from xml.etree import ElementTree as ET
            root=ET.fromstring(xml)
            tree=root.find('Tree')
            active=int(tree.get('activeSpec','1')) if tree is not None else 1
            trees=projection.trees
            node_ids=next((t.node_ids for t in trees if t.index==active-1),[])
            job: dict={'xml':xml.decode('utf-8-sig'),'expected_node_ids':node_ids,
                 'scenarios':[[c.model_dump(exclude_none=True) for c in s] for s in request.scenarios]}
            from .capabilities import digest
            job['scenario_digest']=digest({'configuration':request.configuration.model_dump(mode='json') if request.configuration else None,
                'combat_scenario':request.combat_scenario.model_dump(mode='json') if request.combat_scenario else None})
            if request.target is not None:
                job['target']=request.target.model_dump(exclude_none=True)
            if request.component_targets:
                job['component_targets']=[t.model_dump(exclude_none=True) for t in request.component_targets]
                job['component_offset']=request.component_offset
                job['component_limit']=request.component_limit
            experiments = ([request.experiment] if request.experiment is not None else []) + [v.request for v in request.variant_jobs]
            for experiment in experiments:
                import hashlib
                if (hashlib.sha256(code).hexdigest()!=experiment.base_snapshot_digest
                        or experiment.engine_data_commit!=ENGINE_DATA_COMMIT
                        or tree is None or tree.findall('Spec')[active-1].get('treeVersion')!=experiment.tree_revision):
                    raise EngineError('engine_invalid_request')
            if request.experiment is not None:
                job['experiment']=request.experiment.model_dump(exclude_none=True)
                job['experiment_items']=request.experiment_items
            if request.variant_jobs:
                job['variant_jobs']=[v.model_dump(exclude_none=True) for v in request.variant_jobs]
            if request.inspection is not None:
                if request.inspection.build_id != request.build_id:
                    raise EngineError('engine_invalid_request')
                job['inspection'] = request.inspection.model_dump(exclude_none=True)
            metadata_path=self.private_dir/(request.build_id+'.beasts.json')
            try:
                metadata_path.lstat()
            except FileNotFoundError:
                metadata=None
            else:
                metadata=read_regular_file(metadata_path,MAX_BEAST_METADATA_BYTES)
            if metadata is not None:
                job['beast_metadata']=validate_beast_metadata(metadata,code)
            if request.configuration is not None:
                job['configuration']=request.configuration.model_dump(exclude_none=True)
            if request.combat_scenario is not None:
                job['combat_scenario']=request.combat_scenario.model_dump(exclude_none=True)
        except EngineError:
            raise
        except Exception:
            raise EngineError('engine_invalid_build') from None
        # Temporary files exist only in the private worker's tmpfs. Neither
        # filenames nor process arguments contain the PoB payload.
        with tempfile.TemporaryDirectory(prefix='pob-job-') as td:
            inp,out=Path(td)/'input.json',Path(td)/'result.json'
            inp.write_text(json.dumps(job,allow_nan=False),encoding='utf-8');inp.chmod(0o600)
            env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),
                 'LUA_PATH':str(self.engine_dir/'runtime/lua/?.lua')+';'+str(self.engine_dir/'runtime/lua/?/init.lua')+';;',
                 'LUA_CPATH':os.environ.get('LUA_CPATH',';;'), 'LANG':'C.UTF-8'}
            process=None
            try:
                with inp.open('rb') as stdin, out.open('wb') as stdout:
                    process=await asyncio.create_subprocess_exec(self.luajit,str(Path(__file__).parent/'lua/calculate.lua'),
                        cwd=self.engine_dir/'src',stdin=stdin,stdout=stdout,stderr=asyncio.subprocess.DEVNULL,
                        env=env,preexec_fn=limits,start_new_session=True)
                    async with asyncio.timeout(self.timeout):
                        await process.wait()
                if process.returncode:
                    raise EngineError('engine_calculation_failed')
                result=WorkerResult.model_validate_json(read_regular_file(out,MAX_RESULT))
                origin_path=self.private_dir/(request.build_id+'.origin.json')
                if origin_path.exists() or origin_path.is_symlink():
                    origin=BuildOrigin.model_validate_json(read_regular_file(origin_path,2048))
                    for snapshot in [result.baseline,*result.results,*[v.snapshot for v in result.experiment_variants if v.snapshot is not None],*[p.snapshot for p in result.components]]:
                        snapshot.origin=origin
                expected_count=(1 if result.experiment_audit and result.experiment_audit.status=='valid_changeset' else 0) if request.experiment else len(request.scenarios)
                if len(result.results)!=expected_count or len(result.experiment_variants)!=len(request.variant_jobs):
                    raise EngineError('engine_protocol_error')
                expected_components=min(request.component_limit,max(0,result.component_total-request.component_offset)) if request.component_targets else 0
                if len(result.components)!=expected_components:
                    raise EngineError('engine_protocol_error')
                return result
            except TimeoutError:
                raise EngineError('engine_timeout') from None
            except EngineError:
                raise
            except asyncio.CancelledError:
                raise
            except Exception:
                raise EngineError('engine_calculation_failed') from None
            finally:
                if process is not None and process.returncode is None:
                    os.killpg(process.pid,signal.SIGKILL)
                    await process.wait()


def worker_app(engine: PrivateEngine):
    async def health(_):
        try:
            engine.check_version()
            return JSONResponse({'engine_commit':ENGINE_COMMIT,'engine_data_commit':ENGINE_DATA_COMMIT,
                                 'engine_compatibility':ENGINE_COMPATIBILITY})
        except Exception:
            return JSONResponse({'code':'engine_version_mismatch'},status_code=503)

    async def batch(request: Request):
        try:
            data=bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data)>MAX_REQUEST:
                    raise EngineError('engine_invalid_request')
            query=WorkerRequest.model_validate_json(data)
            result=await engine.calculate(query)
            return JSONResponse(result.model_dump())
        except Exception as exc:
            code=str(exc) if isinstance(exc,EngineError) and str(exc) in SAFE_ENGINE_ERRORS else 'engine_invalid_request'
            return JSONResponse({'code':code},status_code=400)
    async def static(request: Request):
        from .inspection import InspectionRequest
        from .profiles import ProfileRequest
        from .catalog_models import CatalogRequest, PassiveRouteRequest
        try:
            result: DTO
            data=bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data)>65536:
                    raise EngineError('engine_invalid_request')
            if request.url.path=='/passive-order':
                from .passive_execution import PassiveOrderRequest,order
                order_request=PassiveOrderRequest.model_validate_json(data)
                document,_=await engine.inspector.document(order_request.build_id,catalog=True)
                if document.catalog is None: raise EngineError('engine_protocol_error')
                result=order(document.catalog,order_request)
            elif request.url.path=='/passive-candidates':
                from .passive_candidates import PassiveCandidatesRequest,discover
                candidate_request=PassiveCandidatesRequest.model_validate_json(data)
                document,_=await engine.inspector.document(candidate_request.build_id,catalog=True)
                if document.catalog is None:raise EngineError('engine_protocol_error')
                result=discover(document.catalog,candidate_request)
            elif request.url.path in {'/catalog','/passive-route'}:
                from .catalog import page, route
                query=(CatalogRequest if request.url.path=='/catalog' else PassiveRouteRequest).model_validate_json(data)
                document,_=await engine.inspector.document(query.build_id,catalog=True)
                if document.catalog is None: raise EngineError('engine_protocol_error')
                result=page(document.catalog,query) if isinstance(query,CatalogRequest) else route(document.catalog,query)
            elif request.url.path == '/profile':
                result = await engine.inspector.profile(ProfileRequest.model_validate_json(data))
            else:
                result = await engine.inspector.inspect(InspectionRequest.model_validate_json(data))
            return JSONResponse(result.model_dump(mode='json'))
        except Exception as exc:
            code=str(exc) if isinstance(exc,EngineError) and str(exc) in SAFE_ENGINE_ERRORS else 'engine_invalid_request'
            return JSONResponse({'code':code},status_code=400)
    async def observed(request: Request):
        handler=batch if request.url.path=='/batch' else static
        if request.headers.get('x-poe2-observe')!='1': return await handler(request)
        metrics=Measurements();token=CURRENT.set(metrics)
        try:
            response=await handler(request)
            response.headers['x-poe2-workflow-timing']=json.dumps({'milliseconds':metrics.milliseconds,
                'counts':dict(metrics.counts)},separators=(',',':'),allow_nan=False)
            return response
        finally: CURRENT.reset(token)
    return Starlette(routes=[Route('/health',health),Route('/batch',observed,methods=['POST']),
        Route('/inspect',observed,methods=['POST']),Route('/profile',observed,methods=['POST']),
        Route('/catalog',observed,methods=['POST']),Route('/passive-route',observed,methods=['POST']),
        Route('/passive-order',observed,methods=['POST']),Route('/passive-candidates',observed,methods=['POST'])])


def main():
    import uvicorn
    import sys
    os.umask(0o077)
    engine=PrivateEngine(Path(os.environ['POE2_PRIVATE_DIR']),Path(os.environ['POE2_ENGINE_DIR']),os.environ.get('POE2_LUAJIT','luajit'))
    if os.environ.get('POE2_ENGINE_LOCK_FILE'):
        engine.lock_file = Path(os.environ['POE2_ENGINE_LOCK_FILE'])
    socket=Path(os.environ.get('POE2_ENGINE_SOCKET','/engine-socket/pob.sock'))
    socket.parent.mkdir(exist_ok=True,mode=0o700)
    try:
        uvicorn.run(worker_app(engine),uds=str(socket),access_log=False,log_level='critical')
    except Exception:
        print('engine_worker_start_failed',file=sys.stderr)
        raise SystemExit(1) from None


if __name__=='__main__':
    main()
