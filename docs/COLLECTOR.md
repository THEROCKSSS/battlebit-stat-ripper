# Background collector

Goal: keep player records fresh without asking everyone to run a GUI each time.

## The hard limit (measured, not assumed)

BattleBit's `POST /Player/GetStats` request is `steamid(u64) + session(u64)`. The
session comes from `POST /Tokens/GetToken`, which exchanges a Steam auth ticket.
The session is bound to the ticket's account. Feeding a different Steam ID returns
HTTP 200 with a one-byte body `0x03` instead of stats.

Verified 2026-11-23 with the signed-in account:

| Request | Result |
|---|---|
| `GetStats(own_id, own_session)` | 2,590 bytes, 3,873 kills, schema OK |
| `GetStats(friend_id, own_session)` ×3 | HTTP 200, body `0x03`, no stats |
| `GetStats(own_id, own_session)` again | still 2,590 bytes, schema OK |

So one account cannot pull another player's record server-side, and a hosted
"paste any Steam ID and get stats" service is not possible with this API. Any
design that promises that would be fabricating data.

## What works: one collector per Steam account

Each player runs the same ripper headlessly on the PC where their Steam account is
signed in. It captures and uploads on a schedule. The site stores the record under
that account.

```
player PC                          site
---------                          ----
Steam ticket → GetToken → GetStats
        ↓
   .bbrstats JSON
        ↓  POST /api/captures
   Bearer collector token  ───────► validate, bind steam_id, upsert profile
```

The site never sees a Steam password, ticket, or session. The token can upload
only the Steam ID it was created for.

### 1. Create a token

Sign in on the site → **Account** → **Collector tokens** → label + Steam ID →
**Create token**. Copy it once; the server stores only `sha256(token)`.

A Steam-linked account can only create a token for its own Steam ID. A local
password account (the owner account used before Steam sign-in existed) can bind a
token to any ID, which is how the owner seeds their own collector before signing
in through Steam.

### 2. Run the collector

```powershell
$env:BBR_UPLOAD_URL = "https://owens-pc-vpn.tailff2683.ts.net:8552"
$env:BBR_UPLOAD_TOKEN = "bbr_..."
.\dist\bbr-ripper-cli.exe --watch --interval-hours 6 --wait-for-steam 600
```

- `--watch` captures, uploads, then sleeps; it does not exit.
- `--interval-hours` has a 5-minute floor.
- `--wait-for-steam` covers Steam starting after logon.
- `--upload-url` / `--upload-token` also read `BBR_UPLOAD_URL` /
  `BBR_UPLOAD_TOKEN`, which keeps the token off the command line.
- Upload failures return code 6 but keep the local files and history; the next
  cycle retries.

### 3. Start it at logon

`scripts/run_collector.ps1` reads
`%LOCALAPPDATA%\BBR Stats Ripper\collector.json`:

```json
{ "url": "http://127.0.0.1:8099", "token": "bbr_...", "interval_hours": 6 }
```

It sets the environment variables and runs the CLI with `--watch`, appending to
`%LOCALAPPDATA%\BBR Stats Ripper\collector.log`. The Startup-folder entry
`bbr-collector.cmd` starts it hidden. Use the loopback URL when the collector runs
on the same PC as the site; use the tailnet URL for a different PC.

A scheduled task would be cleaner, but `Register-ScheduledTask` needs an elevated
shell on this PC; the Startup folder works without admin.

## API

`POST /api/captures`

```http
Authorization: Bearer bbr_...
Content-Type: application/json

{ "schema": "bbr-profile/1", "player": { "steam_id": "..." }, ... }
```

- 200 `{ok, steam_id, persona, url}`
- 400 malformed/invalid capture
- 401 missing, unknown, or revoked token
- 403 token bound to a different Steam ID
- 409 record belongs to another account
- 429 rate limit (10 uploads/hour/account)

The endpoint reuses the same `validate_profile` as the web upload, preserves the
existing visibility, and updates `upload_tokens.last_used_at`.

## Session logger (planned)

A future in-game tool can log the Steam IDs in your lobby. Those IDs are useful
immediately for **Steam cards** (`players` rows): name, avatar, frame, level,
status. They do not unlock game stats. Stats appear only when each of those
players runs a collector once, because of the session binding above.

Do not auto-add every ID from every lobby without consent. Feed sessions into the
directory deliberately, and expect many pages to show "No BattleBit capture yet".

## Tests

- `tests/test_upload.py` — request shape, bearer header, 401/403 mapping.
- `server/tests/test_server.py::test_18` — create token, upload, reject wrong
  Steam ID, revoke, reject after revoke.
