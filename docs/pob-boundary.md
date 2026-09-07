# Private PoB data boundary

PoB codes, decoded XML, source paths, and arbitrary engine text have no model-facing input or output field. The operator imports and exports files outside ChatGPT. The MCP process reads bounded projections or calls the private worker; it never mounts the raw store in the supported container topology.

## Operator-only import and export

Run these commands directly in your own terminal, not through ChatGPT or an agent shell. The input is a file containing the exported PoB code. Do not put its content into command-line arguments or paste it into chat.

```bash
poe2-pob-files import   --input /absolute/path/build.pob   --private-dir /srv/poe2/private   --projection-dir /srv/poe2/projections
```

The command returns an opaque `bld_` identifier. Share only that identifier with ChatGPT. Raw and projection directories must be separate and non-nested. Files are written atomically with restricted permissions.

Export copies the original bytes unchanged:

```bash
poe2-pob-files export   --build-id YOUR_IMPORTED_BUILD_ID   --private-dir /srv/poe2/private   --output /absolute/path/exported.pob
```

There is no MCP import/export tool or model-readable raw-file resource. Equipment comparisons do not modify the original build or produce a replacement PoB code.

## Enforced controls

The importer bounds encoded input to 2 MiB and decompressed XML to 8 MiB, uses safe XML parsing, requires a PoE2 root, and limits node count and depth. It never evaluates imported Lua. The worker uses pinned upstream code only.

Model-facing build, equipment, and engine requests are validated before SDK error serialization so invalid extra fields cannot be echoed by Pydantic. Responses use closed schemas, selected numeric metrics, bounded lists, and fixed public error codes. Worker arbitrary prints and stderr are discarded; temporary private files are deleted at request completion. Engine responses are limited to 8 KiB per public result.

Source data and trade item text remain untrusted. They are not instructions. The server holds trade query tokens and importer payloads internally, exposing short handles and sanitized views.

## Scope of the guarantee

This architecture prevents the plugin's supported tools from fetching or generating raw PoB payloads into the conversation. It cannot control content a user manually pastes, unrelated connectors, or a model outside this plugin. Server instructions tell the model never to request, reconstruct, repeat, or inspect codes through other tools. Do not grant agents separate access to the private store.

Private summaries and calculated numbers still reveal build information. Protect the MCP endpoint with a user-specific access boundary. There is no tenant authorization layer in this release. See [privacy](privacy.md) and [deployment](deployment.md).

Future character providers must fetch and decode server-side, save behind the same boundary, and return opaque IDs. A character name alone may be ambiguous and must not be treated as proof of ownership. Character lookup and poe.ninja ingestion are not implemented yet.
