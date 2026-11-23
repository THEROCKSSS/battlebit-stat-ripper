# Profile file format & API wire format

## Export file: `.bbrstats`

UTF-8 JSON, schema `bbr-profile/1`. Top-level keys:

| Key | Meaning |
|---|---|
| `schema` | `"bbr-profile/1"` |
| `captured_at` | ISO-8601 UTC timestamp |
| `tool` | Ripper name/version |
| `source` | API host, endpoint, game build, raw byte count |
| `player` | `steam_id`, Steam `persona_name`, optional API `username` |
| `progress` | 44 decoded profile fields (snake_case) |
| `derived` | K/D, W/L, accuracy, KPM, SPM, hours, full rank, per-round averages |
| `classes` | Leader/Assault/Medic/Engineer/Support/Recon kills, score, playtime |
| `weapons` | 76 per-tool records: `tool_id`, `name`, `kills`, `extra`, `total` |
| `achievements` | `u32` achievement IDs (normally empty in the live response) |
| `clan` | `in_clan`, `clan_id`, `clan_rank` |
| `flags` | `is_banned`, `is_timed_out` |
| `role` | Role enum (low 32 bits of the serialized 64-bit value) |
| `challenge` | Weekly challenge presence, byte length, base64 payload |
| `selections_b64` | Packed loadout/wearings blob, base64 |
| `inventory_b64` | Inventory blob (normally empty) |
| `raw` | `len`, `sha256`, base64 of the exact response, trailing hex |
| `decode` | `schema_ok`, warnings |

The raw response is always embedded. A future parser can re-decode an old file
without the user re-ripping.

## Steam → API handshake

The app uses the game's own `steam_api64.dll` to request an auth session ticket
for app `671860`, then:

```
POST /Tokens/GetToken
User-Agent: b32bf642b285ca1f0663688e7078f892dc2d0843
Content-Length: 486 (typical)

u64   SteamID
u16   len(ticket_hex)
bytes ticket_hex (ASCII)
u64   1
```

Response (80 bytes typical):

```
u8    0x01
u64   session
8     unknown (varies)
u32   unknown (0xA4 in verified samples)
u16   token length
bytes token (ASCII hex)
u16   build length
bytes build ("Production 2.2.5 Hotfix")
```

Then:

```
POST /Player/GetStats

u64   SteamID
u64   session
```

The response is the binary profile described below.

## `/Player/GetStats` response

All integers are little-endian.

```
u8      lead = 0x01
u64     SteamID
u32     field_count = 44
u32[44] PlayerStats.PlayerProgess fields
u16     tools_payload_bytes
repeat  tools_payload_bytes / 10:
    u16 tool_id
    u32 kills
    u32 extra
u16     achievements_payload_bytes
repeat  bytes / 4:
    u32 achievement_id
u16     selections_bytes
bytes   selections blob (packed loadouts)
u16     inventory_bytes
bytes   inventory (normally empty)
u8      in_clan
if in_clan:
    u64 clan_id
    u8  clan_rank
u8      is_banned
u8      is_timed_out
u16     weekly_challenge_bytes
bytes   weekly challenge payload (absent when 0)
u64     role (low 32 bits meaningful)
u16     username length
bytes   username UTF-8 (may be absent / 0 in live responses)
...     trailing bytes (preserved as hex)
```

### The 44 fields, in order

| # | Key | In-game label |
|---:|---|---|
| 0 | `kills` | Kills |
| 1 | `leader_kills` | Leader kills |
| 2 | `assault_kills` | Assault kills |
| 3 | `medic_kills` | Medic kills |
| 4 | `engineer_kills` | Engineer kills |
| 5 | `support_kills` | Support kills |
| 6 | `recon_kills` | Recon kills |
| 7 | `deaths` | Deaths |
| 8 | `wins` | Wins |
| 9 | `losses` | Losses |
| 10 | `friendly_shots` | Friendly shots |
| 11 | `friendly_kills` | Friendly kills |
| 12 | `revived` | Times revived |
| 13 | `revived_teammates` | Teammates revived |
| 14 | `assists` | Assists |
| 15 | `prestige` | Prestige |
| 16 | `rank` | Rank |
| 17 | `exp` | Rank XP |
| 18 | `shots_fired` | Shots fired |
| 19 | `shots_hit` | Shots hit |
| 20 | `headshots` | Headshots |
| 21 | `objectives_completed` | Objectives completed |
| 22 | `hp_healed` | HP healed |
| 23 | `road_kills` | Road kills |
| 24 | `suicides` | Suicides |
| 25 | `vehicles_destroyed` | Vehicles destroyed |
| 26 | `vehicles_hp_repaired` | Vehicle HP repaired |
| 27 | `longest_kill_m` | Longest kill (m) |
| 28 | `playtime_seconds` | Playtime |
| 29 | `leader_playtime_seconds` | Leader playtime |
| 30 | `assault_playtime_seconds` | Assault playtime |
| 31 | `medic_playtime_seconds` | Medic playtime |
| 32 | `engineer_playtime_seconds` | Engineer playtime |
| 33 | `support_playtime_seconds` | Support playtime |
| 34 | `recon_playtime_seconds` | Recon playtime |
| 35 | `leader_score` | Leader score |
| 36 | `assault_score` | Assault score |
| 37 | `medic_score` | Medic score |
| 38 | `engineer_score` | Engineer score |
| 39 | `support_score` | Support score |
| 40 | `recon_score` | Recon score |
| 41 | `total_score` | Total score |
| 42 | `ammo_supplied` | Ammo supplied |
| 43 | `weekly_challenges_completed` | Weekly challenges completed |

### Per-tool records

Each record is 10 bytes:

```
u16 tool_id
u32 kills
u32 extra
```

`kills` sums to the global `KillCount` in every verified capture, so it is the
kill count credited to that tool (weapons, vehicles, explosives). `extra` is a
second counter serialized by the same `Pint` type; it is preserved and surfaced
as `extra` / `total` rather than guessed. Tool IDs map to the game's
`Tools.AllTools` array; the names in `src/bbr_ripper/tool_names.py` were
extracted from the 2.2.5 `resources.assets` `Tools` asset (`path_id 37929`).

### Verification values (2026-11-23)

```
SteamID <verified test account>
raw length 2590 (or 2678 when weekly challenge data is present)
Kills 3873, Deaths 8073, Rank 200, Prestige 1,
TotalScore 15865086, PlayTimeSeconds 920278
Tool sum 3873, 76 records
```

The 88-byte difference is the weekly-challenge payload; the challenge prefix is
a byte length, not a boolean. Both lengths decode cleanly.
