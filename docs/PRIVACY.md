# Privacy

## What the ripper sends

Only to `https://api.battlebit.cloud` (the game's own master server):

1. Your Steam ID.
2. A short-lived Steam auth session ticket for BattleBit Remastered (app `671860`).
3. The session value returned by `/Tokens/GetToken`.

The ticket is held in memory for the length of the run and cancelled when the app
exits. The ripper does not store it, log it, or send it anywhere else. It does not
read the game's memory, patch files, or interact with Easy Anti-Cheat.

## What the ripper writes

`Documents\BattleBit Stats Ripper\`:

- `.bbrstats` — the decoded profile plus the raw API response. This includes your
  Steam ID, persona name, stats, clan ID, and loadout blob. Treat it as public
  information; anyone with the file can read it.
- `.txt` — the same data in a human-readable sheet.

The ripper itself does **not** upload anything. You choose whether to upload the
file to a stats site.

## What the website stores

If you use the included Flask site:

- Account: username, scrypt password hash, creation timestamp. No email.
- Profile: the uploaded `.bbrstats` JSON, keyed by Steam ID and linked to one
  account, plus a public/private flag, optional display name, bio, portrait
  filename, and social links.
- Clan: name, tag, description, join mode, crest filename, colour, social links,
  owner, roster, and pending join requests. Clan pages and rosters are public;
  private profiles show as "Private record" and their stats are excluded from
  clan totals.
- Media: portraits and clan crests are re-encoded to WebP and stored under
  `server/data/uploads/`. EXIF metadata is stripped.
- Session: a signed cookie containing your user ID and a CSRF token.
- Server log: standard request logs may contain IP addresses depending on how you
  run it (Waitress/reverse proxy).

The site does not call the BattleBit API. It only stores and displays uploaded
files. Private profiles return 404 to everyone except their owner.

## Deleting data

- Ripper: delete the two files from `Documents\BattleBit Stats Ripper\`.
- Site: **Remove** on the account page deletes the profile row and its portrait.
  Disbanding a clan deletes the clan, roster, requests, and crest. Account
  deletion is not exposed in the v1 UI; delete the user row from
  `server/data/profiles.db` or remove the database file for a fresh start.

## Third parties

- BattleBit Remastered / api.battlebit.cloud — see the game's own privacy terms.
- Steam — the local client is used to issue the auth ticket.
- The site host — whoever runs the Flask server sees uploaded profiles and account
  data.

Not affiliated with BattleBit Remastered, Steam, or Valve.
