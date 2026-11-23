"""Seed the player directory with Steam profiles.

Usage:
    python scripts/seed_players.py [steam_id ...]

With no arguments it imports the six community profiles the site was seeded
with. Public Steam data only; stats still require each player's own capture.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server"
sys.path.insert(0, str(SERVER))

import db  # noqa: E402
import steam_profiles  # noqa: E402

DATA_DIR = Path(os.environ.get("BBR_SERVER_DATA", SERVER / "data"))
MEDIA_DIR = DATA_DIR / "uploads"

SEED_IDS = [
    "76561198067613739",  # GodfatherAct
    "76561199125435580",  # Yuh_Eclipse
    "76561199130810403",  # skeletalsavage
    "76561199539216680",  # noobiewithboobies
    "76561199182643173",  # racoonman
    "76561198028883348",  # Micro
]


def main(argv: list[str]) -> int:
    steam_ids = argv[1:] or SEED_IDS
    conn = db.connect(DATA_DIR / "profiles.db")
    failures = 0
    for index, steam_id in enumerate(steam_ids):
        if index:
            time.sleep(0.8)
        try:
            player = steam_profiles.refresh_player(conn, steam_id, MEDIA_DIR)
        except steam_profiles.SteamError as exc:
            failures += 1
            print(f"FAIL {steam_id}: {exc}")
            continue
        print(
            "OK  {steam_id}  {persona_name!r}  level={level}  "
            "avatar={avatar_path}  frame={frame_path}  bg={background_path}".format(**player)
        )
    print(f"{len(steam_ids) - failures}/{len(steam_ids)} profiles imported")
    return 1 if failures and failures == len(steam_ids) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
