# Server

Flask + SQLite site for uploading and showing `.bbrstats` profiles, player
records, and clans.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\waitress-serve --host 127.0.0.1 --port 8099 app:app
```

## Deploy

The waitress command above serves loopback only. To reach it from other devices
on the tailnet:

```powershell
tailscale serve --bg --https=8552 http://127.0.0.1:8099
tailscale serve --https=8552 off   # reverse it
```

The mapping survives reboots; the waitress backend does not, so restart it after
a restart. Set `BBR_HTTPS=1` when the site is only reached over TLS so the
session cookie is marked `Secure`.

## What it includes

- Accounts with CSRF-protected register/login/logout and session cookies.
- Steam OpenID sign-in; first sign-in creates the account from the public Steam
  profile, and an existing capture for that Steam ID is transferred to it.
- Steam player directory: any Steam ID, profile link, or vanity can get a page with
  persona name, real name, summary, avatar, avatar frame, level, status, location,
  and animated background. Stats still require that player's own capture.
- Collector tokens: per-account bearer tokens (stored hashed) for the headless
  `bbr-ripper --watch` loop; `POST /api/captures` validates and upserts the capture,
  bound to the token's Steam ID.
- Profile uploads (`.bbrstats` file or pasted JSON), public/private visibility,
  leaderboard, raw JSON view.
- Profile presentation: portrait upload, display name, bio, six social link
  types, clan chip, and owner edit page.
- Clans: public directory, create, open/request/closed join modes, roster,
  aggregate public stats, crest upload, clan socials, join requests,
  approve/decline, promote/demote, kick, leave, and disband.
- Image uploads are decoded, centre-cropped, resized to 512 px, and re-encoded
  as WebP (max 6 MB, max 24 MP) before being served from
  `/media/avatars/...` or `/media/clans/...`.
- Ripper download is a first-class page at `/download` with version, file size,
  SHA-256, direct `/download/windows` and `/download/zip` routes, and run/error
  guidance.
- `/healthz` reports profile and clan counts.

## Data

- `data/profiles.db` — SQLite database. New columns/tables are migrated in place.
- `players` — public Steam identity rows (`steam_id`, persona, summary, media paths,
  level, status); separate from captured `profiles`.
- `data/secret_key` — generated session key.
- `data/uploads/avatars/` and `data/uploads/clans/` — WebP media.
- `data/uploads/steam/` — cached Steam avatars, avatar frames, and backgrounds.
- `upload_tokens` — collector token hashes, label, bound Steam ID, last use, revoke
  time. The plaintext token is shown once and never stored.
- `BBR_SERVER_DATA` overrides the data directory.
- `BBR_SECRET_KEY` overrides the generated session key.
- `BBR_HTTPS=1` marks the session cookie `Secure` behind TLS.
- `BBR_PUBLIC_URL` sets the absolute origin used for Steam OpenID return URLs.
- `BBR_DOWNLOAD` / `BBR_DOWNLOAD_ZIP` override the exe and zip paths.

## Rate limits

Single-process, in-memory sliding windows. Move to Redis if the site is ever run
behind multiple workers.

| Action | Limit |
|---|---|
| Register | 5 / hour / IP |
| Steam sign-in start | 20 / 10 min / IP |
| Steam player lookup | 6 / hour / IP |
| Collector upload | 10 / hour / account |
| Login | 30 attempts / 10 min / IP, plus 8 failures / 10 min / IP+username |
| Upload capture | 10 / hour / account |
| Profile edit / portrait | 20 / hour / account |
| Create clan | 3 / day / account |
| Join/request clan | 8 / hour / account |
| Clan settings / crest | 12 / hour / account |
| Clan approve/decline/promote/kick | 60 / hour / account |
| Disband clan | 3 / hour / account |

Rate-limited responses render `429.html` and send `Retry-After`.

## Collector API

`POST /api/captures` with `Authorization: Bearer bbr_...` and the capture JSON.
Returns `{ok, steam_id, persona, url}`. Errors: 400 invalid capture, 401 missing or
revoked token, 403 token bound to a different Steam ID, 409 record owned by another
account, 429 rate limit. Tokens are created under `/me` and stored as SHA-256.
Background usage: `docs/COLLECTOR.md`.

## Tests

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests cover upload validation, private visibility, CSRF, avatar/social editing,
clan create/join/approve, clan promotion/kick, clan rate limiting, social URL
validation, and the download routes.
