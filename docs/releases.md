# CI and release process

Pull requests and pushes to `main` run Python 3.11/3.12 tests, package and documentation checks, wheel/source builds, Compose validation, and an MCP image build. A separate Linux container job installs the actual pinned PoB engine and Lua runtime, runs the test suite without external network access, and fails if any test skips. Ordinary Python jobs intentionally skip optional real-engine cases.

GitHub Actions are pinned to commit SHAs. Dependabot proposes action, Python, and Docker updates. Review dependency changes and refresh the optional Python 3.12 constraints file in a clean supported environment. Engine source updates require a separate reviewed commit/digest change and real-engine compatibility validation.

## Release a version

1. Update `pyproject.toml`, the plugin manifest, user-agent version strings, the changelog, and all README versions together.
2. Merge reviewed changes after CI succeeds. Run the private deployment acceptance cases when a change affects integration.
3. Create and push a version tag matching the package, for example `v0.4.0`.
4. The release workflow reruns CI, publishes a wheel, source distribution, complete plugin ZIP and SHA-256 checksums as GitHub release assets, and pushes versioned Linux amd64 images to GHCR.
5. Inspect the workflow and release assets. Confirm each GHCR package is public before advertising anonymous pulls; package visibility can require a one-time repository-owner setting.

Images are named `ghcr.io/dev-jahn/poe2-gpt:<tag>` and `ghcr.io/dev-jahn/poe2-gpt-engine:<tag>`. No moving `latest` tag is published. Use a verified version or image digest. Compose builds from source by default, so a first installation does not depend on GHCR publication. ARM64 images and homelab automatic deployment are not included.

The workflows use GitHub's ephemeral token with read-only defaults. Only release jobs receive repository-release or package write permissions. No homelab credentials are stored in CI, and no deployment happens automatically on the user's server. Forks must review their own repository/package settings before releasing.

There is no PyPI publication workflow or claim that the distribution is already on PyPI. GitHub release publication and a public ChatGPT directory submission are separate processes. After the real endpoint and authentication work, follow [installation](installation.md) and [evaluation](evaluation.md) for ChatGPT testing and review.
