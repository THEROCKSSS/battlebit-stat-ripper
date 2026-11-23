import json
import tempfile
import unittest
from pathlib import Path

from bbr_ripper.logging_setup import RunLogger


class RunLoggerTests(unittest.TestCase):
    def test_writes_log_summary_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = RunLogger(log_dir=Path(tmp), version="test", console=False)
            step = run.step("example", input=1)
            run.end_step(step, ok=True, output=2)
            run.record_error(RuntimeError("boom"), code="BBR-X002")
            run.finish("error", code="BBR-X002")
            self.assertTrue(run.log_path.is_file())
            self.assertTrue(run.summary_path.is_file())
            summary = json.loads(run.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "error")
            self.assertEqual(summary["steps"][0]["name"], "example")
            self.assertEqual(summary["steps"][0]["duration_ms"] >= 0, True)
            self.assertEqual(summary["errors"][0]["code"], "BBR-X002")

            diagnostics = run.write_diagnostics(Path(tmp) / "diag.txt")
            text = diagnostics.read_text(encoding="utf-8")
            self.assertIn("BBR-X002", text)
            self.assertIn("ENVIRONMENT", text)

    def test_ticket_is_never_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = RunLogger(log_dir=Path(tmp), version="test")
            run.info("STEAM_TICKET_READY", bytes=234, fingerprint="abc123", handle=0)
            run.finish("ok")
            text = run.log_path.read_text(encoding="utf-8")
            self.assertIn("fingerprint='abc123'", text)
            self.assertNotIn("14000000", text)


if __name__ == "__main__":
    unittest.main()
