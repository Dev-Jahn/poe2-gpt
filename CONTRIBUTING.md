# Contributing

Use English for code, issues, pull requests, and canonical technical documentation. Translated READMEs are welcome; keep their feature and limitation claims aligned with README.md.

## Development environment

Use Python 3.11+ on Linux for the complete test suite. Create a virtual environment, then run:

```bash
python -m pip install -e '.[test]'
python -m pytest -q
python scripts/check_release.py
```

The regular suite uses mocked upstream APIs and synthetic builds. Do not make live game-service calls from CI. Real-engine tests are enabled separately; follow [the engine guide](docs/pob-engine.md). Report skipped tests when describing validation. `requirements.lock.txt` records the Python 3.12 Linux runtime environment; use it as optional constraints, not as a cross-platform lock.

## Changes and review

Open an issue for substantial API or architecture changes. Explain the problem, resulting behavior, tests, and remaining limitations in a pull request. Add meaningful regression coverage for protocol, validation, caching, calculation, or privacy changes. Avoid adding tests that only repeat formatting or trivial implementation details.

Keep raw build payloads, personal character files, account identifiers, session cookies, tokens, and private paths out of issues, fixtures, logs, and PRs. Use synthetic fixtures. Never add an MCP raw import/export endpoint, a model-readable private-file resource, or free-form Lua execution. See [the boundary](docs/pob-boundary.md).

Third-party data is untrusted input. Preserve rate-limit handling and explicit unknown/unsupported states. Pin engine updates to a reviewed commit and archive digest; update compatibility checks and real-engine tests together. Never silently update the engine at startup.

## Repository map

- `src/poe2_companion/`: MCP server, source adapters, models, and isolated worker.
- `src/poe2_companion/lua/`: headless PoB integration.
- `tests/`: offline regression tests and synthetic real-engine cases.
- `scripts/`: packaging checks and pinned runtime installers.
- `docs/`: installation, interfaces, architecture, and maintenance.
- `.github/workflows/`: tests, container checks, and release publication.

The Python module name is retained for compatibility; the distribution, plugin, and repository are named `poe2-gpt`. This project does not require contributors to own a GGG account or disclose their real build.
