# Share a Mac server with two friends

One Mac, Colima VM, Cloudflare Tunnel and Access application can serve the owner
and two friends. Each person connects their own ChatGPT account to their own MCP
path and signs in with their own Access identity. Each path has a separate MCP
process, private PoB worker, build volume, projection volume and Unix socket.
The existing single-owner JWT check remains enabled in every MCP instance.

| Person | Example ChatGPT endpoint | Mac origin |
|---|---|---|
| Owner | `https://poe2.example.com/mcp` | `localhost:18080` |
| Friend 1, ID `alice` | `https://poe2.example.com/u/alice/mcp` | `localhost:18082` |
| Friend 2, ID `bob` | `https://poe2.example.com/u/bob/mcp` | `localhost:18083` |

The path selects an instance, but grants no permission. An Alice token sent to
Bob's actual origin is denied with 403. A known Bob build ID or retained trade
search ID is unavailable in Alice's instance. ChatGPT tool arguments do not
select the user, email, private directory or worker socket.

## Add friends

Complete the [Mac setup](mac-mini-cloudflare.md) for the owner first. An existing
owner deployment keeps its endpoint, containers, volume names and build IDs.
Run these commands in the operator's Mac terminal:

```bash
python3.12 scripts/mac.py add-user --id alice
python3.12 scripts/mac.py add-user --id bob
python3.12 scripts/mac.py start
python3.12 scripts/mac.py members
```

Each `add-user` prompts for that friend's login email. Emails and generated
Compose settings stay in the local configuration directory outside Git. IDs
are stable storage identities, not character names. Use lowercase letters,
digits and hyphens, starting with a letter, up to 24 characters. An email or ID
cannot belong to more than one member. This deployment allows two active friends.

In Cloudflare, update the existing Access application's **Allow → Emails** rule
to contain the three individual login emails. Keep it on the entire hostname,
with Managed OAuth enabled. The local `POE2_CF_OWNER_EMAIL` setting for the
original instance remains the owner's one email. The renderer assigns each
friend's one email to their separate instance.

In the same tunnel's published application routes, add the following **above**
the existing hostname route with no path:

| Hostname | Path regular expression | HTTP service |
|---|---|---|
| `poe2.example.com` | `^/u/alice/(mcp\|accounts(/.*)?)$` | `localhost:18082` |
| `poe2.example.com` | `^/u/bob/(mcp\|accounts(/.*)?)$` | `localhost:18083` |
| `poe2.example.com` | Empty, existing fallback | `localhost:18080` |

Use the actual ports printed by `members`. Cloudflared matches ingress rules
from top to bottom. Preserve the path and public Host header; the friend's
backend serves that full path directly. OAuth discovery remains handled by
Cloudflare at the shared hostname. See [Cloudflare routing rules](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/).

Give each friend their endpoint. They create their own OAuth MCP connection in
ChatGPT and authenticate with the email registered for that instance. Add each
connection's exact callback URI to the Managed OAuth redirect allowlist if it
differs. Each connection can have a separate OAuth grant even when the hostname
is shared. See [Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/).

Friends do not need the tunnel token, a Mac login, Docker or access to the owner's
ChatGPT account. The operator performs server configuration; no invitations are
sent by these scripts.

## Register each person's build

Each person uses their own authenticated MCP endpoint. Provide an account tag and
character name, or attach an original PoB `.txt` file in ChatGPT. The private
provider for that endpoint imports the build automatically. No physical-host
file transfer or operator PoB import command is provided. Build IDs and Ninja
refresh sessions are local to the member; owner credentials are never reused.

See [character integration](characters.md) for account linking, file references,
refresh session setup and snapshot semantics. Guest IDs such as `guest1` and
`guest2` are configured normally; examples elsewhere are placeholders.

## What is shared

| Resource | Scope |
|---|---|
| Mac, Linux VM, images, domain and tunnel | Shared infrastructure |
| Scout SQLite price cache | Shared public market snapshots |
| Trade searches and retained candidate state | Separate MCP process per person |
| Raw builds, projections and worker socket | Separate volumes per person |
| PoB temporary files and results | Private worker per person |
| Calculation lease | Shared lock file containing no build data |

Only one PoB calculation batch runs at a time across the three workers. Another
calculation receives `engine_busy` and can be retried later; prices and ordinary
trade requests continue independently. The lease is released on completion,
failure or worker exit. The 8 GiB VM default is a starting allocation for this
small deployment, not a performance guarantee for arbitrary builds.

All upstream requests still leave through the same network address. Trade rate
limits and challenges can affect everyone; keep searches modest and respect
retry responses. The shared deployment does not introduce account-cookie sharing.

This isolates friends' service access from one another. The Mac/Docker operator
can administer and read the underlying files, including backups. It does not
provide cryptographic confidentiality against the server operator.

## Revoke access

```bash
python3.12 scripts/mac.py remove-user --id alice
```

This stops and removes Alice's containers before marking the membership retired.
Previously issued tokens cannot reach a running Alice instance afterward. Remove
Alice's Access email rule and tunnel route as well. Private volumes are retained
for operator-managed backup/deletion; neither the ID nor its email is reassigned
through `add-user`. Do not edit a record to turn one person's storage into another's.
The command does not alter the owner's or Bob's containers.

## Acceptance tests

For each actual ChatGPT connection, verify its own build summary and calculation,
then try a known other person's build ID and retained trade search ID: both must
fail without revealing their data. Connecting to another person's URL must fail
authentication. Check a concurrent PoB request returns `engine_busy`, then succeeds
after the first calculation finishes. Verify revocation with an already signed-in
client. Cloudflare account setup and these real-client checks are deployment gates;
the repository CI uses synthetic identities and synthetic builds.

Each member also has a separate `character-provider`, `character-socket` and `character-state` volume. The provider reaches Ninja and approved attachment hosts; only the calculation worker has no network.


Since 0.13, each member also has an `account-broker` with separate socket, state,
key and configuration volumes. Account pages use `/accounts` or
`/u/<member>/accounts`; the expanded routes above must include callbacks. Member
removal stops the broker as well. See [accounts](accounts.md) before enabling
GGG OAuth or restoring credential backups.
