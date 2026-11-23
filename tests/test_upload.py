"""Unit tests for the capture upload client (no network)."""

from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest import mock

from bbr_ripper.upload import UploadError, upload_profile

PROFILE = {"schema": "bbr-profile/1", "player": {"steam_id": "76561198028883348"}}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


class UploadTests(unittest.TestCase):
    def test_posts_profile_with_bearer_token(self):
        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(b'{"ok":true,"steam_id":"76561198028883348"}')

        with mock.patch("bbr_ripper.upload.urllib.request.urlopen", fake_urlopen):
            answer = upload_profile(PROFILE, "https://example.test/", "bbr_secret")
        self.assertTrue(answer["ok"])
        self.assertEqual(captured["url"], "https://example.test/api/captures")
        self.assertEqual(captured["auth"], "Bearer bbr_secret")
        self.assertEqual(captured["body"]["player"]["steam_id"], "76561198028883348")

    def test_missing_token_is_rejected_locally(self):
        with self.assertRaises(UploadError) as ctx:
            upload_profile(PROFILE, "https://example.test", "")
        self.assertEqual(ctx.exception.code, "BBR-U002")

    def test_bad_scheme_is_rejected(self):
        with self.assertRaises(UploadError):
            upload_profile(PROFILE, "ftp://example.test", "bbr_x")

    def test_401_maps_to_token_error(self):
        error = urllib.error.HTTPError(
            "https://example.test/api/captures",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":"Unknown or revoked token."}'),
        )
        with mock.patch("bbr_ripper.upload.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(UploadError) as ctx:
                upload_profile(PROFILE, "https://example.test", "bbr_x")
        self.assertEqual(ctx.exception.code, "BBR-U002")
        self.assertEqual(ctx.exception.status, 401)

    def test_403_maps_to_steam_id_error(self):
        error = urllib.error.HTTPError(
            "https://example.test/api/captures",
            403,
            "Forbidden",
            {},
            io.BytesIO(b'{"error":"bound to a different Steam ID"}'),
        )
        with mock.patch("bbr_ripper.upload.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(UploadError) as ctx:
                upload_profile(PROFILE, "https://example.test", "bbr_x")
        self.assertEqual(ctx.exception.code, "BBR-U003")


if __name__ == "__main__":
    unittest.main()
