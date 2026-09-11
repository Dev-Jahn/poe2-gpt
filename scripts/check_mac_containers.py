"""CI smoke test of the Mac stack's Linux containers, using synthetic data only.

This does not establish that macOS, Colima, Cloudflare or ChatGPT is connected.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from poe2_companion.deployment import render_member_stack


def main():
    env = {**os.environ, "POE2_PUBLIC_HOST": "poe2.example.com", "POE2_CF_TEAM_DOMAIN": "test.cloudflareaccess.com",
           "POE2_CF_AUDIENCE": "a" * 64, "POE2_CF_OWNER_EMAIL": "owner@example.com"}
    command = ["docker", "compose", "--project-name", "poe2-mac-ci", "-f", "deploy/compose.mac.yaml",
               "-f", "deploy/compose.mac-engine.yaml"]
    def run(args, **kwargs):
        return subprocess.run(command + args, check=True, env=env, cwd=ROOT, **kwargs)
    temporary = tempfile.TemporaryDirectory(prefix="poe2-members-ci-")
    try:
        base = json.loads(run(["config", "--format", "json"], capture_output=True, text=True).stdout)
        # Disjoint from production ports and image tags on a running Mac.
        base["services"]["poe2-companion"]["ports"][0]["published"] = "28080"
        for service in base["services"].values():
            if "image" in service:
                service["image"] = service["image"].removesuffix(":local") + ":ci"
        members = [{"id": name, "email": name + "@example.com", "port": port, "enabled": True}
                   for name, port in (("alice", 18082), ("bob", 18083))]
        rendered = Path(temporary.name) / "compose.json"
        stack = render_member_stack(base, members)
        for suffix in ('', '-alice', '-bob'):
            service = stack['services']['poe2-companion' + suffix]
            assert service['environment']['POE2_DECISION_DIR'] == '/workflow-state'
            assert service['environment']['POE2_DECISION_KEY_FILE'] == '/workflow-keys/decision.key'
            mounts = {v['target']: v['source'] for v in service['volumes'] if v['type'] == 'volume'}
            assert mounts['/workflow-state'] == 'workflow-state' + suffix
            assert mounts['/workflow-keys'] == 'workflow-keys' + suffix
        for service in stack["services"].values():
            for port in service.get("ports", []):
                if int(port["published"]) in (18082, 18083):
                    port["published"] = str(int(port["published"]) + 10000)
        rendered.write_text(json.dumps(stack))
        command = ["docker", "compose", "--project-name", "poe2-mac-ci", "-f", str(rendered)]
        run(["build"])
        run(["up", "-d", "--wait", "--wait-timeout", "120"])
        account_ids = {}
        for suffix in ("", "-alice", "-bob"):
            # These are isolated CI volumes. Never bind production account stores
            # to synthetic identities while doing deployment smoke checks.
            result = run(["exec", "-T", "poe2-companion" + suffix, "python", "-c",
                "import httpx,json; from pathlib import Path; "
                "assert not list(Path('/account-state').iterdir()); "
                "assert not list(Path('/account-keys').iterdir()); "
                "assert not list(Path('/account-config').iterdir()); "
                "c=httpx.Client(transport=httpx.HTTPTransport(uds='/account-socket/accounts.sock')); "
                "r=c.post('http://broker/rpc',json={'operation':'register','principal':'a'*64,'payload':{'account_name':'Synthetic#1234'}}); "
                "r.raise_for_status(); print(json.dumps(r.json()))"], capture_output=True, text=True)
            account = json.loads(result.stdout)["account"]
            assert account["verified"] is False
            account_ids[suffix] = account["account_id"]
            run(["exec", "-T", "account-broker" + suffix, "python", "-c",
                "from pathlib import Path; p=Path('/account-keys/master.key'); "
                "assert p.stat().st_uid==10001 and p.stat().st_mode & 0o777==0o600; "
                "assert len(p.read_bytes())==32; assert not Path('/account-config/oauth.json').exists()"])
        assert len(set(account_ids.values())) == 3
        traces = {}
        for suffix in ('', '-alice', '-bob'):
            member = suffix.removeprefix('-') or 'owner'
            result = run(['exec', '-T', 'poe2-companion' + suffix, 'python', '-c',
                "import os,json; from pathlib import Path; "
                "from poe2_companion.workflow_store import DecisionStore; "
                "from poe2_companion.workflow_telemetry import WorkflowTelemetry,BeginTrace; "
                "s=DecisionStore('" + member + "',Path(os.environ['POE2_DECISION_DIR']),Path(os.environ['POE2_DECISION_KEY_FILE'])); "
                "t=WorkflowTelemetry(s).begin('synthetic-workflow-owner',BeginTrace(goal='inspect_build',persist_trace=True)); "
                "print(json.dumps({'trace_id':t.trace_id})); s.close(); "
                "p=Path(os.environ['POE2_DECISION_KEY_FILE']); "
                "assert p.stat().st_uid==10001 and p.stat().st_mode & 0o777==0o600 and len(p.read_bytes())==32; "
                "assert b'synthetic-workflow-owner' not in Path('/workflow-state/decisions.sqlite3').read_bytes()"],
                capture_output=True, text=True)
            traces[suffix] = json.loads(result.stdout)['trace_id']
        run(['restart', 'poe2-companion', 'poe2-companion-alice', 'poe2-companion-bob'])
        run(['up', '-d', '--wait', '--wait-timeout', '120'])
        for suffix, own_trace in traces.items():
            member = suffix.removeprefix('-') or 'owner'
            foreign_trace = next(value for key, value in traces.items() if key != suffix)
            # A fresh process must recover the opted-in record after restart;
            # neither another deployment member nor a new principal can read it.
            check = "\n".join([
                "import os", "from pathlib import Path",
                "from poe2_companion.workflow_store import DecisionStore,WorkflowError",
                "from poe2_companion.workflow_telemetry import WorkflowTelemetry",
                f"s=DecisionStore({member!r},Path(os.environ['POE2_DECISION_DIR']),Path(os.environ['POE2_DECISION_KEY_FILE']))",
                "t=WorkflowTelemetry(s)",
                f"assert t.get('synthetic-workflow-owner',{own_trace!r}).request.goal=='inspect_build'",
                f"for owner,identifier in [('synthetic-workflow-owner',{foreign_trace!r}),('another-principal',{own_trace!r})]:",
                "    try: t.get(owner,identifier)",
                "    except WorkflowError: pass",
                "    else: raise AssertionError('Foreign workflow was readable')",
                "s.close()",
            ])
            run(['exec', '-T', 'poe2-companion' + suffix, 'python', '-c', check])
        for suffix in ("-alice", "-bob"):
            run(["exec", "-T", "poe2-companion" + suffix, "python", "-c",
                "import httpx; c=httpx.Client(transport=httpx.HTTPTransport(uds='/account-socket/accounts.sock')); "
                "r=c.post('http://broker/rpc',json={'operation':'status','principal':'a'*64,'payload':{'account_id':'" + account_ids[""] + "'}}); "
                "assert r.json()=={'status':'not_found'}"])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for port in (28080, 28082, 28083):
            try:
                opener.open(f"http://127.0.0.1:{port}/mcp", timeout=5)
                raise AssertionError("Unauthenticated origin request succeeded")
            except urllib.error.HTTPError as error:
                assert error.code == 403 and json.load(error) == {"error": "access_denied"}
        code = base64.urlsafe_b64encode(zlib.compress((ROOT / "tests/fixtures/engine_synthetic.xml").read_bytes()))
        result = run(["exec", "-T", "character-provider", "python", "-c",
                      "import sys,json; from pathlib import Path; from poe2_companion.pob_io import import_stream; "
                      "b=import_stream(sys.stdin.buffer,Path('/private-builds'),Path('/build-projections')); "
                      "print(json.dumps({'status':'imported','build_id':b}))"], input=code, capture_output=True)
        imported = json.loads(result.stdout)
        assert imported["status"] == "imported"
        build_id = imported["build_id"]
        # Linux-native named volumes keep UID 10001 and 0600 permissions; the
        # worker reads raw files, while MCP has only the safe projection mount.
        run(["exec", "-T", "pob-engine", "python", "-c",
             "from pathlib import Path; import os; p=Path('/private-builds') / '" + build_id + ".pob'; "
             "assert p.stat().st_uid==10001 and p.stat().st_mode & 0o777==0o600; assert p.read_bytes()"])
        run(["exec", "-T", "poe2-companion", "python", "-c",
             "from pathlib import Path; assert not list(Path('/private-builds').iterdir()); "
             "assert (Path('/build-projections') / '" + build_id + ".json').is_file()"])
        container = run(["ps", "-q", "pob-engine"], capture_output=True, text=True).stdout.strip()
        inspect = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
        assert inspect["HostConfig"]["NetworkMode"] == "none"
        assert inspect["HostConfig"]["ReadonlyRootfs"] is True
        assert not inspect["HostConfig"]["PortBindings"]
        imported_ids = {"": build_id}
        for member in members:
            suffix = "-" + member["id"]
            result = run(["exec", "-T", "character-provider" + suffix, "python", "-c",
                          "import sys,json; from pathlib import Path; from poe2_companion.pob_io import import_stream; "
                          "b=import_stream(sys.stdin.buffer,Path('/private-builds'),Path('/build-projections')); "
                          "print(json.dumps({'build_id':b}))"], input=code, capture_output=True)
            imported_ids[suffix] = json.loads(result.stdout)["build_id"]
        for suffix, own_id in imported_ids.items():
            foreign_id = next(value for key, value in imported_ids.items() if key != suffix)
            # Exercise real Unix sockets and the real engine from each isolated MCP container.
            run(["exec", "-T", "poe2-companion" + suffix, "python", "-c",
                 "import httpx; from pathlib import Path; "
                 "assert not list(Path('/character-state').iterdir()); "
                 "p=httpx.Client(transport=httpx.HTTPTransport(uds='/character-socket/characters.sock')); "
                 "assert p.get('http://provider/health').json()=={'status':'ok'}; "
                 "r=p.post('http://provider/refresh_character',json={'account_tag':'Example#1234','character_name':'Synthetic'}); "
                 "assert r.status_code==200 and r.json()['status']=='authentication_required'; "
                 "assert {p.stem for p in Path('/build-projections').glob('*.json')} == {'" + own_id + "'}; "
                 "c=httpx.Client(transport=httpx.HTTPTransport(uds='/engine-socket/pob.sock'),timeout=90); "
                 "r=c.post('http://worker/batch',json={'build_id':'" + own_id + "','scenarios':[]}); "
                 "assert r.status_code==200 and r.json()['baseline']['stats']; "
                 "r=c.post('http://worker/batch',json={'build_id':'" + foreign_id + "','scenarios':[]}); "
                 "assert r.status_code==400 and r.json()=={'code':'engine_invalid_build'}"])
        # A lease in one container must block another, and release after exit.
        holder = subprocess.Popen(command + ["exec", "-T", "pob-engine", "python", "-c",
            "import fcntl,sys; f=open('/engine-coordination/compute.lock','r+'); "
            "fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); sys.stdin.read(1)"],
            env=env, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            assert holder.stdout.readline().strip() == b"locked"
            run(["exec", "-T", "pob-engine-alice", "python", "-c",
                 "import httpx; c=httpx.Client(transport=httpx.HTTPTransport(uds='/engine-socket/pob.sock')); "
                 "r=c.post('http://worker/batch',json={'build_id':'" + imported_ids['-alice'] + "','scenarios':[]}); "
                 "assert r.status_code==400 and r.json()=={'code':'engine_busy'}"])
        finally:
            holder.communicate(input=b"x", timeout=10)
        print("Three-user containers: private imports, cross-user build denial, real calculations, shared compute lease, encrypted workflow restart/isolation and origin auth OK")
    finally:
        # This disposable CI project contains only generated synthetic data.
        run(["down", "--volumes"])
        temporary.cleanup()


if __name__ == "__main__":
    main()
