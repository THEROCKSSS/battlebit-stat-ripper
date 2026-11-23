# Replication guide

This is the complete path from a clean Windows machine to a working profile file.
It is written so another agent or engineer can rebuild the ripper without the
original session, and so a future game update can be diagnosed quickly.

## 0. What is being replicated

The BattleBit Remastered client, when signed in through Steam, asks the local
Steam client for an auth session ticket (app `671860`), exchanges it with
`https://api.battlebit.cloud/Tokens/GetToken`, then posts the returned 8-byte
session to `/Player/GetStats`. The response is a binary profile.

The ripper does the same three steps from a separate process. It does **not**
read game memory, patch files, or interact with EAC.

Verified against game build `Production 2.2.5 Hotfix`, 2026-11-23.

## 1. Locate the game and its Steam library

1. Read `HKCU\Software\Valve\Steam\SteamPath` and
   `HKLM\SOFTWARE\WOW6432Node\Valve\Steam\InstallPath`.
2. Parse `<SteamPath>\steamapps\libraryfolders.vdf` and collect every `"path"`.
3. For each library, check
   `<library>\steamapps\common\BattleBit Remastered\BattleBit.exe` and
   `BattleBit_Data\Plugins\x86_64\steam_api64.dll`.
4. Do not copy or redistribute `steam_api64.dll`; load the user's installed copy.

Implementation: `src/bbr_ripper/steam.py::find_battlebit`.

## 2. Get a Steam auth ticket

Load the game's `steam_api64.dll` with `ctypes` (64-bit Python required):

| Export | Use |
|---|---|
| `SteamAPI_Init` | initialise Steamworks |
| `SteamAPI_SteamUser_v020` | get `ISteamUser*` |
| `SteamAPI_ISteamUser_GetSteamID` | verify the signed-in user |
| `SteamAPI_ISteamUser_GetAuthSessionTicket` | issue the ticket |
| `SteamAPI_ISteamUser_CancelAuthTicket` | release it after the run |
| `SteamAPI_SteamFriends_v017` | optional persona name |
| `SteamAPI_ISteamFriends_GetPersonaName` | optional persona name |

Critical detail: `SteamAPI_Init` reads `steam_appid.txt` from the **current working
directory**. The ripper `chdir`s to a temp directory containing `671860`, then
restores the original directory when done.

`GetAuthSessionTicket` writes a binary ticket to an 8192-byte buffer and returns a
handle and length. The verified ticket was 234 bytes. Never log the ticket; a
SHA-256 prefix is enough for correlation.

Implementation: `src/bbr_ripper/steam.py::SteamSession`.

## 3. Exchange the ticket

TLS to `api.battlebit.cloud:443` with SNI, no auth header, and the game's user
agent:

```
User-Agent: b32bf642b285ca1f0663688e7078f892dc2d0843
```

### 3a. `POST /Tokens/GetToken`

Request, little-endian:

```
u64  SteamID
u16  len(ticket_hex)
...  ticket_hex (ASCII, lowercase hex)
u64  1
```

The typical body is 486 bytes: 8 + 2 + 468 + 8.

Response (80 bytes typical):

```
u8   0x01
u64  session
8    unknown, varies per run
u32  unknown (0xA4 in verified samples)
u16  token length
...  token (ASCII hex, 32 chars)
u16  build length
...  build UTF-8 ("Production 2.2.5 Hotfix")
```

Do not log the response head; it contains the session and token. The stats request
does not use the token header; it uses the 8-byte session.

### 3b. `POST /Player/GetStats`

```
u64 SteamID
u64 session
```

16 bytes total. The response is 2,590 bytes, or 2,678 bytes when the weekly
challenge payload is present. Both are valid.

Implementation: `src/bbr_ripper/api.py`.

## 4. Decode the profile

Full byte layout and the 44-field table: [`FORMAT.md`](FORMAT.md).

Key checks:

- Lead byte `0x01`, SteamID at offset 1, field count `44` at offset 9.
- 44 × `u32` starting at offset 13.
- Tool array: `u16` byte length, then 10-byte records
  `{u16 tool_id, u32 kills, u32 extra}`.
- Achievements: `u16` byte length, then `u32` IDs.
- Selections: `u16` byte length, packed loadout blob.
- Inventory: `u16` byte length (normally 0).
- Clan, flags, **weekly challenge as a `u16` byte length** (not a boolean),
  role `u64`, optional username string, trailing bytes.
- Preserve the raw response in the export. If the layout changes, stop and keep
  the bytes; do not invent values.

Verified values: 3,873 kills, 8,073 deaths, 200 rank, 15,865,086 total score,
920,278 playtime seconds, 76 tool records, tool kill sum = 3,873.

Implementation: `src/bbr_ripper/decoder.py`.

## 5. Map tool IDs to names

BattleBit assigns each `ToolItem` its index in `Tools.AllTools` at load time. That
index is the `tool_id` in the per-tool records.

1. Open `BattleBit_Data/resources.assets` with UnityPy.
2. Find the `MonoBehaviour` named `Tools` (path_id 37929 in 2.2.5).
3. Parse the serialized object:
   - header 28 bytes + name (4-byte length + bytes, padded to 4).
   - two PPtrs (12 bytes each): `EmptyGun`, `EmptyGadget`.
   - `u32` array count, then `count × 12-byte` PPtrs.
4. Resolve each PPtr `path_id` to the object's `peek_name()`.
5. Write `src/bbr_ripper/tool_names_generated.py`; the hand-written display
   overrides live in `src/bbr_ripper/tool_names.py`.

One command:

```powershell
pip install UnityPy
python tools/extract_tool_names.py
```

Known sample: 34 = `0_Rpg7_Heat_Explosive` (displayed `RPG-7 HE`), 17 = `SCAR-H`,
119 = `HermitMilitaryArmed`, 116 = `LittlebirdMilitaryArmed`.

## 6. Export, history, and logs

- `.bbrstats` JSON: schema `bbr-profile/1`, decoded fields, weapons, raw bytes.
- `.txt`: human-readable stat sheet.
- History: SQLite at `%LOCALAPPDATA%\BBR Stats Ripper\history.sqlite3`, one row
  per unique `(steam_id, raw_sha256)`.
- Logs: `%LOCALAPPDATA%\BBR Stats Ripper\logs\run-<id>.log` plus a JSON summary
  in `logs\runs\<id>.json`.
- Diagnostics: `%LOCALAPPDATA%\BBR Stats Ripper\diagnostics\diagnostics-<id>.txt`.
  The ticket is never written; the Steam ID and public stats are.

Implementation: `src/bbr_ripper/exporter.py`, `history.py`, `logging_setup.py`.

## 7. Verify

Run the ripper against the signed-in account and compare with the in-game
Profile screen:

| Stat | Expected | Source |
|---|---:|---|
| Kills | 3,873 | in-game screen |
| Deaths | 8,073 | in-game screen |
| Hours | 255.6 | 920,278 s |
| Total score | 15,865,086 | in-game screen |
| Wins / losses | 333 / 368 | in-game screen |
| Revived / revives | 1,091 / 1,003 | in-game screen |
| Objectives | 760 | in-game screen |
| Vehicles destroyed | 439 | in-game screen |
| Vehicle repairs | 374,435 | in-game screen |

Also check:

- `sum(weapons[].kills) == progress.kills`
- `rounds = wins + losses`
- each class `kills` sums to the global kills
- the raw response length is 2,590 or 2,678
- `raw.sha256` matches the embedded bytes

## 8. Package

```powershell
build\build.ps1
```

Produces `dist\BattleBitStatRipper.exe`, `dist\bbr-ripper-cli.exe`, and
`dist\BattleBitStatRipper-windows-x64.zip`.

## 9. If the game updates

1. Run `bbr-ripper --diagnose`; note the game build and response size.
2. Run a normal rip with `--verbose`; the log records the HTTP status, byte count,
   and SHA-256.
3. If `BBR-D001` (layout changed), compare the new response with the old one and
   update `decoder.py` + `FORMAT.md`. Never guess; add a test with a synthetic
   payload.
4. Re-run `tools/extract_tool_names.py` to refresh names.
5. Re-verify against the in-game screen and bump the version.

## 10. Security rules

- The ticket is for the signed-in user only; do not add a "rip any Steam ID" mode
  without a server-side authorization design.
- Never log the ticket or token response body.
- Never modify the game, its files, or EAC.
- The `.bbrstats` file contains the Steam ID and public stats; treat it as public.
