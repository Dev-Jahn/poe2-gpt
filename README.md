# POE2 GPT

[English](README.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Русский](README.ru.md) · [Português (Brasil)](README.pt-BR.md)

A self-hosted ChatGPT plugin and MCP server for **Path of Exile 2**: currency prices, official trade-site equipment search, private Path of Building calculations, and equipment upgrades within a budget.

**Status: 0.11.0, experimental.** The code includes up to 31 MCP tools. Homelab deployment, authentication, and testing with your own character are separate installation steps. This repository does not provide a hosted endpoint or a published ChatGPT directory listing.

## Features

Version 0.11 adds complete equipment/skill/configuration inspection, paged
diagnostics, request-time Ninja provenance, descriptive trade results, scoped
resource comparisons and minimum-cost equipment repair. See the
[review resolution and acceptance scenarios](docs/review-followup.md).

| Area | Available now |
|---|---|
| Currency prices | Scout JSON API, 17 category families, league selection, search, basket quotes, cache and source timestamps |
| Equipment search | Typed filters and stat lookup through the official trade site's experimental `trade2` web API |
| Saved builds | Account + character lookup or ChatGPT .txt attachment, opaque build IDs, bounded summaries and passive-node pages |
| PoB calculation | Pinned PoE2 PoB engine in a private worker; compare equipment and validate requirements |
| Upgrade planning | Maximize explicit character metrics or minimize cost under budget and minimum-stat constraints |

The default league is **Forbidden Rites**; check `list_leagues` before using another season. Prices default to **Exalted Orbs per item**. English and verified Korean item names are supported through a bundled PoE2DB name catalog. Currency, base types, classes and selected skills include Korean labels when verified; `search_game_terms` provides both names and their sources. The server does not need an OpenAI API key.

The engine combines a pinned PoB2 development revision with a checksummed 0.5.5 data overlay. It reports the selected skill and distinguishes player DPS, selected-minion DPS and explicitly configured FullDPS. Unknown passive nodes, unparsed effects and unsupported configurations remain visible and block verified upgrade recommendations. See [engine compatibility](docs/pob-engine.md) and [localization coverage](docs/localization.md).

Version 0.10 adds copied Spirit Vessel attacks, captured-beast modifiers, Martial Artist mechanics, PoE2 leech and Impale rules, and bounded charge/Mountain combat scenarios. Optional typed [calculation assumptions](docs/calculation-assumptions.md) apply equally to the baseline and equipment candidates. See the [current-league coverage matrix](docs/league-coverage.md) and [upstream review](docs/upstream-review-010.md) for tested scope and remaining gaps.

**MCP never returns raw PoB codes or XML.** A private ingestion service downloads Ninja exports or attached-file references; the calculation worker reads private files. Tool results contain bounded summaries, IDs, validated numbers, and statuses. Never paste a PoB code into chat. ChatGPT's own attachment processing is outside the plugin's control. See the [data boundary](docs/pob-boundary.md).

## Quick start

Python 3.11+ is required. The PoB worker requires Linux and its pinned Lua runtime.

```bash
git clone https://github.com/Dev-Jahn/poe2-gpt.git
cd poe2-gpt
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m poe2_companion.check
```

On Windows, create the environment with `py -3 -m venv .venv` and use `.venv\Scripts\python.exe` for the Python commands. The `poe2_companion` module and previous `poe2-companion` command remain compatible.

Run the homelab MCP service:

```bash
docker compose up -d --build
```

Its local endpoint is `http://127.0.0.1:8000/mcp`. Connect it to ChatGPT web/desktop through an account-scoped Secure MCP Tunnel, or deploy a compatible authenticated HTTPS endpoint. Cloudflare can supply OAuth; each MCP instance accepts one configured owner. See [installation](docs/installation.md) and [deployment](docs/deployment.md).

For a Mac mini behind an inbound firewall, use the [Mac mini + Cloudflare setup](docs/mac-mini-cloudflare.md): native ARM64/amd64 Linux containers, Managed OAuth with origin JWT verification, and supervised login services.

[Share with two friends](docs/friends.md): separate authenticated MCP instances, build stores, trade search state and PoB workers on one Mac. The domain, tunnel and public price cache are shared.

The repository includes `.codex-plugin/plugin.json`, `.mcp.json`, and a Git-backed marketplace catalog for local plugin hosts. Installing a local STDIO server does not make it available to ChatGPT web. Public directory publication requires a separate OpenAI review. [Plugin packaging reference](https://developers.openai.com/plugins/build/plugins).

## Character connection

Provide a PoE account tag and character name, or attach the original PoB export as a UTF-8 `.txt` file in ChatGPT. Every `get_character` call resolves the league and checks Ninja's currently published model before importing it; an identical export can safely reuse the immutable build ID. The response includes the upstream check time and model version so reuse is not mistaken for a local-cache hit. `import_pob_attachment` consumes the host file reference without asking the model to read or rewrite the file. Both return a build ID for calculation and upgrade tools. For Ninja-imported builds, `get_build_equipment` lists the active equipped slots and returns detailed properties/modifiers for one requested slot without exposing the PoB/XML or saved-but-unequipped items. No file transfer to the physical server or PoB import command is provided.

Link the public profile through [poe.ninja Connect](https://poe.ninja/account). Kakao users first click **English** on [Kakao account connections](https://poe.kakaogames.com/my-account/connections) to transfer their signed-in GGG session, then authorize Ninja. Public lookup needs no server-side login; explicit refresh requires a separately configured per-user Ninja session. See [character integration and file boundaries](docs/characters.md).

## Try it

- “Check Divine Orb prices in Forbidden Rites, quoted in Exalted Orbs. Show freshness and the source.”
- “Find rare helmets with at least 100 life under 100 Exalted Orbs.”
- “Using my imported build ID and those search results, maximize life within 20 Divine Orbs while keeping cold resistance at least 75.”

The last request needs the private PoB worker. The [tool reference](docs/tools.md) explains which tools each configuration exposes.

## Scope and limitations

Scout prices are aggregated estimates; fetch time is not the original market observation time. Trade listings may sell before you act. The trade web API is not GGG's documented OAuth developer API and may change or deny access. The adapter respects rate limits and stops on authentication or challenge responses.

PoB evaluates the saved active configuration, not a live character. Only combinations that pass supported equipment checks enter PoB recommendations; unknown mechanics remain `indeterminate`. Optimization covers retained candidates, not the entire market. The separate item-stat optimizer is not a PoB or character-DPS calculation.

Account-tag character lookup and private poe.ninja import are available. Automatic purchasing and modified-build export are not implemented. Docker deployment and your own PoB compatibility must be checked on the target host.

## Development and license

```bash
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_release.py
```

Real-engine tests require the optional runtime; ordinary test runs explicitly skip them. See [Contributing](CONTRIBUTING.md), [architecture](docs/architecture.md), [engine setup](docs/pob-engine.md), [CI and releases](docs/releases.md), [Security](SECURITY.md), and [Privacy](docs/privacy.md).

Released under the [MIT License](LICENSE). See [NOTICE](NOTICE) for third-party components and trademarks. README locales are selected using a public language-community proxy, with Korean included; they are not a claim about country player rankings. [Localization policy](docs/localization.md).
