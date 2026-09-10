# Game accounts and persistent connections

0.13 adds seven optional MCP tools and an authenticated account page. The Mac
stack enables one private account broker per member, including deployments without
the PoB engine. The original builds, Ninja credentials and market caches retain
their existing boundaries.

## Using accounts

`register_game_account` saves a provider (`ggg` or `kakao`) and account name.
This persists across restarts and conversations but is **unverified**. Registering
a name does not authenticate a game account. `get_game_accounts` lists up to ten
records per page, including empty `records=[]`; the store allows sixteen accounts.
`set_default_game_account` selects the default for future handoffs.

`begin_game_account_link` returns the authenticated account page, even when OAuth
is not configured. Owner uses `/accounts`; friends use `/u/<member>/accounts`.
The page manages default selection, automatic refresh and disconnection. Login
uses a configured GGG confidential OAuth application with `account:profile`, PKCE,
browser-bound state and a verified profile UUID. Kakao OAuth and website-session
enrollment are not implemented. Passwords and cookies are never requested in chat.

`get_game_connection_status` reports saved verification, access expiry, absolute
refresh deadline and the next action. Unknown expiry remains null. Expired access
with a usable enabled refresh grant is `refresh_pending`; expired or revoked
authorization requires re-login. An active credential is not a live game login.

## Session maintenance

The private broker encrypts grants and PKCE verifiers using AES-256-GCM. Its key,
state, configuration and UDS have separate per-member volumes. Only the socket is
mounted in that member's MCP process. Keys are generated on first initialization;
a missing key for an existing database fails startup rather than discarding data.
The first authenticated principal binds the store to its verified issuer/subject.
Another subject cannot claim it merely by supplying the same email.

A background task checks due grants once per minute. Refresh uses the documented
grant, updates the credential pair atomically and preserves the original absolute
deadline. A durable in-flight flag prevents crash recovery from blindly reusing a
possibly consumed token. Ambiguous token responses require re-login. HTTP 429
preserves its retry delay. Disconnection and reauthorization invalidate previous
handoffs and prevent an in-flight refresh or login from restoring a removed grant.
Expiry within seven days is surfaced through `next_action=reauthenticate` and the
account page. No email or chat notification is sent automatically.

GGG's current confidential-client documentation describes 28-day access tokens and
90-day refresh tokens; renewed refresh tokens inherit the original expiry. Actual
access expiry follows the response's `expires_in`. This cannot provide permanent
authentication. See [official authorization documentation](https://www.pathofexile.com/developer/docs/authorization).

Disconnect immediately removes local secrets and pending authorization attempts.
The requested profile scope does not grant upstream token revocation, so the UI
links to the official applications page for revoking the grant there as well.
The operator can administer the underlying host and read memory/keys; encryption
does not hide credentials from that operator. Online master-key rotation is not
implemented in this release.

## Trade handoffs

`prepare_hideout_travel` accepts a retained `search_id` and `listing_ref`, with an
optional account ID. It verifies that the listing belongs to this instance and
records the selected account, listing and observed price. Multiple accounts need
a default or explicit selection. The result currently always has:

```json
{
  "mode": "official_site",
  "game_action_executed": false,
  "website_account_verified": false,
  "expires_at_scope": "receipt_only"
}
```

The URL opens the existing GGG trade search. It does not switch the website's
account, guarantee availability, identify the user's current game session or
teleport. Kakao labels do not create a Kakao-authenticated execution path. Verify
the account on the official site before using its Travel to Hideout button.

`get_hideout_travel_result` recovers the receipt for two minutes; afterward its
status is expired and no URL is returned. Changing the default account does not
change an earlier receipt. Disconnect/reconnect cancels earlier receipts. The
two-minute deadline applies to the stored receipt, not to the public search URL
already visible in chat. At most 256 receipts are retained, for up to 24 hours;
capacity pressure may evict expired ones earlier.

The future authenticated travel POST and confirmation UI in the
[design](account-sessions-and-travel.md) remain unimplemented. A documented or
otherwise authorized, verified provider integration is needed first. The public
search DTO continues to report `travel_link_supported=false`.

## Operator setup

Normal `scripts/mac.py start` creates the broker and its empty stores; OAuth
configuration is optional. The GGG docs currently state that new app applications
cannot be processed. An existing registered confidential client and approved grant
are prerequisites, not something this server creates.
[Application registration](https://www.pathofexile.com/developer/docs)

For an existing registered app, allow the exact HTTPS callbacks for the members
who will connect, for example `/accounts/callback` and
`/u/guest1/accounts/callback` on the deployed hostname. Run privately on the Mac:

```bash
python3.12 scripts/mac.py configure-game-oauth --user owner
python3.12 scripts/mac.py configure-game-oauth --user guest1
```

The helper prompts for client ID, hidden client secret and contact, passes them
through stdin into that member's private config volume and restarts only that
broker. An empty client ID disables OAuth. Do not put credentials in Git, MCP
arguments or messages to deployment agents. This is app configuration; users
subsequently grant access to their own accounts on the official site.

Expand each friend's Cloudflare tunnel route from `^/u/<id>/mcp$` to
`^/u/<id>/(mcp|accounts(/.*)?)$`, targeting its existing port before the owner
fallback. The whole hostname must stay behind Access. Preserve Host and the
original path. Test browser login and MCP with the same real member: both must
resolve to the same verified subject. A mismatch fails closed and requires
investigation; do not weaken subject binding or copy a different user's store.

`remove-user` stops/removes the broker along with that user's other services and
retains its private volumes under the existing retirement policy. Preserve the
state and matching key together for encrypted backups, with restricted access.
Never restore a backup directly into a live broker: first stop it and run its
`--invalidate-restored-sessions` command against the restored volumes, using a
one-off container with the same configuration. This deletes restored credentials
and invalidates old links before startup. Users then reconnect. Lost master keys
cannot recover the old credentials. Backups need their own retention/deletion
policy; local disconnection cannot erase historical backups.

## Validation and deployment gates

`tests/test_accounts.py` exercises authenticated HTTP MCP output contracts,
enrollment/PKCE/state/CSRF, account mismatch, two-member isolation, key loss,
encrypted persistence, refresh rotation/restart, absolute expiry and disconnect
races. Its provider is synthetic; it does not prove live GGG login or game travel.
The Mac container smoke test adds broker/key/socket separation and foreign-ID
denial in disposable CI volumes.

For production, verify all twelve containers, origin denial, per-member routes
and real browser/MCP identity continuity. Do not use fabricated subjects to smoke
test production account RPC: the first successful call persists its identity
binding. Use isolated test volumes for synthetic principals. Existing raw build
files, volumes and Ninja session configuration must survive the update.
