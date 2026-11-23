import unittest

from bbr_ripper.api import ApiError
from bbr_ripper.errors import RipperError, classify
from bbr_ripper.steam import SteamError


class ErrorModelTests(unittest.TestCase):
    def test_user_message_has_code_cause_fix(self) -> None:
        err = RipperError(
            "BBR-S001",
            "Steam is not running",
            "Steam did not start",
            "Open Steam and sign in.",
            details={"steam_process_running": False},
        )
        text = err.user_message()
        self.assertIn("[BBR-S001]", text)
        self.assertIn("What happened", text)
        self.assertIn("What to do", text)
        self.assertIn("steam_process_running", text)

    def test_classifies_api_codes(self) -> None:
        token = classify(ApiError("bad", status=403, body=b"x", code="BBR-A002"))
        self.assertEqual(token.code, "BBR-A002")
        stats = classify(ApiError("bad", status=403, body=b"x", code="BBR-A003"))
        self.assertEqual(stats.code, "BBR-A003")
        malformed = classify(ApiError("bad", body=b"x", code="BBR-A005"))
        self.assertEqual(malformed.code, "BBR-A005")

    def test_classifies_steam_and_permissions(self) -> None:
        self.assertEqual(classify(SteamError("nope")).code, "BBR-S002")
        self.assertEqual(classify(PermissionError("denied")).code, "BBR-X001")
        self.assertEqual(classify(RuntimeError("boom")).code, "BBR-X002")

    def test_known_error_is_returned_as_is(self) -> None:
        err = RipperError("BBR-A001", "t", "c", "f")
        self.assertIs(classify(err), err)


if __name__ == "__main__":
    unittest.main()
