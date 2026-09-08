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

from .builds import DTO, read_regular_file
from .pob_io import MAX_CODE_BYTES, decode_pob, project_pob
from .engine_models import ENGINE_COMMIT, ENGINE_DATA_COMMIT, ENGINE_COMPATIBILITY, EngineError, EngineSlot, BuildID, EngineSnapshot, SAFE_ENGINE_ERRORS

MAX_REQUEST = 2 * 1024 * 1024
MAX_RESULT = 512 * 1024
from .engine_protocol import WorkerRequest, WorkerResult


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
            raise EngineError('engine_busy')
        async with self.lock:
            with self.compute_lease():
                return await self._calculate(request)

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
            job={'xml':xml.decode('utf-8-sig'),'expected_node_ids':node_ids,
                 'scenarios':[[c.model_dump(exclude_none=True) for c in s] for s in request.scenarios]}
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
                if len(result.results)!=len(request.scenarios):
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
    return Starlette(routes=[Route('/health',health),Route('/batch',batch,methods=['POST'])])


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
