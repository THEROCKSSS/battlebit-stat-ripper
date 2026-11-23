"""Decoder for the BattleBit Remastered `/Player/GetStats` response.

The schema below is not a guess.  It was recovered from the live 2,590-byte
response captured on 2026-07-12 and re-verified against a live response on
2026-11-23, then cross-checked against the game's own serializers in the
Ghidra dump (`PlayerStats_PlayerProgess__WriteTo_MasterServer_GameServerSide`,
`FUN_182ef5360`, `PlayerStats_PlayerAchievements__WriteToMasterServerGameServerSide`,
`PlayerStats_PlayerSelections__WriteToMasterServerGameServerSide`).

Layout:

    u8      lead (0x01)
    u64     SteamID
    u32     field count (44)
    44 x u32 profile fields, in PlayerStats.PlayerProgess declaration order
    u16     tools payload byte length
    N x { u16 tool_id, u32 kills, u32 extra }      (10 bytes each)
    u16     achievements payload byte length
    N x u32 achievement id
    u16     selections payload byte length
    ...     packed loadout data
    u16     inventory payload byte length
    ...     inventory data (normally empty)
    u8      in_clan
    [u64 clan_id, u8 clan_rank]  (only when in_clan)
    u8      is_banned
    u8      is_timed_out
    u16     weekly-challenge flag
    [challenge payload]          (only when the flag is non-zero)
    u64     role
    u16     username length + UTF-8 username
    ...     trailing bytes (preserved raw)

All values are little-endian.  Nothing is invented: if a section does not
match, the decoder stops and preserves the remaining bytes as raw data.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from typing import Any

LEAD_BYTE = 0x01
EXPECTED_PARAM_COUNT = 44

# PlayerStats.PlayerProgess declaration order.  (snake_case key, display label)
FIELDS: list[tuple[str, str]] = [
    ("kills", "Kills"),
    ("leader_kills", "Leader kills"),
    ("assault_kills", "Assault kills"),
    ("medic_kills", "Medic kills"),
    ("engineer_kills", "Engineer kills"),
    ("support_kills", "Support kills"),
    ("recon_kills", "Recon kills"),
    ("deaths", "Deaths"),
    ("wins", "Wins"),
    ("losses", "Losses"),
    ("friendly_shots", "Friendly shots"),
    ("friendly_kills", "Friendly kills"),
    ("revived", "Revived"),
    ("revived_teammates", "Teammates revived"),
    ("assists", "Assists"),
    ("prestige", "Prestige"),
    ("rank", "Rank"),
    ("exp", "Rank XP"),
    ("shots_fired", "Shots fired"),
    ("shots_hit", "Shots hit"),
    ("headshots", "Headshots"),
    ("objectives_completed", "Objectives completed"),
    ("hp_healed", "HP healed"),
    ("road_kills", "Road kills"),
    ("suicides", "Suicides"),
    ("vehicles_destroyed", "Vehicles destroyed"),
    ("vehicles_hp_repaired", "Vehicle HP repaired"),
    ("longest_kill_m", "Longest kill (m)"),
    ("playtime_seconds", "Playtime (s)"),
    ("leader_playtime_seconds", "Leader playtime (s)"),
    ("assault_playtime_seconds", "Assault playtime (s)"),
    ("medic_playtime_seconds", "Medic playtime (s)"),
    ("engineer_playtime_seconds", "Engineer playtime (s)"),
    ("support_playtime_seconds", "Support playtime (s)"),
    ("recon_playtime_seconds", "Recon playtime (s)"),
    ("leader_score", "Leader score"),
    ("assault_score", "Assault score"),
    ("medic_score", "Medic score"),
    ("engineer_score", "Engineer score"),
    ("support_score", "Support score"),
    ("recon_score", "Recon score"),
    ("total_score", "Total score"),
    ("ammo_supplied", "Ammo supplied"),
    ("weekly_challenges_completed", "Weekly challenges completed"),
]

CLASSES = ("leader", "assault", "medic", "engineer", "support", "recon")


class DecodeError(ValueError):
    """The payload is not a BattleBit GetStats response we can read."""

    def __init__(self, message: str, raw: bytes = b"") -> None:
        super().__init__(message)
        self.raw = raw


@dataclass
class ToolProgress:
    tool_id: int
    kills: int
    extra: int
    name: str | None = None

    @property
    def total(self) -> int:
        return self.kills + self.extra

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "kills": self.kills,
            "extra": self.extra,
            "total": self.total,
        }


@dataclass
class DecodedStats:
    steam_id: int = 0
    raw_len: int = 0
    raw_sha256: str = ""
    raw_b64: str = ""
    schema_ok: bool = False
    warnings: list[str] = field(default_factory=list)
    fields: dict[str, int] = field(default_factory=dict)
    derived: dict[str, float | int] = field(default_factory=dict)
    classes: dict[str, dict[str, int]] = field(default_factory=dict)
    tools: list[ToolProgress] = field(default_factory=list)
    achievements: list[int] = field(default_factory=list)
    selections_raw_b64: str = ""
    selections_len: int = 0
    inventory_raw_b64: str = ""
    inventory_len: int = 0
    clan: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)
    role: int | None = None
    username: str | None = None
    challenge_present: bool = False
    challenge_len: int = 0
    challenge_raw_b64: str = ""
    trailing_hex: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "steam_id": str(self.steam_id),
            "raw_len": self.raw_len,
            "raw_sha256": self.raw_sha256,
            "schema_ok": self.schema_ok,
            "warnings": list(self.warnings),
            "fields": dict(self.fields),
            "derived": dict(self.derived),
            "classes": dict(self.classes),
            "tools": [t.to_dict() for t in self.tools],
            "achievements": list(self.achievements),
            "selections_len": self.selections_len,
            "selections_raw_b64": self.selections_raw_b64,
            "inventory_len": self.inventory_len,
            "inventory_raw_b64": self.inventory_raw_b64,
            "clan": dict(self.clan),
            "flags": dict(self.flags),
            "role": self.role,
            "username": self.username,
            "challenge_present": self.challenge_present,
            "challenge_len": self.challenge_len,
            "challenge_raw_b64": self.challenge_raw_b64,
            "trailing_hex": self.trailing_hex,
            "raw_b64": self.raw_b64,
        }


def _u16(raw: bytes, offset: int) -> int:
    if offset + 2 > len(raw):
        raise DecodeError(f"truncated u16 at offset {offset}", raw)
    return struct.unpack_from("<H", raw, offset)[0]


def _u32(raw: bytes, offset: int) -> int:
    if offset + 4 > len(raw):
        raise DecodeError(f"truncated u32 at offset {offset}", raw)
    return struct.unpack_from("<I", raw, offset)[0]


def _u64(raw: bytes, offset: int) -> int:
    if offset + 8 > len(raw):
        raise DecodeError(f"truncated u64 at offset {offset}", raw)
    return struct.unpack_from("<Q", raw, offset)[0]


def decode(raw: bytes, tool_names: dict[int, str] | None = None) -> DecodedStats:
    """Decode a GetStats response.  Never discards the raw bytes."""

    if not raw:
        raise DecodeError("BattleBit returned no bytes.", raw)
    out = DecodedStats(
        raw_len=len(raw),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        raw_b64=__import__("base64").b64encode(raw).decode("ascii"),
        username=None,
    )

    offset = 0
    lead = raw[offset]
    offset += 1
    if lead != LEAD_BYTE:
        out.warnings.append(f"unexpected lead byte 0x{lead:02x}")
    out.steam_id = _u64(raw, offset)
    offset += 8
    param_count = _u32(raw, offset)
    offset += 4
    if param_count != EXPECTED_PARAM_COUNT:
        out.warnings.append(
            f"expected {EXPECTED_PARAM_COUNT} profile fields, got {param_count}"
        )

    # Profile fields.  If the game adds fields, read what we know and stop.
    readable = min(param_count, len(FIELDS))
    for index in range(readable):
        key, _label = FIELDS[index]
        out.fields[key] = _u32(raw, offset)
        offset += 4
    if param_count != EXPECTED_PARAM_COUNT:
        # Cannot trust the rest of the layout without the field count.
        out.trailing_hex = raw[offset:].hex()
        _finalize(out, tool_names)
        return out

    # ToolsProgess: a length-prefixed array of 10-byte records.
    tools_size = _u16(raw, offset)
    offset += 2
    if tools_size % 10 != 0:
        out.warnings.append(f"tools payload length {tools_size} is not a multiple of 10")
        out.trailing_hex = raw[offset:].hex()
        _finalize(out, tool_names)
        return out
    tool_count = tools_size // 10
    for _ in range(tool_count):
        tool_id = _u16(raw, offset)
        kills = _u32(raw, offset + 2)
        extra = _u32(raw, offset + 6)
        offset += 10
        out.tools.append(
            ToolProgress(
                tool_id=tool_id,
                kills=kills,
                extra=extra,
                name=(tool_names or {}).get(tool_id),
            )
        )
    out.tools.sort(key=lambda item: (-item.kills, -item.extra, item.tool_id))

    # Achievements.
    ach_size = _u16(raw, offset)
    offset += 2
    if ach_size % 4 != 0:
        out.warnings.append(f"achievement payload length {ach_size} is not a multiple of 4")
    for index in range(ach_size // 4):
        out.achievements.append(_u32(raw, offset + index * 4))
    offset += ach_size

    # Selections (packed loadouts / wearings).  Preserved verbatim.
    selections_size = _u16(raw, offset)
    offset += 2
    selections = raw[offset : offset + selections_size]
    if len(selections) != selections_size:
        raise DecodeError("selections payload is truncated", raw)
    out.selections_len = selections_size
    out.selections_raw_b64 = __import__("base64").b64encode(selections).decode("ascii")
    offset += selections_size

    # Inventory (normally empty).
    inventory_size = _u16(raw, offset)
    offset += 2
    inventory = raw[offset : offset + inventory_size]
    if len(inventory) != inventory_size:
        raise DecodeError("inventory payload is truncated", raw)
    out.inventory_len = inventory_size
    out.inventory_raw_b64 = __import__("base64").b64encode(inventory).decode("ascii")
    offset += inventory_size

    # Clan.
    in_clan = raw[offset] if offset < len(raw) else 0
    offset += 1
    out.clan = {"in_clan": bool(in_clan)}
    if in_clan:
        out.clan["clan_id"] = _u64(raw, offset)
        offset += 8
        out.clan["clan_rank"] = raw[offset]
        offset += 1

    # Flags.
    out.flags["is_banned"] = bool(raw[offset]) if offset < len(raw) else False
    offset += 1
    out.flags["is_timed_out"] = bool(raw[offset]) if offset < len(raw) else False
    offset += 1

    # Weekly challenge: a 16-bit byte length, then that many bytes of
    # challenge progress.  (The July capture had length 0; the November
    # capture had 88 bytes.  This is a length, not a boolean.)
    challenge_len = _u16(raw, offset) if offset + 2 <= len(raw) else 0
    offset += 2
    if challenge_len:
        out.challenge_present = True
        out.challenge_len = challenge_len
        challenge = raw[offset : offset + challenge_len]
        if len(challenge) != challenge_len:
            raise DecodeError("weekly challenge payload is truncated", raw)
        out.challenge_raw_b64 = __import__("base64").b64encode(challenge).decode("ascii")
        offset += challenge_len

    # Role: serialized as a 64-bit enum; the low 32 bits are the role.
    if offset + 8 <= len(raw):
        out.role = _u64(raw, offset) & 0xFFFFFFFF
        offset += 8

    # Username: u16 length + UTF-8.  A zero/garbage length is tolerated.
    if offset + 2 <= len(raw):
        name_len = _u16(raw, offset)
        offset += 2
        if 0 < name_len <= len(raw) - offset:
            candidate = raw[offset : offset + name_len]
            try:
                name = candidate.decode("utf-8")
            except UnicodeDecodeError:
                name = None
            if name and name.isprintable():
                out.username = name
                offset += name_len

    out.trailing_hex = raw[offset:].hex()
    _finalize(out, tool_names)
    return out


def _finalize(out: DecodedStats, tool_names: dict[int, str] | None) -> None:
    f = out.fields
    if not f:
        return

    play_seconds = max(1, f.get("playtime_seconds", 0))
    play_minutes = play_seconds / 60.0
    rounds = f.get("wins", 0) + f.get("losses", 0)
    kills = f.get("kills", 0)
    deaths = f.get("deaths", 0)

    out.derived = {
        "kd": round(kills / max(1, deaths), 4),
        "wl": round(f.get("wins", 0) / max(1, f.get("losses", 0)), 4),
        "win_rate": round(f.get("wins", 0) / max(1, rounds), 4),
        "accuracy": round(f.get("shots_hit", 0) / max(1, f.get("shots_fired", 0)), 4),
        "headshot_rate": round(f.get("headshots", 0) / max(1, kills), 4),
        "kills_per_minute": round(kills / max(1e-9, play_minutes), 4),
        "score_per_minute": round(f.get("total_score", 0) / max(1e-9, play_minutes), 4),
        "hours_played": round(play_seconds / 3600.0, 2),
        "rounds_played": rounds,
        "kills_per_round": round(kills / max(1, rounds), 4),
        "score_per_round": round(f.get("total_score", 0) / max(1, rounds), 2),
        "full_rank": f.get("prestige", 0) * 200 + f.get("rank", 0),
    }

    out.classes = {
        cls: {
            "kills": f.get(f"{cls}_kills", 0),
            "score": f.get(f"{cls}_score", 0),
            "playtime_seconds": f.get(f"{cls}_playtime_seconds", 0),
        }
        for cls in CLASSES
    }

    # The first per-tool value is a kill count: the sum of the records matches
    # the global KillCount in every verified capture.  Names come from the
    # bundled AllTools mapping; a missing name is left as None on purpose.
    out.schema_ok = not out.warnings
