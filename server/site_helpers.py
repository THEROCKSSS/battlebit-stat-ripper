"""Shared read helpers for profiles, clans, and download metadata."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

CLAN_COLORS = (
    "#d98a3d",
    "#c25b4e",
    "#7f9a76",
    "#6f8fa8",
    "#b08a5a",
    "#a4788f",
    "#8b8b8b",
    "#c9a227",
)


def profile_name(row) -> str:
    try:
        name = row["display_name"]
    except (KeyError, IndexError):
        name = None
    return (name or row["persona_name"] or "Unknown player").strip()


def profile_socials(row) -> list[dict[str, str]]:
    import socials

    try:
        raw = row["social_json"]
    except (KeyError, IndexError):
        raw = None
    return socials.links(raw)


def profile_clan(conn, user_id: int):
    return conn.execute(
        """
        SELECT c.*, m.role AS member_role
        FROM clan_members m JOIN clans c ON c.id = m.clan_id
        WHERE m.user_id = ?
        """,
        (user_id,),
    ).fetchone()


def clan_by_slug(conn, slug: str):
    return conn.execute("SELECT * FROM clans WHERE slug = ?", (slug,)).fetchone()


def clan_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM clans").fetchone()["n"]


def user_role_in_clan(conn, clan_id: int, user_id: int | None):
    if not user_id:
        return None
    row = conn.execute(
        "SELECT role FROM clan_members WHERE clan_id = ? AND user_id = ?",
        (clan_id, user_id),
    ).fetchone()
    return row["role"] if row else None


def can_manage(role: str | None) -> bool:
    return role in ("owner", "officer")


def member_rows(conn, clan_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT u.id AS user_id, u.username, m.role, m.joined_at,
               p.steam_id, p.persona_name, p.display_name, p.avatar_path,
               p.visibility, p.updated_at
        FROM clan_members m
        JOIN users u ON u.id = m.user_id
        LEFT JOIN profiles p ON p.steam_id = (
            SELECT steam_id FROM profiles
            WHERE user_id = m.user_id
            ORDER BY updated_at DESC LIMIT 1
        )
        WHERE m.clan_id = ?
        ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'officer' THEN 1 ELSE 2 END,
                 u.username COLLATE NOCASE
        """,
        (clan_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def roster_stats(conn, clan_id: int) -> dict:
    members = member_rows(conn, clan_id)
    kills = deaths = score = hours = 0.0
    counted = 0
    for member in members:
        steam_id = member.get("steam_id")
        if not steam_id or member.get("visibility") != "public":
            continue
        row = conn.execute(
            "SELECT data FROM profiles WHERE steam_id = ?", (steam_id,)
        ).fetchone()
        if not row:
            continue
        try:
            doc = json.loads(row["data"])
        except (TypeError, ValueError):
            continue
        progress = doc.get("progress", {})
        derived = doc.get("derived", {})
        kills += float(progress.get("kills", 0) or 0)
        deaths += float(progress.get("deaths", 0) or 0)
        score += float(progress.get("total_score", 0) or 0)
        hours += float(derived.get("hours_played", 0) or 0)
        counted += 1
    return {
        "members": len(members),
        "counted": counted,
        "kills": int(kills),
        "deaths": int(deaths),
        "kd": (kills / deaths) if deaths else 0.0,
        "score": int(score),
        "hours": hours,
    }


def clan_directory(conn, query: str = "", sort: str = "members") -> list[dict]:
    rows = conn.execute("SELECT * FROM clans").fetchall()
    q = query.strip().lower()
    items = []
    for clan in rows:
        stats = roster_stats(conn, clan["id"])
        if q and q not in clan["name"].lower() and q not in clan["tag"].lower():
            continue
        items.append({"clan": dict(clan), "stats": stats})
    keys = {
        "members": lambda item: (item["stats"]["members"], item["stats"]["kills"]),
        "kills": lambda item: (item["stats"]["kills"], item["stats"]["members"]),
        "kd": lambda item: (item["stats"]["kd"], item["stats"]["kills"]),
        "newest": lambda item: item["clan"]["created_at"],
    }
    items.sort(key=keys.get(sort, keys["members"]), reverse=True)
    return items


def unique_slug(conn, name: str, tag: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or tag.lower()
    base = base[:48].strip("-") or "clan"
    candidate = base
    n = 2
    while conn.execute("SELECT 1 FROM clans WHERE slug = ?", (candidate,)).fetchone():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
