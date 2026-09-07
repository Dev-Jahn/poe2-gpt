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
        run(["build"])
        base = json.loads(run(["config", "--format", "json"], capture_output=True, text=True).stdout)
        members = [{"id": name, "email": name + "@example.com", "port": port, "enabled": True}
                   for name, port in (("alice", 18082), ("bob", 18083))]
        rendered = Path(temporary.name) / "compose.json"
        rendered.write_text(json.dumps(render_member_stack(base, members)))
        command = ["docker", "compose", "--project-name", "poe2-mac-ci", "-f", str(rendered)]
        run(["up", "-d", "--wait", "--wait-timeout", "120"])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for port in (18080, 18082, 18083):
            try:
                opener.open(f"http://127.0.0.1:{port}/mcp", timeout=5)
                raise AssertionError("Unauthenticated origin request succeeded")
            except urllib.error.HTTPError as error:
                assert error.code == 403 and json.load(error) == {"error": "access_denied"}
        code = base64.urlsafe_b64encode(zlib.compress((ROOT / "tests/fixtures/engine_synthetic.xml").read_bytes()))
        result = run(["run", "--rm", "-T", "--no-deps", "pob-import", "import", "--stdin",
                      "--private-dir", "/private-builds", "--projection-dir", "/build-projections"], input=code, capture_output=True)
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
            result = run(["run", "--rm", "-T", "--no-deps", "pob-import" + suffix, "import", "--stdin",
                          "--private-dir", "/private-builds", "--projection-dir", "/build-projections"], input=code, capture_output=True)
            imported_ids[suffix] = json.loads(result.stdout)["build_id"]
        for suffix, own_id in imported_ids.items():
            foreign_id = next(value for key, value in imported_ids.items() if key != suffix)
            # Exercise real Unix sockets and the real engine from each isolated MCP container.
            run(["exec", "-T", "poe2-companion" + suffix, "python", "-c",
                 "import httpx; from pathlib import Path; "
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
        print("Three-user containers: private imports, cross-user build denial, real calculations, shared compute lease and origin auth OK")
    finally:
        # This disposable CI project contains only generated synthetic data.
        run(["down", "--volumes"])
        temporary.cleanup()


if __name__ == "__main__":
    main()
