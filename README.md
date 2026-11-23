# BattleBit Stat Ripper

[![CI](https://github.com/THEROCKSSS/battlebit-stat-ripper/actions/workflows/ci.yml/badge.svg)](https://github.com/THEROCKSSS/battlebit-stat-ripper/actions/workflows/ci.yml)

A small Windows app that captures **your own** BattleBit Remastered profile from the
official API and writes a portable profile file you can upload to a stats site.

- No game files are modified. No EAC interaction. No administrator rights.
- No password is stored. The app borrows a short-lived Steam auth ticket from the
  locally running Steam client, the same way the game does.
- The exported file contains every field the `/Player/GetStats` response provides,
  including the raw bytes, the 76 per-tool records, and the packed loadout blob.
- Every run is logged and appended to local history, so a user can run it any time
  and still keep a record if a file is lost.
- Errors have stable codes (`BBR-S001`, `BBR-A002`, `BBR-D001`, …), a plain-English
  cause, and a fix. The app can write a redacted diagnostics report in one click.

Verified against a live capture on 2026-11-23 and cross-checked against Owen's in-game
profile screen:

| Stat | In-game | Ripper |
|---|---:|---:|
| Kills | 3,873 | 3,873 |
| Deaths | 8,073 | 8,073 |
| Hours | 255.6 | 255.6 |
| XP / total score | 15,865,086 | 15,865,086 |
| Wins / losses | 333 / 368 | 333 / 368 |
| Revived / revives | 1,091 / 1,003 | 1,091 / 1,003 |
| Objectives | 760 | 760 |
| Vehicles destroyed | 439 | 439 |
| Vehicle repairs | 374,435 | 374,435 |

## Requirements

- Windows 10 or 11, 64-bit Python only if running from source.
- Steam running and signed in to the account that owns BattleBit Remastered.
- BattleBit Remastered installed in a Steam library (the app loads the game's
  `steam_api64.dll`; it does not copy or redistribute it).

## Use the GUI

Download `BattleBitStatRipper.exe` from the site's **Download** page or the
[latest GitHub release](https://github.com/THEROCKSSS/battlebit-stat-ripper/releases/latest),
or build it (see below). Double-click it and press **Rip my stats**.

The app writes two files to `Documents\BattleBit Stats Ripper\`:

```
BBR-<name>-<steamid>.bbrstats   JSON profile (upload this)
BBR-<name>-<steamid>.txt        human-readable stat sheet
```

It also keeps a local record of every distinct capture:

```
%LOCALAPPDATA%\BBR Stats Ripper\history.sqlite3     one row per unique raw response
%LOCALAPPDATA%\BBR Stats Ripper\logs\run-<id>.log   full run log
%LOCALAPPDATA%\BBR Stats Ripper\logs\runs\<id>.json structured summary
%LOCALAPPDATA%\BBR Stats Ripper\diagnostics\...     one-click diagnostics
```

The log never contains the Steam auth ticket. It does contain the Steam ID and
public stats, so treat a shared log as public.

## If something goes wrong

The app shows an error card with a code, what happened, and what to do. Press
**Copy error details** or **Open diagnostics folder**. The CLI prints the same
message and writes a diagnostics file:

```powershell
python -m bbr_ripper --diagnose --verbose
```

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) for the code table and
common fixes.

## Use the CLI

```powershell
python -m bbr_ripper --out "C:\Users\me\Documents\BattleBit Stats Ripper" --verbose
```

Other flags:

```
--json-only         skip the .txt sheet
--quiet             print only the output paths
--probe             check the Steam bridge without calling the API
--diagnose          check Steam + DNS + TLS and write a diagnostics report
--wait-for-steam N  wait up to N seconds for Steam (scheduled runs)
--no-history        do not append to local history
--history-csv PATH  export local history to CSV
--log-dir PATH      override the log directory
--open              open the output folder when done
--upload-url URL    site base URL (or BBR_UPLOAD_URL)
--upload-token T    collector token (or BBR_UPLOAD_TOKEN, safer)
--watch             keep running: capture + upload, then sleep
--interval-hours N  delay between watch runs (default 6, floor 5 minutes)
--version
```

To run automatically at logon and every few hours:

```powershell
.\scripts\install_startup_task.ps1 -Hours 6
.\scripts\install_startup_task.ps1 -Hours 3 -RunNow
.\scripts\uninstall_startup_task.ps1
```

The task is per-user, hidden, waits up to 5 minutes for Steam, and appends every
new capture to local history. If PowerShell blocks `Register-ScheduledTask` by
policy, run that one command from an elevated PowerShell or create the task in
Task Scheduler with the same action.

## Background collector

The site can keep a record fresh without anyone pressing a button. Create a token
under **Account → Collector tokens**, then run the ripper headlessly on the PC
where that Steam account is signed in:

```powershell
$env:BBR_UPLOAD_URL = "https://your-site"
$env:BBR_UPLOAD_TOKEN = "bbr_..."
.\dist\bbr-ripper-cli.exe --watch --interval-hours 6 --wait-for-steam 600
```

`--watch` captures, uploads to `POST /api/captures`, and sleeps. Upload failures
keep the local files and retry on the next cycle. `scripts/run_collector.ps1`
reads a private `collector.json` and is what the Startup-folder entry runs.

One limit is measured and hard: the BattleBit session is bound to the Steam
account that requested it. With one account's session, `GetStats` for another
Steam ID returns HTTP 200 with a one-byte `0x03`, not stats (own record still
works in the same session). So a server cannot impersonate players or pull any
Steam ID on demand; each account needs its own collector once. Full evidence and
the design are in [`docs/COLLECTOR.md`](docs/COLLECTOR.md).

## How it works

1. The app locates BattleBit through the Steam library registry and loads the game's
   `steam_api64.dll` in a short-lived helper process.
2. It calls `SteamAPI_ISteamUser_GetAuthSessionTicket` for app `671860`.
3. It posts the ticket to `https://api.battlebit.cloud/Tokens/GetToken`, exactly like
   the game client:
   `SteamID(u64) + ticket_hex_len(u16) + ticket_hex + u64(1)`.
4. It posts `SteamID(u64) + session(u64)` to `/Player/GetStats`.
5. It decodes the 2,590–2,678 byte response and writes the profile.

The decode schema was recovered from the game's own serializers
(`PlayerStats_PlayerProgess__WriteTo_MasterServer_GameServerSide`,
`FUN_182ef5360`, `PlayerStats_PlayerAchievements__…`,
`PlayerStats_PlayerSelections__…`) and validated against live data. The full
byte layout is in [`docs/FORMAT.md`](docs/FORMAT.md).

## Website

The `server/` folder is a Flask site with Steam sign-in, a Steam player directory,
uploads, public profile pages, private visibility, a leaderboard, clans, profile
portraits/social links, and a first-class ripper download page.

Every Steam ID can get a page built from that public Steam profile: persona name,
real name, summary, avatar, avatar frame, level, status, location, and animated
background. BattleBit stats still come only from the player's own uploaded capture.

```powershell
cd server
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\waitress-serve --host 127.0.0.1 --port 8099 app:app
```

Open <http://127.0.0.1:8099>. The SQLite database and session key are created in
`server/data/`. Put a built `BattleBitStatRipper.exe` and the release zip at
`dist/` to enable the download page.

Site surface:

- `/` — front page, recent public records, clan preview, ripper card
- `/players` — Steam player directory; paste any Steam ID, profile link, or vanity
- `/p/<steamid>` — Steam card plus public record; owner can edit portrait, name, bio, socials
- `/auth/steam` — Steam OpenID sign-in (creates the account on first use)
- `/me` → **Collector tokens** — create/revoke tokens for background uploads
- `POST /api/captures` — bearer-token upload for the headless collector
- `/clans` — directory with search and sort
- `/clans/new` — create a clan (tag, crest, join mode, socials)
- `/c/<slug>` — clan page with roster and combined public stats
- `/c/<slug>/manage` — owner/officer settings, requests, roster actions
- `/download` — release page; `/download/windows` and `/download/zip` direct files
- `/upload` — attach a capture to the signed-in account

Rate limits cover registration, login, uploads, profile edits, clan creation,
joins, management actions, and disbanding. See [`server/README.md`](server/README.md).

For a container deployment:

```bash
podman build -f server/Dockerfile -t bbr-profiles .
podman run -d --name bbr-profiles -p 127.0.0.1:8099:8099 \
  -v bbr-profiles-data:/data \
  -e BBR_SECRET_KEY="$(openssl rand -hex 32)" \
  bbr-profiles
```

Set `BBR_HTTPS=1` behind a TLS reverse proxy so the session cookie is marked
`Secure`. Set `BBR_PUBLIC_URL` to the site's absolute origin (for example
`https://owens-pc-vpn.tailff2683.ts.net:8552`) so Steam OpenID returns to the right
host.

Seed the player directory with the community profiles the site launched with:

```powershell
python scripts/seed_players.py            # the six seeded IDs
python scripts/seed_players.py 7656119... # any Steam ID
```

## Build the Windows app

```powershell
python -m venv .venv
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller --noconfirm --clean --onefile --windowed ^
  --name BattleBitStatRipper --paths src --distpath dist --workpath build/work ^
  --specpath build run_gui.py
```

Or run `build\build.ps1` to build both the GUI and CLI and zip the GUI.

## Tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

The tests cover the wire format, the exact 44-field profile layout, the tool
records, the weekly-challenge length, raw-byte preservation, truncation, error
classification, log/summary writing, ticket redaction, and history dedupe.

The server suite covers upload validation, private visibility, CSRF, avatar and
social-link editing, clan creation, join requests and approval, rate limiting,
social URL validation, the download routes, Steam profile parsing, OpenID
assertion checks, and the player directory:

```powershell
cd server
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Documentation

- [`docs/FORMAT.md`](docs/FORMAT.md) — API wire format and `.bbrstats` schema.
- [`docs/REPLICATION.md`](docs/REPLICATION.md) — rebuild the whole pipeline from scratch.
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — error codes and fixes.
- [`docs/PRIVACY.md`](docs/PRIVACY.md) — what is sent, stored, and shareable.
- [`docs/STEAM.md`](docs/STEAM.md) — Steam OpenID, public profile sync, player cards.
- [`docs/COLLECTOR.md`](docs/COLLECTOR.md) — background collector, tokens, and the session-binding limit.
- [`docs/ECOSYSTEM.md`](docs/ECOSYSTEM.md) — GitHub/web tools that can help: server API, Steam Web API, packaging, ops.
- [`docs/RELEASING.md`](docs/RELEASING.md) — tag → CI build → release assets.
- [`HANDOFF.md`](HANDOFF.md) — current state and next steps.

## Limitations

- The API is unofficial and private to the game. If BattleBit changes the handshake
  or response schema, the decoder stops and preserves the raw bytes instead of
  inventing values.
- Per-tool names come from the `Tools.AllTools` array in the 2.2.5 build. A game
  update can reorder it; the app will still show `Tool #<id>` when a name is missing.
- The `.bbrstats` file includes your Steam ID and public stats. Upload it only to a
  site you trust, or keep it local.
- The executable is unsigned. Windows SmartScreen may warn on first run; the source
  is here to inspect and build yourself.

## License

MIT. Not affiliated with BattleBit Remastered, Steam, or Valve.
