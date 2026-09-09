# Character integration

Character entry has two user flows:

1. Supply a PoE account tag and character name. On every call, `get_character` discovers an unambiguous league, requests poe.ninja's current model version and model, and privately imports its PoB export. A league slug is needed only to resolve ambiguity. Content-addressed reuse of an identical export is reported separately from the request-time upstream check.
2. Attach an original PoB export as a UTF-8 `.txt` file in ChatGPT and ask to import it. `import_pob_attachment` takes a top-level `file` object supplied by ChatGPT, not file contents or a filesystem path. The private service downloads the bytes directly.

Both return an opaque build ID and bounded summary. Continue with `recalculate_build`, `validate_build_equipment` or `recommend_pob_trade_upgrades`. Re-fetch or reattach when the character changes; existing snapshots and calculations are not live game state. Identical original bytes and supplemental metadata reuse an existing import within the same user store.

There is no physical-server file transfer, `import-build` command or public PoB import/export CLI. Do not read attachments using other tools, ask users to paste codes, generate replacement codes, or expose private files through filesystem connectors.

## Ninja account prerequisite

GGG/Steam users can use **Connect** at [poe.ninja/account](https://poe.ninja/account), then approve **Authorize** at GGG. For Kakao accounts, sign in at [Kakao account connections](https://poe.kakaogames.com/my-account/connections), click **English** to transfer the session through `/login/transfer`, then use Ninja **Connect** and GGG **Authorize**. The Kakao flow is user-verified; provider UI can change. See the [Korean README](../README.ko.md).

The public profile must be available to Ninja. Account tags are converted to profile slugs by replacing the final `#` separator with `-`. Names and leagues are individually URL-encoded. This public lookup is not proof that the requesting user owns the PoE account; imports belong to the authenticated MCP user's isolated store.

The adapter follows the website's event stream to obtain the current snapshot version, reads the versioned character list/model, and closes the stream after the first version event. It does not hard-code `model/15`. Requests use a fixed `poe.ninja` origin, bounded response sizes/timeouts, no redirects, fixed errors and no credential collection through MCP. Private profiles and challenges fail explicitly.

For captured beasts, the provider privately joins Ninja metadata to the original
export only when canonical skill, species, level, quality and the complete support
multiset identify exactly one instance on both sides. It also verifies the
export's selected species and companion membership. Ambiguous or unmapped records
do not establish complete modifier coverage. The bounded supplement contains
canonical identifiers and verification hashes; it is unavailable to MCP file
readers and contains no raw upstream properties. The worker verifies it again
before applying it to a temporary calculation. Original export bytes remain
unchanged, and changed metadata creates a new immutable build ID. Re-fetching
through `get_character` enables this enrichment for previously imported builds;
an attachment without verified supplemental data retains missing-roll diagnostics.

## File reference contract

The tool declares `_meta["openai/fileParams"] = ["file"]` with the [official file schema](https://developers.openai.com/plugins/reference): required `download_url` and `file_id`; optional string `mime_type` and `file_name`. All four properties are declared. The model should forward the host-supplied reference without opening or rewriting the file. Plain PoB text, Base64 arguments, XML and local paths are rejected.

The private ingestion service allows only exact approved HTTPS download hosts, rejects private-address destinations and redirects, sends no Ninja credentials to downloads, and bounds the file at 2 MiB. The initial allowlist is `files.oaiusercontent.com`. If the host supplies another legitimate storage hostname, the operator must verify it and add the exact hostname using `POE2_ATTACHMENT_HOSTS` on that user's provider service. Do not allow arbitrary domains or disable URL validation. Expired URLs require reattaching the file; the tool does not echo signed URLs.

The plugin does not send the file contents to the model. ChatGPT may independently process or retain attachments; this server cannot disable the host's own attachment ingestion. Host file-reference support must be checked in the actual ChatGPT installation after refreshing the tool list.

## Explicit refresh

`refresh_character` is not required to read the latest model already published by Ninja. It sends the website's authenticated empty-body POST to ask Ninja to fetch again from the game account, then reads a bounded overview. It is a write operation and should be called only when the user explicitly requests that upstream refresh. It never retries the POST automatically. A persistent minimum five-minute cooldown survives provider restarts and honors longer upstream wait times. Success means Ninja accepted the request, not that a new GGG fetch has been proven. Call `get_character` afterwards to import the resulting published snapshot.

Public lookup and PoB import require no Ninja cookie. Refresh returned HTTP 401 without authentication during verification. A browser's GGG→Ninja account link does not give this server a Ninja session; ChatGPT/Cloudflare OAuth is also unrelated.

For refresh only, the operator may configure an explicitly authorized Ninja session locally using `python3.12 scripts/mac.py configure-ninja --user owner` (or an active guest ID). Enter the matching PoE account tag and the Ninja Cookie header in the hidden prompt. Obtain it in the user's own authenticated browser; never paste it into ChatGPT or send it to an agent. Empty cookie input revokes the configured session. This is credential setup, not a PoB file-transfer path.

The provider stores this session as a restricted file in that user's private `character-state` volume. It sends the cookie only to the fixed Ninja refresh endpoint and only for the configured account. Expiry/revocation returns `authentication_required`; another account returns `account_mismatch`. No CAPTCHA solving, credential scraping, proxy rotation or automatic login is implemented. Each guest needs their own session; owner credentials are never cloned to guests.

## Deployment and retention

`compose.engine.yaml` and the Mac engine overlay include the character provider automatically. Its private Unix socket and state volume are unique per member. It writes raw builds and safe projections; MCP reads projections and sockets only. PoB calculation keeps `network_mode: none`.

Original bytes and summaries persist across restarts. Imports are limited to 500 builds and 128 MiB of original bytes plus supplemental metadata per user; capacity errors do not evict older builds. Operator backup/deletion remains an administration task. Credential state and signed URLs must not be logged. The provider container disables Docker log collection; HTTP client debug logging must remain disabled.
