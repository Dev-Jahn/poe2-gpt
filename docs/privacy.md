# Data handling

This repository contains software, not a hosted service. A deployment operator is responsible for its endpoint, authentication, backups, retention, and access logs.

The optional Cloudflare deployment sends MCP traffic through Cloudflare's TLS
termination and Access authentication. Cloudflare processes login identity and
the bounded MCP requests/responses; raw PoB contents are excluded from MCP traffic. Origin authentication strips Access assertions, authorization headers and
cookies before dispatching to MCP and does not log them. Operator email and
tunnel credentials belong in local deployment files, not the public repository.

Scout receives league/category requests and the server's network address and User-Agent. GGG receives trade metadata/search/fetch requests and the server's network address and User-Agent. The client sends no GGG account cookie. Raw builds are not sent to these providers.

Raw PoB files are fetched by a separate private ingestion service and retained in its private store, readable by the network-isolated calculation worker. ChatGPT receives selected build statistics, identifiers, candidate summaries, and calculation statuses. These summaries can still reveal a build. Review ChatGPT's own data settings separately; this server does not control conversation retention.

Scout snapshots are stored in a local SQLite cache. Retained trade queries are in process memory and expire after ten minutes. Imported files and projections remain until the operator deletes them. Worker request files are temporary and cleaned up. No analytics or telemetry endpoint is implemented in the project.

In the [friends deployment](friends.md), only the public Scout cache is shared.
Each person's build files, projections, worker socket and in-memory trade state
belong to a separate instance. Membership and email mappings remain in local
operator files. Revocation removes that person's containers but retains private
volumes until the operator backs up or deletes them. The operator can read all
stores administratively; this service isolation does not hide data from its host.

Do not log request bodies, imported files, private paths, or arbitrary worker output. Restrict backups and filesystem permissions. To remove a build, stop access as appropriate and delete its raw file and corresponding projection using the operator's own filesystem tools. Do not expose those operations as model tools.

This document describes repository behavior, not a legal policy for a future public service. A public operator must publish their own actual retention, contact, and authorization practices before accepting other users' data.

The optional [account broker](accounts.md) stores per-user account labels and
verified profile identity persistently. Configured GGG OAuth sends authorization
codes, client credentials and token requests directly from that private broker;
MCP receives only bounded status projections. Cloudflare terminates the account
UI's HTTPS traffic, including short-lived OAuth callback code/state parameters.
Origin access logs are disabled; deployment operators must separately review
Cloudflare logging and retention. OAuth grants are encrypted at rest with a
per-member key mounted only in the broker. No GGG website cookies are collected.
Local disconnect deletes current credentials and cancels handoffs, but historical
backups and the upstream application's grant require separate handling. Handoff
receipts contain account/listing IDs and quoted prices, capped at 256 / 24 hours;
they neither execute nor observe an in-game action.

The two character flows are public Ninja account/name lookup and original `.txt`
attachments in ChatGPT. Ninja receives account/name requests and, for explicitly
requested refresh, the matching per-user session cookie configured by the
operator. Attachment bytes are downloaded directly from an approved host into
the private service. ChatGPT supplies a temporary download URL and file ID; the
plugin does not read the content into model context. ChatGPT may independently
process or retain attached files; that host behavior is outside this server.

Importer sockets, deduplication records, cooldowns and optional Ninja credentials
are separate per user. Original builds are limited to 500 / 128 MiB per store;
limits refuse new imports rather than evict data. The raw store is not shared
with other providers. Do not collect HTTP client debug logs or signed URLs.
