# AGENTS.md

## What this repo is

Two deliverables that share one profile format:

1. `src/bbr_ripper/` — Windows ripper. Steam ticket → official BattleBit API →
   `.bbrstats` JSON + `.txt`.
2. `server/` — Flask site. Accounts, uploads, public/private profiles, leaderboard.

`docs/FORMAT.md` is the contract between them. Change it before changing either side.

## Rules

- Never modify BattleBit files, the game process, or EAC. The ripper only uses
  Steam's local API and the official HTTPS API.
- Preserve raw bytes. A decode failure must never fabricate values; add a warning and
  keep `raw_b64` / `trailing_hex`.
- Do not commit personal `.bbrstats` files, Steam IDs, or `server/data/`.
- Do not redistribute Valve's `steam_api64.dll`. The app loads the user's installed
  copy.
- The executable is a network client for a private game API. Keep the handshake and
  user agent aligned with the game build documented in `docs/FORMAT.md`.
- Site uploads are one Steam ID → one account. Private profiles return 404 to
  non-owners.

## Verify

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m bbr_ripper --probe
python -m bbr_ripper --out out --verbose
```

Server:

```powershell
cd server
.venv\Scripts\waitress-serve --host 127.0.0.1 --port 8099 app:app
```

Then exercise register → upload → profile → private → 404 → public.

## Build

`build\build.ps1` builds both exes and `dist\BattleBitStatRipper-windows-x64.zip`.

## CI

`.github/workflows/ci.yml` runs the ripper tests on Windows and the server tests on
Linux for every push and PR. `.github/workflows/release.yml` builds the executables
and attaches them to a GitHub release when a `v*` tag is pushed; see
`docs/RELEASING.md`.
