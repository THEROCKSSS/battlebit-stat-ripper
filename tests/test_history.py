import tempfile
import unittest
from pathlib import Path

from bbr_ripper import history


def profile(sha: str = "a" * 64, kills: int = 10) -> dict:
    return {
        "schema": "bbr-profile/1",
        "captured_at": "2026-11-23T00:00:00+00:00",
        "player": {"steam_id": "76561190000000001", "persona_name": "Tester"},
        "progress": {
            "kills": kills,
            "deaths": 20,
            "rank": 5,
            "total_score": 1000,
            "playtime_seconds": 3600,
        },
        "raw": {"len": 2590, "sha256": sha},
    }


class HistoryTests(unittest.TestCase):
    def test_append_dedupe_and_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "history.sqlite3"
            row, inserted, previous = history.append_snapshot(profile(), run_id="run-1", path=db)
            self.assertTrue(inserted)
            self.assertIsNone(previous)
            self.assertEqual(row, 1)

            row2, inserted2, previous2 = history.append_snapshot(profile(), run_id="run-2", path=db)
            self.assertFalse(inserted2)
            self.assertEqual(row2, 1)
            self.assertEqual(previous2["id"], 1)

            latest = history.latest("76561190000000001", path=db)
            self.assertEqual(latest["kills"], 10)
            self.assertEqual(history.count(path=db), 1)

    def test_csv_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "history.sqlite3"
            history.append_snapshot(profile(), run_id="run-1", path=db)
            target = history.export_csv(Path(tmp) / "out.csv", path=db)
            text = target.read_text(encoding="utf-8")
            self.assertIn("steam_id", text.splitlines()[0])
            self.assertIn("76561190000000001", text)


if __name__ == "__main__":
    unittest.main()
