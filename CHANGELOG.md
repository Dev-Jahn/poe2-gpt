# Changelog

## 0.5.0

- Cloudflare Access Managed OAuth deployment with origin-side JWT signature, issuer, audience, expiry and single-owner checks.
- Mac mini deployment through a dedicated Colima VM and Cloudflare Tunnel, with isolated login services and private token-file configuration.
- Native ARM64 and amd64 real-engine CI, plus container tests for authentication and raw/projection volume isolation.
- Linux-native private build volumes and a bounded operator-only import pipe; no raw PoB tool input/output was added.
- Multi-architecture release images and localized links to the new deployment guide.

Actual Mac login/reboot behavior and the Cloudflare-to-ChatGPT OAuth connection require deployment acceptance testing.

## 0.4.0

Initial public source release, consolidating the earlier private prototype.

- Scout currency prices, league/category discovery, basket quotes, caching, and bounded retry behavior.
- Experimental official trade-site equipment filtering, stat discovery, and paginated retained search results.
- Private external PoB import/export, safe build projections, and optional equipment datasets.
- Pinned PoE2 PoB worker, equipment requirements, candidate comparisons, and budget optimization.
- Standard plugin manifest and marketplace metadata, English technical documentation, five README locales, and CI/release workflows.

This version does not include a hosted MCP service, character-name lookup, a reviewed public ChatGPT listing, or built-in multi-user authentication.
