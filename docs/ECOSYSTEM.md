# BattleBit ecosystem research (2026-11-23)

What exists on GitHub and the public web that can help this project. Checked
against live endpoints where possible. Links are to the canonical repos/docs.

## The headline: the official community-server API exposes lifetime stats

`MrOkiDoki/BattleBit-Community-Server-API` (C#, MIT, 167 stars, updated 2025-10)
is the server-side API used by BattleBit community servers. On a player join the
server receives that player's **full `PlayerStats`**, not just match stats:

- `BattleBitAPI/Server/Player.cs` exposes `SteamID`, `Name`, `IP`.
- `PlayerJoiningArguments.Stats` is a `PlayerStats` with `Progress`,
  `ToolProgress`, `Achievements`, and `Selections`.
- `PlayerStats.PlayerProgess` has 42 lifetime fields: `KillCount`, `DeathCount`,
  `WinCount`, `LoseCount`, `Revived`, `RevivedTeamMates`, `Assists`, `Prestige`,
  `Rank`, `EXP`, `ShotsFired`, `ShotsHit`, `Headshots`, `ObjectivesComplated`,
  `HealedHPs`, `RoadKills`, `Suicides`, `VehiclesDestroyed`, `VehicleHPRepaired`,
  `LongestKill`, `PlayTimeSeconds`, per-class kills/playtime/score, and
  `TotalScore`.
- `OnPlayerJoiningToServer(steamID, args)` and
  `OnSavePlayerStats(steamID, stats)` fire server-side.

That is the same lifetime data our ripper decodes, delivered by the game to a
server we control — no client app required, no EAC interaction. It also logs the
SteamID, so it is simultaneously the session logger, **for players on that
server**.

Implementations:

- `BattleBit-Community-Servers/BattleBitAPIRunner` (C#, 16 stars, updated
  2025-07) — modular runner; modules catalog at <https://modules.battlebit.community>.
- `battlebit-community-server-api` on PyPI — Python re-implementation
  (MIT, repo last updated 2023; supports `ON_PLAYER_JOINING` with official stats).
  Staleness vs game 2.2.5 is a compatibility risk, but it is the shortest path in
  our language.
- `Bluscream/battlebitapirunner-modules` — community modules, including a
  `Logger.cs` that prints `"Name (SteamID)"` and Steam ban checks. No license file;
  use as a reference, not copied code.
- `BattleBit-Community-Servers/Battlebit-Community-Server-Launcher` (Rust, 2024)
  and `battlebit-server-docker` / `pterodactyl-battlebit` for hosting.

Caveat: this only works on **whitelisted community servers running the API**.
Official matchmaking servers expose no such API. If you run or partner with one
community server, you get background stats + SteamIDs for everyone who joins it.

## Session logging without a server: what does not work

| Approach | Result |
|---|---|
| `publicapi.battlebit.cloud/Servers/GetServerList` | 21 live servers, fields only `Name/Map/Players/QueuePlayers/MaxPlayers/...`; no player list, no IP |
| Valve `A2S_PLAYER` query | Names and scores only; SteamID is not part of the protocol |
| BattleMetrics | BattleBit server stats exist, but the API returns 403 "subscription required"; web pages block scripted fetches. Player history is tied to connected servers/SteamID.com; not a free arbitrary-ID source |
| BattleBit `Player.log` | Checked locally at `%USERPROFILE%\AppData\LocalLow\BattleBitDevTeam\BattleBit\Player.log`; it logs the Steam ticket/token exchange and engine noise, no lobby IDs |
| Steam Web API | No lobby/party membership for BattleBit; identity, profile, hours, bans only |
| Client memory / mods (BitMod etc.) | Would need to read the game under EAC; not recommended |

So for official lobbies there is no sanctioned SteamID source. The clean session
logger is a server plugin on a server you control, or cooperation from a server
owner who already runs BattleBitAPIRunner.

## Steam identity, profiles, and hours

A free **Steam Web API key** (<https://steamcommunity.com/dev/apikey>) unlocks the
official Web API:

- `ISteamUser/GetPlayerSummaries/v2` — up to 100 IDs per call; reliable name,
  avatar, state, profile URL (better than scraping the profile HTML).
- `IPlayerService/GetOwnedGames/v1` — `playtime_forever` for app `671860`, which
  gives BattleBit hours when the profile is public. This directly serves the
  "players with high hours" idea.
- `ISteamUser/GetPlayerBans/v1` — VAC/game/community bans.

Python wrappers: `steamapi`, ValvePython `steam`, `steamid` (ID conversion).

Steam OpenID packages exist (`steamsignin` 1.1.3, `flask_openid_steam` 1.3.1,
`steam-openid` 1.0.6, `pallets-eco/flask-openid`), but our own
`steam_openid.py` already does state-checked verification with zero dependencies;
no migration needed.

## BattleBit stats projects and data

- **`THEROCKSSS/battlebit-stats`** (ours) — Node 22 + `node:sqlite`, one Express
  dependency; polls the leaderboard and server list, stores append-on-change
  history, charts players/clans/servers, dark editorial UI, hardened container,
  admin CLI. Roadmap explicitly excludes accounts/logins and per-match stats
  ("the public API exposes no per-match endpoint"). It is the strongest existing
  frontend/poller to reuse or link to.
- `alexcroox/battlebit-stats` (Nuxt, 15 stars) — maps, weapons, leaderboards,
  battlebitstats.com. Content is from 2023, no license file; useful as a reference
  for map tiles/weapon presentation, not code to copy.
- `superyu1337/battlebit-stats` (Rust/Yew), `henryecw/battlebit-stats` — server
  statistics, small.
- `affectioned/ExtractBBRWeaponStats` (MIT, 2023) — extracts weapon stats from the
  Unity assets; stale at 2.2.1 but the workflow is reusable for a weapon page.
- `TheGreenPlanet/battlebit-dumper` — Rust offset dumper; cheat-adjacent, no
  license, not for this project.
- `battlebit.wiki.gg`, `battlebit.community` — map/weapon/server reference data.
- `gametools.network` — free community API; has a `/battlebit/serverarray/`
  population-history endpoint (needs parameters; docs at
  <https://api.gametools.network/docs>). Optional alternative to polling the
  server list yourself.

None of these sites offers arbitrary lifetime stats by SteamID — the API
restriction above is why. They show leaderboard values or server populations.

## Packaging, updates, and signing

- Current PyInstaller onefile build works but is unsigned. **SignPath Foundation**
  (<https://signpath.org>) gives free code signing for OSS projects, with a
  `submit-signing-request` GitHub Action; this removes the SmartScreen warning and
  links the binary to the public repo.
- **Velopack** has a Python SDK (<https://docs.velopack.io/getting-started/python>)
  with installers and delta auto-updates. It requires PyInstaller `--onedir` (not
  our current `--onefile`) and the .NET SDK for the `vpk` CLI. A real upgrade, but
  a larger build change.
- **tufup** (MIT, 149 stars, active) — TUF-signed auto-updates for standalone
  Python apps; stronger security model, more setup.
- `distromate/pyinstaller-auto-update` (MIT, active 2026) — simple GitHub
  Releases-based updater; small project, few stars.
- **Briefcase** (BeeWare) can produce an MSI installer; a packaging rewrite.
- Practical low-effort path: keep onefile + zip, add SignPath signing and a
  "check GitHub Releases for a newer version" button/dialog.

## Web, ops, and security

- `Flask-Limiter` — Redis/in-memory rate limits with standard headers; replaces
  our hand-rolled limiter if the site ever runs multiple workers.
- `Flask-Login`, `Flask-WTF` — session/auth/CSRF helpers; our code is small enough
  that migration is optional.
- `Flask-Migrate`/Alembic — schema migrations; our additive migrations work but
  are manual.
- `sentry-sdk[flask]` — error tracking (self-hosted Sentry or SaaS) for the
  collector/site.
- `structlog` — structured logs.
- `Litestream` (v0.5, active) — continuous SQLite WAL replication to S3/file;
  ideal for `profiles.db` backups without a DB server.
- `Uptime Kuma` or Healthchecks.io — external uptime checks for the tailnet site.
- `Caddy` (automatic TLS) or Cloudflare Tunnel if the site ever goes public;
  Tailscale Serve remains the private default.
- `CodeQL`, Dependabot/Renovate, `pip-audit`, `bandit`, `Ruff`, `mypy`,
  `pre-commit` — CI hardening.
- `pytest` + `responses`/`respx` + `Playwright` — richer tests/e2e than unittest +
  manual browser checks.

## What I would adopt, in order

1. **Get a Steam Web API key.** Low effort, immediate value: verified ownership,
   BattleBit hours (`GetOwnedGames`), reliable avatars/names, ban flags. This is
   the missing piece for "high-hours players".
2. **Decide on a community server.** If you will run one or partner with an owner,
   build the join-stats bridge: on `ON_PLAYER_JOINING`, map `PlayerStats` to the
   `.bbrstats` schema and POST to a server-token endpoint. That removes the
   per-player collector for everyone on that server and provides the session
   SteamID log. It is the only sanctioned way to do both.
3. **If staying official-only:** keep the per-account collector; use the Steam
   directory for identity; do not attempt client-memory session logging under EAC.
4. **Reuse `battlebit-stats`** for leaderboards/server history/charts; link it from
   the profile site instead of rebuilding those views.
5. **Sign the Windows build** with SignPath; add a release update check. Consider
   Velopack only if switching to `--onedir` is acceptable.
6. **Add Litestream + Sentry + Flask-Limiter** when the site leaves one machine or
   gains real users.
