# Homelab deployment

The default Compose service binds `127.0.0.1:8000` and persists Scout's SQLite cache. Use a tunnel for personal access. For HTTPS ingress, pass `--allowed-host your.actual.hostname` to the MCP command and preserve streaming HTTP and the `/mcp` path. Host validation is not authentication. Never use wildcard host allowances as an authentication substitute.

## Optional services

| Capability | Configuration |
|---|---|
| Currency and trade | `compose.yaml` |
| Saved build summaries | Add `compose.builds.yaml`; set `POE2_HOST_PROJECTION_DIR` |
| Imported equipment datasets | Add `compose.equipment.yaml`; set `POE2_HOST_EQUIPMENT_DIR` |
| Real PoB calculations | Add `compose.engine.yaml`; set `POE2_HOST_PRIVATE_DIR` |

Use absolute host paths. The files must already exist; Compose will not create a missing private bind source.

```bash
export POE2_HOST_PRIVATE_DIR=/srv/poe2/private
# Run the external import workflow first, then grant the worker read access.
docker compose -f compose.yaml -f compose.engine.yaml up -d --build
```

Both containers use UID/GID 10001. Import writes directories as 0700 and files as 0600. Run imports with an appropriate operator identity or grant the worker narrowly scoped directory traversal and file-read ACLs after every import. Do not fix permissions by mounting the private directory into MCP or making it world-readable. The worker socket volume is also owned by UID 10001.

The worker is read-only, has no network or exposed TCP port, drops capabilities, and uses a private tmpfs. MCP talks to it through a dedicated Unix socket. The worker retains upstream licenses in its image. Build the engine image on a Linux host with enough disk and memory; source extraction is hundreds of megabytes and calculation processes have a 3 GiB address-space cap.

## Environment

| Variable | Purpose |
|---|---|
| `POE2_USER_AGENT` | Identify this deployment and an appropriate operator contact to upstream services |
| `POE2_CACHE_PATH` | SQLite cache location; defaults under the service user's home |
| `POE2_TRADE_ENABLED` | `1` by default; set `0` to disable direct trade tools |
| `POE2_BUILD_PROJECTION_DIR` | MCP-readable summaries only |
| `POE2_EQUIPMENT_PROJECTION_DIR` | MCP-readable typed equipment snapshots |
| `POE2_ENGINE_SOCKET` | Private worker Unix-socket path |
| `POE2_PRIVATE_DIR` | Worker-only raw store |
| `POE2_ENGINE_DIR` / `POE2_LUAJIT` | Worker-only pinned runtime locations |

## Operation and updates

Back up the private store separately with restricted access; rebuild the cache when needed. Raw data deletion is operator-managed. Do not enable HTTP request-body logging or collect worker temporary files. The public code repository is not a backup location for builds.

Before upgrading, read the changelog and pin a release tag or image digest. Stop and recreate services after pulling the reviewed change. Do not run automatic engine updates. If trade returns a challenge or authentication response, investigate normal access from the operator's environment before restarting; do not rotate proxies or bypass the challenge.

Verify `/health` on the worker through its private socket, the MCP tool list through MCP Inspector, and then the [ChatGPT acceptance cases](evaluation.md). Confirm file ACLs, worker isolation, and actual Unix-socket transport on the homelab. These deployment properties cannot be established by a unit-test-only pass.

This is a single-user deployment. Public multi-user hosting requires per-user authorization, isolated stores and caches where appropriate, quotas, and a privacy policy for the actual service operator.
