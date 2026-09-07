"""Operator-only Mac deployment. No remote administration or model tools."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = Path.home() / ".config" / "poe2-gpt"
PROFILE = "poe2-gpt"
CONTEXT = "colima-poe2-gpt"
LABELS = {"colima": "ai.poe2-gpt.colima", "tunnel": "ai.poe2-gpt.tunnel"}


def write_private(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Refusing to write through a symlink")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as file:
        os.fchmod(file.fileno(), 0o600)
        file.write(data)


def process_env():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("POE2_", "COMPOSE_")) and k not in
           {"DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"}}
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    return env


def binary(name: str) -> str:
    result = shutil.which(name, path=process_env()["PATH"])
    if not result:
        raise ValueError(f"Install {name} first; see docs/mac-mini-cloudflare.md")
    return result


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, env=process_env(), **kwargs)


def config():
    return json.loads((STATE / "deployment.json").read_text())


def compose(settings):
    command = [binary("docker"), "--context", CONTEXT, "compose", "--project-name", PROFILE,
               "--env-file", str(STATE / "deployment.env"), "-f", str(ROOT / "deploy/compose.mac.yaml")]
    if settings["engine"]:
        command += ["-f", str(ROOT / "deploy/compose.mac-engine.yaml")]
    return command


def colima_command(foreground=False):
    command = [binary("colima"), "start", PROFILE, "--activate=false", "--vm-type", "vz",
               "--cpus", "4", "--memory", "8", "--disk", "64"]
    if foreground:
        command += ["--foreground"]
    return command


def agent_spec(kind):
    if kind == "colima":
        args = colima_command(foreground=True)
    else:
        args = [binary("cloudflared"), "tunnel", "--no-autoupdate", "--metrics", "127.0.0.1:18081",
                "run", "--token-file", str(STATE / "tunnel-token")]
    return {"Label": LABELS[kind], "ProgramArguments": args, "RunAtLoad": True,
            "KeepAlive": True, "ThrottleInterval": 30,
            "EnvironmentVariables": {"PATH": process_env()["PATH"]},
            "StandardOutPath": str(STATE / (kind + ".log")),
            "StandardErrorPath": str(STATE / (kind + ".log"))}


def unload_agent(kind):
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABELS[kind]}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def install_agent(kind):
    spec = agent_spec(kind)
    path = Path.home() / "Library" / "LaunchAgents" / (LABELS[kind] + ".plist")
    if path.exists():
        previous = plistlib.loads(path.read_bytes())
        if previous.get("Label") != LABELS[kind]:
            raise ValueError("Existing LaunchAgent does not belong to this deployment")
    unload_agent(kind)
    write_private(path, plistlib.dumps(spec))
    run(["launchctl", "bootstrap", f"gui/{os.getuid()}", path])


def set_token():
    token = getpass.getpass("Cloudflare tunnel token (hidden; paste the token only): ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_+/=-]{40,8192}", token):
        raise ValueError("Invalid tunnel token format")
    write_private(STATE / "tunnel-token", token.encode())


def configure(args):
    if (STATE / "deployment.json").exists():
        raise ValueError("Deployment already configured. Edit the private deployment.env/JSON locally; use set-token to rotate credentials")
    hostname = args.hostname or input("Public hostname (e.g. poe2.example.com): ").strip()
    team = input("Cloudflare team hostname (your-team.cloudflareaccess.com): ").strip()
    audience = input("Access application AUD tag: ").strip()
    email = input("Only allowed owner email: ").strip()
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", hostname):
        raise ValueError("Use a lowercase public hostname without a scheme or path")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com", team):
        raise ValueError("Invalid Cloudflare team hostname")
    if not re.fullmatch(r"[a-f0-9]{64}", audience):
        raise ValueError("Invalid AUD tag")
    # dotenv is an output format here; disallow interpolation and quoting syntax.
    if len(email) > 254 or not re.fullmatch(r"[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", email):
        raise ValueError("Use one plain email address")
    set_token()
    values = {"POE2_PUBLIC_HOST": hostname, "POE2_CF_TEAM_DOMAIN": team,
              "POE2_CF_AUDIENCE": audience, "POE2_CF_OWNER_EMAIL": email}
    write_private(STATE / "deployment.env", "".join(f"{k}={v}\n" for k, v in values.items()).encode())
    write_private(STATE / "deployment.json", json.dumps({"engine": args.engine}).encode())
    print("Configured. Set the tunnel origin to http://localhost:18080 and enable Access Managed OAuth before starting.")


def status(settings):
    run(compose(settings) + ["ps"])
    for kind, label in LABELS.items():
        result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"], capture_output=True)
        print(f"{kind} login service: {'loaded' if result.returncode == 0 else 'not loaded'}")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open("http://127.0.0.1:18080/mcp", timeout=5).close()
        print("Origin auth check: FAILED (unexpected unauthenticated success)")
        return 1
    except urllib.error.HTTPError as error:
        good = error.code == 403 and error.read(1024) == b'{"error":"access_denied"}'
        print("Origin auth check: " + ("expected 403" if good else "FAILED"))
        return 0 if good else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("configure")
    setup.add_argument("--hostname")
    setup.add_argument("--engine", action="store_true", help="Enable private PoB calculations and saved build summaries")
    for name in ("start", "status", "install-login", "stop", "set-token"):
        sub.add_parser(name)
    load = sub.add_parser("import-build", help="Operator terminal only; never run through model tools")
    load.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != "Darwin":
        parser.error("This deployment helper runs on macOS")
    try:
        if args.command == "configure":
            configure(args)
            return
        settings = config()
        if args.command == "start":
            binary("cloudflared")
            if not (STATE / "tunnel-token").is_file():
                raise ValueError("Run set-token first")
            run(colima_command())
            run(compose(settings) + ["up", "-d", "--build", "--wait", "--wait-timeout", "120"])
            install_agent("tunnel")
            print("Started. Run install-login once to restore the VM after macOS login.")
        elif args.command == "install-login":
            # A foreground supervisor must own Colima; only this dedicated profile stops.
            unload_agent("colima")
            run([binary("colima"), "stop", PROFILE])
            install_agent("colima")
            install_agent("tunnel")
            print("Login services installed. The dedicated VM restarts now; containers recover with Docker restart policies.")
        elif args.command == "stop":
            unload_agent("tunnel")
            unload_agent("colima")
            run([binary("colima"), "stop", PROFILE])
            print("Stopped for this login session. Remove the two poe2-gpt LaunchAgent files to disable future login startup.")
        elif args.command == "set-token":
            set_token()
            install_agent("tunnel")
            print("Tunnel credential updated and tunnel restarted.")
        elif args.command == "status":
            sys.exit(status(settings))
        elif args.command == "import-build":
            if not settings["engine"]:
                raise ValueError("Enable engine in deployment.json and run start first")
            if args.input.is_symlink() or not args.input.is_file() or args.input.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("Input must be a regular PoB file of at most 2 MiB")
            with args.input.open("rb") as source:
                run(compose(settings) + ["run", "--rm", "-T", "--no-deps", "pob-import", "import", "--stdin",
                    "--private-dir", "/private-builds", "--projection-dir", "/build-projections"], stdin=source)
    except (ValueError, OSError, subprocess.CalledProcessError, urllib.error.URLError) as error:
        # Never print subprocess arguments, token contents or PoB input on failure.
        if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError):
            print(str(error), file=sys.stderr)
        else:
            print("Deployment operation failed. Check local configuration and service status; keep secrets and raw builds out of chat.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
