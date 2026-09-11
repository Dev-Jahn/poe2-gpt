"""Private-only native loader, bounded cache and process lifecycle."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile
import time
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from .engine_worker import PrivateEngine

from .builds import read_regular_file, bounded_dto, BuildError
from .engine_models import ENGINE_COMMIT, ENGINE_DATA_COMMIT, ENGINE_COMPATIBILITY, EngineError
from .inspection import InspectionPage, InspectionRequest
from .pob_io import MAX_CODE_BYTES, decode_pob, project_pob
from .profiles import BuildProfile, ProfileRequest, StaticDocument

CACHE_BYTES = 32 * 1024 * 1024
CACHE_TTL = 600


class StaticInspector:
    def __init__(self, engine: PrivateEngine) -> None:
        self.engine = engine
        self.cache: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self.cache_bytes = 0
        self.lock = asyncio.Lock()
        self.process_runs = 0

    def source(self, build_id: str) -> tuple[bytes, str]:
        code = read_regular_file(self.engine.private_dir / (build_id + '.pob'), MAX_CODE_BYTES)
        return code, hashlib.sha256(code).hexdigest()

    async def document(self, build_id: str, query: InspectionRequest | None = None, *, catalog: bool = False) -> tuple[StaticDocument, str]:
        self.engine.check_version()
        try:
            code, digest = self.source(build_id)
        except Exception:
            raise EngineError('engine_invalid_build') from None
        selector = query.model_dump(exclude={'offset', 'limit', 'build_id'}, exclude_none=True) if query else None
        key = hashlib.sha256(json.dumps([digest, ENGINE_COMMIT, ENGINE_DATA_COMMIT,
            ENGINE_COMPATIBILITY, 'static-v2', selector, catalog], sort_keys=True).encode()).hexdigest()
        # The owner boundary is the worker's private directory; no global cache.
        # Recheck after acquiring the lock to collapse identical cold requests.
        try:
            async with asyncio.timeout(40):
                async with self.lock:
                    now = time.monotonic()
                    for old_key, (deadline, data) in list(self.cache.items()):
                        if deadline <= now:
                            self.cache.pop(old_key)
                            self.cache_bytes -= len(data)
                    entry = self.cache.get(key)
                    if entry:
                        self.cache.move_to_end(key)
                        return StaticDocument.model_validate_json(entry[1]), digest
                    xml = decode_pob(code)
                    projection = project_pob(xml, build_id)
                    if projection.summary.target_version != [0, 1]:
                        raise EngineError('engine_version_mismatch')
                    job: dict[str, Any] = {'xml': xml.decode('utf-8-sig')}
                    if query:
                        job['inspection'] = query.model_dump(exclude_none=True)
                    if catalog:
                        job['catalog'] = True
                    result = await self.execute(job)
                    encoded = result.model_dump_json().encode()
                    if len(encoded) <= CACHE_BYTES:
                        while self.cache and self.cache_bytes + len(encoded) > CACHE_BYTES:
                            _, (_, old) = self.cache.popitem(last=False)
                            self.cache_bytes -= len(old)
                        self.cache[key] = (time.monotonic() + CACHE_TTL, encoded)
                        self.cache_bytes += len(encoded)
                    return result, digest
        except EngineError:
            raise
        except TimeoutError:
            raise EngineError('engine_timeout') from None
        except asyncio.CancelledError:
            raise
        except Exception:
            raise EngineError('engine_invalid_build') from None

    async def execute(self, job: dict) -> StaticDocument:
        from .engine_worker import limits, MAX_RESULT
        with tempfile.TemporaryDirectory(prefix='pob-static-') as directory:
            source, output = Path(directory) / 'input.json', Path(directory) / 'output.json'
            source.write_text(json.dumps(job, allow_nan=False), encoding='utf-8')
            source.chmod(0o600)
            env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8',
                'LUA_PATH': str(self.engine.engine_dir / 'runtime/lua/?.lua') + ';' + str(self.engine.engine_dir / 'runtime/lua/?/init.lua') + ';;',
                'LUA_CPATH': os.environ.get('LUA_CPATH', ';;')}
            process = None
            try:
                with source.open('rb') as stdin, output.open('wb') as stdout:
                    self.process_runs += 1
                    process = await asyncio.create_subprocess_exec(self.engine.luajit,
                        str(Path(__file__).parent / 'lua/static_inspect.lua'),
                        cwd=self.engine.engine_dir / 'src', stdin=stdin, stdout=stdout,
                        stderr=asyncio.subprocess.DEVNULL, env=env, preexec_fn=limits, start_new_session=True)
                    await process.wait()
                if process.returncode:
                    raise EngineError('engine_invalid_build')
                return StaticDocument.model_validate_json(read_regular_file(output, MAX_RESULT))
            finally:
                if process is not None and process.returncode is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()

    async def inspect(self, request: InspectionRequest) -> InspectionPage:
        document, _ = await self.document(request.build_id, request)
        rows = document.records
        end = request.offset + request.limit
        return InspectionPage(build_id=request.build_id, section=request.section,
            records=rows[request.offset:end], total=len(rows),
            next_offset=end if end < len(rows) else None)

    async def profile(self, request: ProfileRequest) -> BuildProfile:
        document, digest = await self.document(request.build_id)
        changed: Literal['same_content', 'different_content', 'not_requested'] = 'not_requested'
        if request.changed_since_build_id:
            try:
                _, previous = self.source(request.changed_since_build_id)
            except Exception:
                raise EngineError('engine_invalid_build') from None
            changed = 'same_content' if previous == digest else 'different_content'
        end = request.offset + request.limit
        skills = [s for s in document.skills if not request.skill_instance_ids or s.skill_instance_id in request.skill_instance_ids]
        result = BuildProfile(build_id=request.build_id, snapshot_digest=digest,
            engine_commit=ENGINE_COMMIT, engine_data_commit=ENGINE_DATA_COMMIT,
            metadata=document.metadata, skill_instances=skills[request.offset:end],
            total_skill_instances=len(skills), next_offset=end if end < len(skills) else None,
            changed_since=changed)
        while True:
            try: return bounded_dto(result)
            except BuildError:
                if len(result.skill_instances) <= 1: raise
                result.skill_instances.pop()
                result.next_offset = request.offset + len(result.skill_instances)
