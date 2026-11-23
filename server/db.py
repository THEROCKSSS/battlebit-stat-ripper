"""SQLite storage for the BattleBit profile site."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    steam_id     TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    persona_name TEXT NOT NULL,
    display_name TEXT,
    bio          TEXT NOT NULL DEFAULT '',
    avatar_path  TEXT,
    social_json  TEXT NOT NULL DEFAULT '{}',
    captured_at  TEXT,
    updated_at   TEXT NOT NULL,
    visibility   TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public', 'private')),
    data         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_profiles_user ON profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_profiles_visibility ON profiles(visibility);

CREATE TABLE IF NOT EXISTS players (
    steam_id        TEXT PRIMARY KEY,
    persona_name    TEXT NOT NULL,
    real_name       TEXT NOT NULL DEFAULT '',
    summary         TEXT NOT NULL DEFAULT '',
    avatar_path     TEXT,
    frame_path      TEXT,
    background_path TEXT,
    location        TEXT NOT NULL DEFAULT '',
    member_since    TEXT,
    level           INTEGER,
    status          TEXT NOT NULL DEFAULT '',
    profile_url     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_players_name ON players(persona_name);

CREATE TABLE IF NOT EXISTS clans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    tag           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    slug          TEXT NOT NULL UNIQUE,
    description   TEXT NOT NULL DEFAULT '',
    emblem_path   TEXT,
    color         TEXT NOT NULL DEFAULT '#d98a3d',
    join_mode     TEXT NOT NULL DEFAULT 'open' CHECK (join_mode IN ('open', 'request', 'closed')),
    social_json   TEXT NOT NULL DEFAULT '{}',
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clan_members (
    clan_id   INTEGER NOT NULL REFERENCES clans(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role      TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'officer', 'member')),
    joined_at TEXT NOT NULL,
    PRIMARY KEY (clan_id, user_id),
    UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_clan_members_clan ON clan_members(clan_id);

CREATE TABLE IF NOT EXISTS clan_requests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    clan_id    INTEGER NOT NULL REFERENCES clans(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (clan_id, user_id)
);
"""

# Columns added after the first public build. Kept as a migration list so an
# existing profiles.db keeps working without a rebuild.
PROFILE_COLUMNS = (
    ("display_name", "TEXT"),
    ("bio", "TEXT NOT NULL DEFAULT ''"),
    ("avatar_path", "TEXT"),
    ("social_json", "TEXT NOT NULL DEFAULT '{}'"),
)
USER_COLUMNS = (("steam_id", "TEXT"),)
CLAN_COLUMNS = (("social_json", "TEXT NOT NULL DEFAULT '{}'"),)


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _add_missing_columns(conn, "profiles", PROFILE_COLUMNS)
    _add_missing_columns(conn, "users", USER_COLUMNS)
    _add_missing_columns(conn, "clans", CLAN_COLUMNS)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_steam ON users(steam_id) WHERE steam_id IS NOT NULL"
    )
    conn.commit()
    return conn
