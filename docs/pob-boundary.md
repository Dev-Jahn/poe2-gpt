# Private PoB data boundary

The two supported input flows are an account tag plus character name, or a `.txt` attachment in ChatGPT. The latter passes a host file reference, never raw file contents. There is no host file-transfer/import CLI. See [character integration](characters.md).

A dedicated network-enabled ingestion service fetches Ninja data or the attached file and stores original PoB bytes separately from allowlisted projections. MCP mounts neither the raw store nor the provider credential store. The private PoB computation worker reads original builds with no network access. Equipment comparisons preserve the original build and do not generate a replacement export.

## Enforced controls

Input is bounded to 2 MiB and expanded XML to 8 MiB. Parsing rejects entities/DTDs, foreign game roots, excess nodes/depth and invalid numeric values. Imported Lua is never executed. Only the pinned PoB runtime executes calculations.

MCP validates typed inputs before SDK validation can echo user content. Character calls accept identifiers or a ChatGPT file reference; there is no raw-content input, arbitrary URL import, host file path, or raw-resource tool. Output schemas expose bounded IDs, names, numeric statistics and fixed statuses. They omit arbitrary upstream notes, raw items, PoB strings and XML. Errors do not echo payloads, signed download URLs or credentials.

Ninja refresh credentials are isolated per user and only sent to the fixed Ninja refresh endpoint. Attachment downloads use a separate HTTP client, exact approved hosts, public-address checks, no credentials or redirects, and bounded reads. Private provider logging is disabled. Calculations use private temporary files with raw output discarded.

## Scope of the guarantee

The plugin's tools never return, reconstruct or generate raw PoB in the conversation. ChatGPT can independently process/retain a file the user attaches; the server cannot control the host's own file ingestion, pasted messages or other connectors. Instructions require the model to forward file references without opening attachments and never inspect the private store through other tools.

Selected build summaries still reveal character information. Each authenticated user has a separate MCP instance, importer, raw/projection/state volumes and sockets. Opaque build IDs do not replace access control. The host operator retains administrative access. See [privacy](privacy.md) and [deployment](deployment.md).
