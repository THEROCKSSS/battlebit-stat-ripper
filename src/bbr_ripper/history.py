"""Local snapshot history so every run is kept, even if the user forgets a file.

SQLite at `%LOCALAPPDATA%\\BBR Stats Ripper\\history.sqlite3` (override with
BBR_HISTORY_DB).  Each unique raw response is stored once per Steam ID.  The
profile JSON is the full `.bbrstats` payload, so history can be re-decoded later.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .logging_setup import default_data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    steam_id           TEXT NOT NULL,
    persona            TEXT,
    captured_at        TEXT NOT NULL,
    recorded_at        TEXT NOT NULL,
    raw_len            INTEGER NOT NULL,
    raw_sha256         TEXT NOT NULL,
    kills              INTEGER,
    deaths             INTEGER,
    rank               INTEGER,
    total_score        INTEGER,
    playtime_seconds   INTEGER,
    run_id             TEXT,
    profile_json       TEXT NOT NULL,
    UNIQUE (steam_id, raw_sha256)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_steam ON snapshots(steam_id, captured_at);
"""


def default_history_path() -> Path:
    env = os.environ.get("BBR_HISTORY_DB")
    if env:
        return Path(env).expanduser()
    return default_data_dir() / "history.sqlite3"


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or default_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def append_snapshot(
    profile: dict[str, Any],
    run_id: str | None = None,
    path: Path | None = None,
) -> tuple[int, bool, dict[str, Any] | None]:
    """Insert a profile. Returns (row_id, inserted, previous_snapshot)."""

    player = profile.get("player", {})
    progress = profile.get("progress", {})
    raw = profile.get("raw", {})
    steam_id = str(player.get("steam_id", ""))
    if not steam_id:
        raise ValueError("profile has no Steam ID")
    sha = str(raw.get("sha256", ""))
    if not sha:
        raise ValueError("profile has no raw SHA-256")

    conn = _connect(path)
    try:
        previous = conn.execute(
            "SELECT id, captured_at, kills, deaths, rank, total_score, playtime_seconds "
            "FROM snapshots WHERE steam_id = ? ORDER BY id DESC LIMIT 1",
            (steam_id,),
        ).fetchone()
        try:
            cursor = conn.execute(
                """
                INSERT INTO snapshots
                    (steam_id, persona, captured_at, recorded_at, raw_len, raw_sha256,
                     kills, deaths, rank, total_score, playtime_seconds, run_id, profile_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    steam_id,
                    player.get("persona_name") or "",
                    profile.get("captured_at") or datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    int(raw.get("len", 0)),
                    sha,
                    int(progress.get("kills", 0)),
                    int(progress.get("deaths", 0)),
                    int(progress.get("rank", 0)),
                    int(progress.get("total_score", 0)),
                    int(progress.get("playtime_seconds", 0)),
                    run_id or "",
                    json.dumps(profile, ensure_ascii=False),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid), True, dict(previous) if previous else None
        except sqlite3.IntegrityError:
            row = conn.execute(
                "SELECT id FROM snapshots WHERE steam_id = ? AND raw_sha256 = ?",
                (steam_id, sha),
            ).fetchone()
            return int(row["id"]), False, dict(previous) if previous else None
    finally:
        conn.close()


def latest(steam_id: str, path: Path | None = None) -> dict[str, Any] | None:
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT * FROM snapshots WHERE steam_id = ? ORDER BY id DESC LIMIT 1",
            (steam_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def history_for(steam_id: str, limit: int = 100, path: Path | None = None) -> list[dict[str, Any]]:
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT id, steam_id, persona, captured_at, recorded_at, raw_len, raw_sha256, "
            "kills, deaths, rank, total_score, playtime_seconds, run_id "
            "FROM snapshots WHERE steam_id = ? ORDER BY id DESC LIMIT ?",
            (steam_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def count(path: Path | None = None) -> int:
    conn = _connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"])
    finally:
        conn.close()


def export_csv(target: Path, steam_id: str | None = None, path: Path | None = None) -> Path:
    conn = _connect(path)
    try:
        query = (
            "SELECT id, steam_id, persona, captured_at, recorded_at, raw_len, raw_sha256, "
            "kills, deaths, rank, total_score, playtime_seconds, run_id FROM snapshots"
        )
        params: tuple[Any, ...] = ()
        if steam_id:
            query += " WHERE steam_id = ?"
            params = (steam_id,)
        query += " ORDER BY id"
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id",
                "steam_id",
                "persona",
                "captured_at",
                "recorded_at",
                "raw_len",
                "raw_sha256",
                "kills",
                "deaths",
                "rank",
                "total_score",
                "playtime_seconds",
                "run_id",
            ]
        )
        for row in rows:
            writer.writerow([row[key] for key in row.keys()])
    return target
