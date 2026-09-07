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
