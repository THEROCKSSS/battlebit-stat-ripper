"""Unit tests for Steam profile parsing and OpenID helpers (no network)."""

from __future__ import annotations

import io
import unittest
from unittest import mock

import steam_openid
import steam_profiles

XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<profile>
  <steamID64>76561198028883348</steamID64>
  <steamID><![CDATA[Micro]]></steamID>
  <realname><![CDATA[Owen]]></realname>
  <summary><![CDATA[Streaming: <a href="https://twitch.tv/x">twitch</a>]]></summary>
  <avatarFull><![CDATA[https://avatars.akamai.steamstatic.com/x_full.jpg]]></avatarFull>
  <location><![CDATA[United States]]></location>
  <timecreated>1234567890</timecreated>
  <onlineState>offline</onlineState>
</profile>
"""

HTML = """
<div class="friendPlayerLevel lvl_30"><span class="friendPlayerLevelNum">35</span></div>
<div class="profile_in_game persona offline"><div class="profile_in_game_header">Currently Offline</div></div>
<div class="playerAvatar profile_header_size offline">
  <div class="profile_avatar_frame">
    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcset="https://shared.akamai.steamstatic.com/frame_static.png"></source>
      <source srcset="https://shared.akamai.steamstatic.com/frame_anim.png"></source>
      <img src="https://shared.akamai.steamstatic.com/frame_anim.png">
    </picture>
  </div>
</div>
<div class="profile_animated_background">
  <video playsinline autoplay muted loop poster="https://shared.akamai.steamstatic.com/bg.jpg"></video>
</div>
"""


class SteamProfileParsingTests(unittest.TestCase):
    def test_parse_xml(self):
        data = steam_profiles.parse_xml(XML)
        self.assertEqual(data["steam_id"], "76561198028883348")
        self.assertEqual(data["persona_name"], "Micro")
        self.assertEqual(data["real_name"], "Owen")
        self.assertEqual(data["summary"], "Streaming: twitch")
        self.assertEqual(data["location"], "United States")
        self.assertTrue(data["member_since"].startswith("2009-02-13T23:31:30"))
        self.assertIn("x_full.jpg", data["avatar_url"])

    def test_parse_html_extracts_frame_level_status_background(self):
        data = steam_profiles.parse_html(HTML)
        self.assertEqual(data["level"], 35)
        self.assertEqual(data["status"], "Offline")
        self.assertIn("frame_anim.png", data["frame_url"])
        self.assertIn("bg.jpg", data["background_url"])

    def test_parse_xml_error(self):
        with self.assertRaises(steam_profiles.SteamError):
            steam_profiles.parse_xml(
                b"<profile><error><![CDATA[The specified profile could not be found.]]></error></profile>"
            )

    def test_resolve_accepts_ids_and_urls(self):
        self.assertEqual(
            steam_profiles.resolve_steam_id("76561198028883348"), "76561198028883348"
        )
        self.assertEqual(
            steam_profiles.resolve_steam_id(
                "https://steamcommunity.com/profiles/76561198028883348/"
            ),
            "76561198028883348",
        )

    def test_resolve_vanity_uses_xml(self):
        with mock.patch.object(steam_profiles, "_get", return_value=XML):
            self.assertEqual(steam_profiles.resolve_steam_id("micro"), "76561198028883348")

    def test_resolve_rejects_junk(self):
        with self.assertRaises(steam_profiles.SteamError):
            steam_profiles.resolve_steam_id("not a / valid ? value")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


class SteamOpenIDTests(unittest.TestCase):
    def test_login_url_contains_expected_parameters(self):
        url = steam_openid.build_login_url(
            "https://example.test/auth/steam/callback?state=abc",
            "https://example.test",
        )
        self.assertIn("steamcommunity.com/openid/login", url)
        self.assertIn("openid.mode=checkid_setup", url)
        self.assertIn("state%3Dabc", url)

    def test_verify_accepts_steam_confirmation(self):
        params = {
            "openid.mode": "id_res",
            "openid.claimed_id": "https://steamcommunity.com/openid/id/76561198028883348",
        }
        with mock.patch.object(
            steam_openid.urllib.request,
            "urlopen",
            return_value=FakeResponse(b"ns:http://specs.openid.net/auth/2.0\nis_valid:true\n"),
        ):
            self.assertEqual(
                steam_openid.verify(params), "76561198028883348"
            )

    def test_verify_rejects_invalid(self):
        params = {
            "openid.mode": "id_res",
            "openid.claimed_id": "https://steamcommunity.com/openid/id/76561198028883348",
        }
        with mock.patch.object(
            steam_openid.urllib.request,
            "urlopen",
            return_value=FakeResponse(b"is_valid:false\n"),
        ):
            self.assertIsNone(steam_openid.verify(params))

    def test_verify_ignores_non_assertion(self):
        self.assertIsNone(
            steam_openid.verify(
                {"openid.mode": "cancel", "openid.claimed_id": "x"}
            )
        )


if __name__ == "__main__":
    unittest.main()
