# Architecture and extension points

```mermaid
flowchart TD
    C["ChatGPT"] <--> M["Typed MCP tools"]
    M <--> S["Scout and trade adapters"]
    M <--> P["Safe projections"]
    M <-->|"Private Unix socket"| W["PoB worker"]
    M <-->|"Identifiers or file reference"| O["Private character provider"]
    O <--> N["Ninja and attachment host"]
    O --> R["Private raw store"]
    O --> P
    R --> W
```

The model-facing process owns typed tool routing, market caches, retained trade searches, and bounded response serialization. The worker owns raw-file decoding and PoB execution. Imports happen outside the model process. Both processes trust validated identifiers and closed data models, not arbitrary file paths, scripts, or upstream text.

`scout.py` normalizes source prices and currencies. `trade.py` validates current metadata, throttles requests, retains listings, and produces safe views. `equipment.py` implements the explicit item-stat model. `engine.py` prepares bounded PoB scenarios and calls the private protocol. `engine_worker.py` executes the Lua integration in `lua/calculate.lua`. `characters.py` defines safe character/file-reference tools; `character_provider.py` fetches and imports outside MCP. `builds.py` and `pob_io.py` implement projections and internal file I/O.

## Extension rules

The character provider resolves account/league/name identity, discovers current Ninja snapshot versions, and privately ingests exports or host-supplied attachment URLs. Refresh uses a matching per-user Ninja session and persistent cooldown. MCP sees only typed projections and build IDs. See [characters](characters.md).

Add metric support by updating closed schemas, engine extraction, compatibility rules, and meaningful synthetic tests together. Maintain explicit unknown values and configuration scope. Do not change a saved summary into a recalculated result without changing its contract.

A multi-user service needs user authorization on every private identifier, isolated storage, quotas, and authenticated MCP discovery. The current opaque IDs do not replace access control. Keep these changes separate from game API authentication.

The public interfaces should remain bounded and deterministic. Long jobs may eventually require asynchronous job handles; do not extend limits indefinitely or stream arbitrary engine logs into model context.
