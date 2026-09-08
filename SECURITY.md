# Security policy

Security fixes target the latest release on `main`. Each experimental MCP instance serves one authenticated owner and has no built-in OAuth authorization provider. The optional [friends deployment](docs/friends.md) separates users by process, private volume and worker socket while verifying each instance's one allowed email. An email allowlist on a shared private-data instance is not a substitute for this isolation. The server operator retains administrative access to all stores.

Do not expose tools backed by private build data without an account-scoped tunnel or a compatible authenticated ingress. Keep the worker socket private and mount raw files only in the worker. See [deployment](docs/deployment.md) and [privacy](docs/privacy.md).

For a vulnerability, use GitHub's **Report a vulnerability** option on this repository's Security tab when it is enabled. If private reporting is unavailable, open a minimal issue asking the maintainer for a private contact channel, without exploit details, credentials, build payloads, or personal data. Do not attach private PoB codes to a public issue.

A report should identify the affected version, impact, and a reproduction using synthetic data. Maintainers should validate privately, fix the issue with a regression test, and publish an advisory after the fix is available. No fixed response-time guarantee is offered.
