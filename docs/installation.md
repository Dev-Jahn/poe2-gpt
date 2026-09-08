# Installation and ChatGPT connection

Install from a reviewed release tag or clone this repository. There is no dependency on an OpenAI model API, and no OpenAI API key is required by this server. Do not assume a PyPI package or container image exists until its release workflow has succeeded.

## Shared homelab server

Start `docker compose up -d --build`, or run:

```bash
.venv/bin/python -m poe2_companion.server --transport streamable-http
```

Use the `/mcp` endpoint on loopback port 8000. For a Mac mini behind an inbound firewall, follow [Mac mini + Cloudflare](mac-mini-cloudflare.md): its separate Compose stack uses port 18080 and delegates OAuth to Cloudflare Access, while validating assertions at the origin. An account-scoped [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) is another deployment option. A private-data server needs an account boundary or a ChatGPT-compatible authenticated HTTPS ingress. The repository does not operate a shared hosted service or its own OAuth authorization server.

In ChatGPT, enable Developer mode under Settings → Security and login. In Plugins, select **+**, enter the name and description, then choose the tunnel or your HTTPS `/mcp` URL. Review the discovered tools and start a new conversation. Refresh the connection and start a new conversation after tool changes. Availability depends on account/workspace policy. [Official connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt).

Run the [acceptance prompts](evaluation.md) after connection. First test prices and trade metadata, then enable imported-build tools. Never test with raw PoB content pasted into ChatGPT.

## Updating an existing ChatGPT connection

Keep the existing connection and its member-specific URL. Redeploying the server and refreshing ChatGPT's stored tool metadata are separate steps.

| Change | Required action |
|---|---|
| Prices, bundled game data, or calculation fixes with unchanged tool metadata | Redeploy the server; existing tools use the updated implementation |
| Tool additions/removals, descriptions, input/output schemas, annotations, auth, or UI resources | Redeploy, open **Plugins → POE2 → Refresh**, review the discovered tools, then start a new conversation |
| Reviewed public-directory plugin metadata | Scan the server and submit/publish the updated metadata version |

Do not delete and recreate a developer-mode connection as the normal update procedure. Opening a new conversation before refreshing may still expose the previous tool inventory. The server cannot make a tool callable if it is absent from the host's discovered metadata. This follows the [official metadata refresh workflow](https://developers.openai.com/plugins/deploy/connect-chatgpt).

For a deployment with character ingestion enabled, verify that `get_character`, `list_account_characters`, `refresh_character`, and `import_pob_attachment` appear and are enabled in ChatGPT. Release 0.8 also adds `search_game_terms`. If the server's `tools/list` includes them but ChatGPT does not, refresh that connection. If the live server omits them, check its deployment configuration first. Check each separately created guest connection after a metadata update.

## Version labels

From 0.9.0, MCP `initialize.serverInfo.version`, `/healthz.version`, and
`get_pob_engine_status.server_version` report the project release. Earlier
versions accidentally advertised the Python MCP SDK version during initialization.
The release check keeps the runtime, Python package, and plugin manifest versions
equal. The engine source/data pins are reported separately.

ChatGPT's installed plugin version is separate metadata. A developer-mode
connection created from a URL does not read this Git repository's manifest.
The server cannot directly edit ChatGPT's plugin record, and the official
connection documentation does not promise that its displayed version follows
`serverInfo.version`. Refresh the existing connection after metadata changes;
if the UI still shows `1.0.0`, use the engine-status tool to check the actual
deployed release. Do not recreate the connection just to change that label.

## Local plugin hosts

Install the Python package in the host environment. The bundled `.mcp.json` invokes `poe2-gpt` from PATH over STDIO. If needed, run the following with your virtual-environment Python to bind this checkout to that interpreter:

```bash
.venv/bin/python scripts/configure_mcp.py
```

This edits only this checkout's `.mcp.json`; do not commit your machine's absolute path. A Git-installed plugin copy uses its own bundled config, so keep `poe2-gpt` available on the host PATH or configure that host's MCP command separately.

The repository's `.agents/plugins/marketplace.json` points to the root plugin in Git. Hosts supporting repository marketplaces can discover it when this repository is open. Review and install it through their Plugins Directory. This is separate from the universal public directory. [Marketplace and manifest specification](https://developers.openai.com/plugins/build/plugins).

For a host that accepts MCP servers directly, use command `/absolute/path/to/.venv/bin/python` with arguments `-m poe2_companion.server --transport stdio`. STDIO is a local process connection; it does not sync a server to ChatGPT web.

## Registered remote plugin and directory publication

After the MCP connection works, a registered remote plugin may reference the actual connection in `.app.json`. No placeholder connection ID is shipped. Keep any account-specific mapping local. Publishing to the public ChatGPT directory requires a reachable production HTTPS endpoint, completed metadata/authentication checks, and OpenAI review; a GitHub release does not perform that submission. See [submission requirements](https://developers.openai.com/plugins/deploy/submission) and [evaluation cases](evaluation.md).
