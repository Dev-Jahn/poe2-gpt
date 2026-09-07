# Data handling

This repository contains software, not a hosted service. A deployment operator is responsible for its endpoint, authentication, backups, retention, and access logs.

The optional Cloudflare deployment sends MCP traffic through Cloudflare's TLS
termination and Access authentication. Cloudflare processes login identity and
the bounded MCP requests/responses; raw PoB data remains in the private worker
store. Origin authentication strips Access assertions, authorization headers and
cookies before dispatching to MCP and does not log them. Operator email and
tunnel credentials belong in local deployment files, not the public repository.

Scout receives league/category requests and the server's network address and User-Agent. GGG receives trade metadata/search/fetch requests and the server's network address and User-Agent. The client sends no GGG account cookie. Raw builds are not sent to these providers.

Raw PoB files remain in the operator's private store and optional network-isolated calculation worker. ChatGPT receives selected build statistics, identifiers, candidate summaries, and calculation statuses. These summaries can still reveal a build. Review ChatGPT's own data settings separately; this server does not control conversation retention.

Scout snapshots are stored in a local SQLite cache. Retained trade queries are in process memory and expire after ten minutes. Imported files and projections remain until the operator deletes them. Worker request files are temporary and cleaned up. No analytics or telemetry endpoint is implemented in the project.

Do not log request bodies, imported files, private paths, or arbitrary worker output. Restrict backups and filesystem permissions. To remove a build, stop access as appropriate and delete its raw file and corresponding projection using the operator's own filesystem tools. Do not expose those operations as model tools.

This document describes repository behavior, not a legal policy for a future public service. A public operator must publish their own actual retention, contact, and authorization practices before accepting other users' data.
