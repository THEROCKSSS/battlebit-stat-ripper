# Steam sign-in and player cards

The site can build a player page for any Steam account without a Steam Web API
key. It uses two public sources and caches the images locally.

## Sign-in (OpenID 2.0)

1. `/auth/steam` stores a random `state` in the session and redirects to
   `https://steamcommunity.com/openid/login` with `checkid_setup`.
2. Steam redirects back to `/auth/steam/callback?state=...` with `openid.*`
   parameters. The `state` must match the session value.
3. The server POSTs those parameters back with `check_authentication` and accepts
   the sign-in only when Steam answers `is_valid:true` and the claimed ID is
   `https://steamcommunity.com/openid/id/<SteamID64>`.
4. On first sign-in a local user row is created with a random unusable password.
   Later sign-ins reuse the `users.steam_id` row.
5. If a capture record already exists for that Steam ID (uploaded from a local
   password account), it is transferred to the Steam-authenticated account —
   Steam has proven ownership of the ID.

`BBR_PUBLIC_URL` must be the site's absolute origin so the `return_to` and realm
match the host the browser is on, for example:

```powershell
$env:BBR_PUBLIC_URL = "https://owens-pc-vpn.tailff2683.ts.net:8552"
```

No password, token, or Steam Guard code is ever sent to this site.

## Profile data

| Field | Source |
|---|---|
| Persona name, real name, summary | `steamcommunity.com/profiles/<id>/?xml=1` |
| Avatar (full), location, member since | same XML |
| Level, online status | profile HTML header |
| Avatar frame | `profile_avatar_frame` picture in the profile HTML |
| Animated background poster | `profile_animated_background` video poster |

Private profiles still expose name, avatar, and frame to anonymous visitors; the
summary may be empty. If the XML has `<error>`, the lookup is rejected.

Only images from `*.steamstatic.com` and `*.steamusercontent.com` are downloaded.
Each file is capped at 8 MB and stored under `server/data/uploads/steam/` as
`<steam_id>-avatar.*`, `-frame.*`, `-background.*`. Media is served by
`/media/steam/<file>` with a MIME type derived from the extension.

## Player directory

`/players` lists `players` rows and accepts a SteamID64, a `/profiles/` URL, a
vanity name, or an `/id/` URL. Additions are rate limited to 6 per hour per IP.

A Steam-only page shows the name, avatar, frame, background, level, status,
summary, location, and a Steam link. BattleBit stats are not public: they appear
only after that Steam account's own capture is uploaded. No stats are invented
for a player who has not captured them.

## Seeding

```powershell
python scripts/seed_players.py
python scripts/seed_players.py 76561198028883348
```

The script upserts players and downloads their media. It is safe to re-run; it
refreshes names, status, level, and media without touching captures.

## Tests

```powershell
cd server
.venv\Scripts\python.exe -m unittest tests.test_steam_units -v
```

The tests cover XML/HTML parsing, vanity resolution, OpenID URL construction, and
assertion verification with a mocked Steam response. No test makes a live request.
