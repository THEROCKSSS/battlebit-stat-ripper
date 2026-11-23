"""Write portable BattleBit profile files.

Two artifacts are produced for every rip:

  BBR-<name>-<steamid>.bbrstats   JSON profile, ready to upload to a stats site
  BBR-<name>-<steamid>.txt        human-readable stat sheet

The JSON is intentionally self-describing and includes the raw 2,590-byte API
response so a bad decode can always be recovered later.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .api import FetchResult
from .decoder import CLASSES, DecodedStats

SCHEMA = "bbr-profile/1"


def build_profile(
    result: FetchResult,
    decoded: DecodedStats,
    steam_identity: Any,
    version: str = "0.2.0",
) -> dict[str, Any]:
    captured = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    persona = getattr(steam_identity, "persona_name", "") or ""
    return {
        "schema": SCHEMA,
        "captured_at": captured,
        "tool": {
            "name": "BattleBit Stat Ripper",
            "version": version,
        },
        "source": {
            "api": "api.battlebit.cloud",
            "endpoint": "/Player/GetStats",
            "game_build": result.token.build,
            "raw_bytes": len(result.stats_raw),
        },
        "player": {
            "steam_id": str(result.steam_id),
            "persona_name": persona,
            "username": decoded.username,
        },
        "progress": dict(decoded.fields),
        "derived": dict(decoded.derived),
        "classes": dict(decoded.classes),
        "weapons": [tool.to_dict() for tool in decoded.tools],
        "achievements": list(decoded.achievements),
        "clan": dict(decoded.clan),
        "flags": dict(decoded.flags),
        "role": decoded.role,
        "challenge": {
            "present": decoded.challenge_present,
            "len": decoded.challenge_len,
            "raw_b64": decoded.challenge_raw_b64,
        },
        "selections_b64": decoded.selections_raw_b64,
        "inventory_b64": decoded.inventory_raw_b64,
        "raw": {
            "len": decoded.raw_len,
            "sha256": decoded.raw_sha256,
            "b64": decoded.raw_b64,
            "trailing_hex": decoded.trailing_hex,
        },
        "decode": {
            "schema_ok": decoded.schema_ok,
            "warnings": list(decoded.warnings),
        },
    }


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned[:48] or "player"


def write_exports(
    profile: dict[str, Any],
    out_dir: Path,
    persona: str = "",
    write_json: bool = True,
    write_text: bool = True,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    steam_id = profile["player"]["steam_id"]
    stem = f"BBR-{safe_name(persona or profile['player'].get('username') or 'player')}-{steam_id}"
    written: list[Path] = []

    if write_json:
        json_path = out_dir / f"{stem}.bbrstats"
        json_path.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written.append(json_path)

    if write_text:
        text_path = out_dir / f"{stem}.txt"
        text_path.write_text(render_text(profile), encoding="utf-8")
        written.append(text_path)

    return written


def _n(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _hours(seconds: Any) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "n/a"
    return f"{seconds // 3600:,}h {(seconds % 3600) // 60:02d}m"


def _playtime(seconds: Any) -> str:
    return f"{_hours(seconds)} ({int(seconds or 0):,}s)"


def render_text(profile: dict[str, Any]) -> str:
    p = profile["progress"]
    d = profile["derived"]
    player = profile["player"]
    lines: list[str] = []
    add = lines.append

    add("=" * 62)
    add("  BATTLEBIT REMASTERED - PLAYER PROFILE")
    add("=" * 62)
    add("")
    add(f"  Player        : {player.get('persona_name') or player.get('username') or 'Unknown'}")
    add(f"  Steam ID      : {player['steam_id']}")
    add(f"  Captured      : {profile['captured_at']}")
    add(f"  Game build    : {profile['source'].get('game_build') or 'unknown'}")
    add(f"  Raw response  : {profile['source'].get('raw_bytes', 0):,} bytes")
    add("")

    add("-" * 62)
    add("  PROGRESSION")
    add("-" * 62)
    add(f"  Rank          : {_n(p.get('rank'))}  (prestige {_n(p.get('prestige'))}, full {_n(d.get('full_rank'))})")
    add(f"  Rank XP       : {_n(p.get('exp'))}")
    add(f"  Total score   : {_n(p.get('total_score'))}")
    add(f"  Playtime      : {_playtime(p.get('playtime_seconds'))}")
    add(f"  Rounds        : {_n(d.get('rounds_played'))}  ({_n(p.get('wins'))} W / {_n(p.get('losses'))} L)")
    add(f"  W/L           : {d.get('wl'):.2f}   Win rate {_pct(d.get('win_rate'))}")
    add("")

    add("-" * 62)
    add("  COMBAT")
    add("-" * 62)
    add(f"  Kills         : {_n(p.get('kills'))}")
    add(f"  Deaths        : {_n(p.get('deaths'))}")
    add(f"  K/D           : {d.get('kd'):.2f}")
    add(f"  Kills/min     : {d.get('kills_per_minute'):.3f}")
    add(f"  Score/min     : {d.get('score_per_minute'):.1f}")
    add(f"  Longest kill  : {_n(p.get('longest_kill_m'))} m")
    add(f"  Headshots     : {_n(p.get('headshots'))}  ({_pct(d.get('headshot_rate'))} of kills)")
    add(f"  Shots fired   : {_n(p.get('shots_fired'))}")
    add(f"  Shots hit     : {_n(p.get('shots_hit'))}")
    add(f"  Accuracy      : {_pct(d.get('accuracy'))}")
    add(f"  Assists       : {_n(p.get('assists'))}")
    add(f"  Suicides      : {_n(p.get('suicides'))}")
    add(f"  Friendly kills: {_n(p.get('friendly_kills'))}")
    add(f"  Road kills    : {_n(p.get('road_kills'))}")
    add("")

    add("-" * 62)
    add("  SUPPORT & OBJECTIVES")
    add("-" * 62)
    add(f"  Objectives    : {_n(p.get('objectives_completed'))}")
    add(f"  HP healed     : {_n(p.get('hp_healed'))}")
    add(f"  Revived       : {_n(p.get('revived'))}")
    add(f"  Teammates rev.: {_n(p.get('revived_teammates'))}")
    add(f"  Ammo supplied : {_n(p.get('ammo_supplied'))}")
    add(f"  Vehicles dest.: {_n(p.get('vehicles_destroyed'))}")
    add(f"  Vehicle repair: {_n(p.get('vehicles_hp_repaired'))}")
    add(f"  Weekly chall. : {_n(p.get('weekly_challenges_completed'))}")
    add("")

    add("-" * 62)
    add("  CLASSES                KILLS       SCORE      PLAYTIME")
    add("-" * 62)
    for cls in CLASSES:
        c = profile["classes"].get(cls, {})
        add(
            f"  {cls.title():10s} {c.get('kills', 0):>12,} {c.get('score', 0):>11,}"
            f" {_hours(c.get('playtime_seconds', 0)):>14}"
        )
    add("")

    weapons = [w for w in profile.get("weapons", []) if w.get("kills", 0) or w.get("extra", 0)]
    if weapons:
        add("-" * 62)
        add("  TOP WEAPONS / TOOLS")
        add("-" * 62)
        add("   #   TOOL                         KILLS       EXTRA       TOTAL")
        for index, weapon in enumerate(weapons[:20], 1):
            name = weapon.get("name") or f"Tool #{weapon['tool_id']}"
            add(
                f"  {index:2d}.  {name[:26]:26s} {weapon.get('kills', 0):>9,}"
                f" {weapon.get('extra', 0):>11,} {weapon.get('total', 0):>11,}"
            )
        if len(weapons) > 20:
            add(f"       ... {len(weapons) - 20:,} more tools in the JSON export")
        add("")

    add("-" * 62)
    add("  CLAN & ACCOUNT")
    add("-" * 62)
    clan = profile.get("clan", {})
    add(f"  In clan       : {_n(clan.get('in_clan'))}")
    if clan.get("in_clan"):
        add(f"  Clan ID       : {_n(clan.get('clan_id'))}")
        add(f"  Clan rank     : {_n(clan.get('clan_rank'))}")
    add(f"  Banned        : {_n(profile['flags'].get('is_banned'))}")
    add(f"  Timed out     : {_n(profile['flags'].get('is_timed_out'))}")
    add(f"  Achievements  : {len(profile.get('achievements', [])):,} unlocked")
    add(f"  Loadout blob  : {len(profile.get('selections_b64', '')):,} base64 chars")
    challenge = profile.get("challenge", {})
    if challenge.get("present"):
        add(f"  Weekly data   : {challenge.get('len', 0):,} bytes (preserved)")
    add("")

    add("-" * 62)
    add("  RAW DATA")
    add("-" * 62)
    add(f"  SHA-256       : {profile['raw']['sha256']}")
    add(f"  Bytes         : {profile['raw']['len']:,}")
    add(f"  Decode status : {'OK' if profile['decode'].get('schema_ok') else 'PARTIAL'}")
    for warning in profile["decode"].get("warnings", []):
        add(f"  Warning       : {warning}")
    add("")
    add("  Upload the .bbrstats file to the stats site, or keep it as a")
    add("  portable backup. The raw response is embedded, so the file can")
    add("  be re-decoded if the site's parser improves.")
    add("")
    add("  Not affiliated with BattleBit Remastered or Steam.")
    add("")
    return "\n".join(lines)
