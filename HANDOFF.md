# HANDOFF

## State (2026-11-23, v0.2.0)

Working, locally verified:

- `src/bbr_ripper` — Steam ticket bridge, official API client with retries,
  exact GetStats decoder, JSON/TXT exporter, CLI, dark Tk GUI.
- **Durable logs** — `%LOCALAPPDATA%\BBR Stats Ripper\logs\run-<id>.log` plus
  `logs\runs\<id>.json` with environment, steps, durations, and errors.
- **Diagnostics** — one-click / `--diagnose` Steam + DNS + TLS report at
  `%LOCALAPPDATA%\BBR Stats Ripper\diagnostics\diagnostics-<id>.txt`. The auth
  ticket is never written; token response bodies are redacted.
- **Local history** — `history.sqlite3`, one row per unique raw response,
  automatically appended on every run; CSV export via `--history-csv`.
- **Stable error codes** — `BBR-S001`…`BBR-X002` with cause + fix in the GUI and
  CLI; `docs/TROUBLESHOOTING.md` maps every code.
- **Run-anytime task** — `scripts/install_startup_task.ps1` registers a per-user
  logon + every-N-hours task; uninstall script included.
- `dist/BattleBitStatRipper.exe` — windowed build.
- `dist/bbr-ripper-cli.exe` — console build.
- `server/` — Flask site with accounts, uploads, public profiles, private
  visibility, leaderboard, raw JSON, download page.
- **Private remote access** — Tailscale Serve publishes the site at
  `https://owens-pc-vpn.tailff2683.ts.net:8552` (tailnet only) proxying
  `http://127.0.0.1:8099`; verified over the tailnet URL on 2026-11-23.
- **Public repo + CI** — `https://github.com/THEROCKSSS/battlebit-stat-ripper`
  (MIT). GitHub Actions runs the ripper suite on Windows and the server suite on
  Linux for every push/PR; `.github/workflows/release.yml` builds the exes on a
  `v*` tag and attaches them to the release. `main` requires both checks to merge
  (admins can still bypass).
- **v0.2.0 release published** — three assets built by CI; the downloaded CLI
  reports `bbr-ripper 0.2.0` and the zip lists the expected 8 files.
- **Site feature pass** — clans (directory, create, open/request/closed join,
  roster, aggregate public stats, crests, socials, requests, promote/kick,
  leave/disband), profile portraits/bios/socials, inline SVG icon set, rate
  limits, and a first-class ripper download page at `/download` with direct
  `/download/windows` and `/download/zip` routes.
- **28 tests passing** (ripper: 8 core + 4 error + 2 log + 2 history; server: 12).

Live verification:

- Real capture of the verified Steam account on 2026-11-23.
- Every headline number matches the in-game profile screen (kills 3,873; deaths
  8,073; 255.6 h; 15,865,086 score; 333/368; 1,091/1,003 revives; 760 objectives;
  439 vehicles; 374,435 repairs).
- Tool IDs mapped from the game's `Tools.AllTools` asset; top entries: RPG-7 HE
  1,259 kills, Hermit (Armed) 288, SCAR-H 239, Littlebird (Armed) 211.
- Server flow exercised in a real browser: register → upload → public profile →
  private → anonymous 404 → public again.
- Site v0.2 features exercised in a browser: profile portrait/socials render,
  a clan created through the real form, clan join/approve tested server-side,
  and all routes audited at 1440 / 768 / 390 px with no horizontal overflow.
- Rate limits verified: clan create returns 429 after the configured count;
  `Retry-After` is sent.
- Layout audited at 1440 px and 390 px; no horizontal overflow; mobile header
  padding fixed.
- CLI `--diagnose` verified: Steam OK, DNS OK, TLS OK (bare GET 520 is normal).
- Real rip writes log, summary, history row, and both export files.
- `tools/extract_tool_names.py` verified against the installed game; reproduces
  133 tool IDs.

## Commands

```powershell
# CLI from source
$env:PYTHONPATH = "src"
python -m bbr_ripper --out out --verbose
python -m bbr_ripper --diagnose --verbose
python -m bbr_ripper --history-csv history.csv

# tests
python -m unittest discover -s tests -v
cd server; .venv\Scripts\python.exe -m unittest discover -s tests -v

# site
cd server
.venv\Scripts\waitress-serve --host 127.0.0.1 --port 8099 app:app

# private tailnet access (persists across reboots; reverse with ... off)
tailscale serve --bg --https=8552 http://127.0.0.1:8099
tailscale serve --https=8552 off

# rebuild Windows apps
build\build.ps1

# optional automatic runs
.\scripts\install_startup_task.ps1 -Hours 6
```

## Site state (2026-11-23)

- Flask site is running locally at `http://127.0.0.1:8099` from `server/` and is
  reachable inside the tailnet at `https://owens-pc-vpn.tailff2683.ts.net:8552`.
- Existing `server/data/profiles.db` was backed up and migrated in place:
  `display_name`, `bio`, `avatar_path`, `social_json` added; `clans`,
  `clan_members`, `clan_requests` created.
- Ripper download is a page plus direct files:
  `/download`, `/download/windows` (alias `/download/exe`), `/download/zip`.
- Clans: `/clans`, `/clans/new`, `/c/<slug>`, `/c/<slug>/manage`.
- Profile editing: `/p/<steamid>/edit` (owner only).
- Media: `/media/avatars/<file>`, `/media/clans/<file>` (WebP, forced MIME).
- Rate limits are in-memory and single-process; table in `server/README.md`.
- Browser verification covered home, clans, clan, profile, download, account,
  and manage pages at 320/390/768/1440 px with no horizontal overflow.

## Next

1. Decide whether the site gets a public URL (opt-in). The code now lives at
   `github.com/THEROCKSSS/battlebit-stat-ripper`; tailnet access is already live.
2. Link the release from `familiar/battlebit-arsenal` on Forgejo (separate repo,
   needs its own write). The site's `/download` page already links to GitHub
   Releases.
3. Optional polish: signed Windows binary, auto-update check, a direct "upload to
   site" button in the GUI (needs an API key/session design), history chart in the
   GUI.
4. If the game updates, follow `docs/REPLICATION.md` section 9: re-run diagnostics,
   compare raw sizes, re-extract tool names, add a synthetic test, bump version.
