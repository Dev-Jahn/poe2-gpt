"""CI smoke test of the Mac stack's Linux containers, using synthetic data only.

This does not establish that macOS, Colima, Cloudflare or ChatGPT is connected.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = {**os.environ, "POE2_PUBLIC_HOST": "poe2.example.com", "POE2_CF_TEAM_DOMAIN": "test.cloudflareaccess.com",
           "POE2_CF_AUDIENCE": "a" * 64, "POE2_CF_OWNER_EMAIL": "owner@example.com"}
    command = ["docker", "compose", "--project-name", "poe2-mac-ci", "-f", "deploy/compose.mac.yaml",
               "-f", "deploy/compose.mac-engine.yaml"]
    def run(args, **kwargs):
        return subprocess.run(command + args, check=True, env=env, cwd=ROOT, **kwargs)
    try:
        run(["up", "-d", "--build", "--wait", "--wait-timeout", "120"])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            opener.open("http://127.0.0.1:18080/mcp", timeout=5)
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
        print("Mac Compose containers: auth denial, private import, projection isolation and worker limits OK")
    finally:
        # This disposable CI project contains only generated synthetic data.
        run(["down", "--volumes"])


if __name__ == "__main__":
    main()
