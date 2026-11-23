import io
import json
import os
import re
import tempfile
import unittest

from PIL import Image

# Configure an isolated data dir before importing the app.
_TMP = tempfile.mkdtemp(prefix="bbr-server-test-")
os.environ["BBR_SERVER_DATA"] = _TMP
os.environ["BBR_SECRET_KEY"] = "test-secret-not-for-production"

import app as server  # noqa: E402

STEAM_ID = "76561190000000001"


def csrf(html: str) -> str:
    match = re.search(r'name="_csrf" value="([^"]+)"', html)
    if not match:
        raise AssertionError("no CSRF token in page")
    return match.group(1)


def png_file() -> io.BytesIO:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (200, 120, 40)).save(buffer, "PNG")
    buffer.seek(0)
    return buffer


def login(client, username: str, password: str) -> None:
    with client.session_transaction() as sess:
        sess.clear()
    page = client.get("/login")
    token = csrf(page.get_data(as_text=True))
    response = client.post(
        "/login",
        data={"_csrf": token, "username": username, "password": password},
        follow_redirects=True,
    )
    assert response.status_code == 200, response.status_code



def profile_doc(steam_id: str = STEAM_ID, persona: str = "TestPlayer") -> dict:
    return {
        "schema": "bbr-profile/1",
        "captured_at": "2026-11-23T00:00:00+00:00",
        "source": {"api": "api.battlebit.cloud", "game_build": "test"},
        "player": {"steam_id": steam_id, "persona_name": persona, "username": None},
        "progress": {
            "kills": 123,
            "deaths": 100,
            "wins": 10,
            "losses": 5,
            "rank": 10,
            "prestige": 0,
            "total_score": 5000,
            "playtime_seconds": 3600,
            "headshots": 12,
            "shots_fired": 1000,
            "shots_hit": 200,
            "assault_kills": 50,
            "medic_kills": 30,
            "engineer_kills": 20,
            "support_kills": 13,
            "recon_kills": 10,
            "leader_kills": 0,
        },
        "derived": {"kd": 1.23, "hours_played": 1.0, "full_rank": 10},
        "classes": {
            "assault": {"kills": 50, "score": 2000, "playtime_seconds": 1200},
            "medic": {"kills": 30, "score": 1000, "playtime_seconds": 600},
        },
        "weapons": [
            {"tool_id": 17, "name": "SCAR-H", "kills": 80, "extra": 0, "total": 80}
        ],
        "achievements": [],
        "clan": {"in_clan": False},
        "flags": {"is_banned": False, "is_timed_out": False},
        "role": 1,
        "challenge": {"present": False, "len": 0, "raw_b64": ""},
        "selections_b64": "",
        "inventory_b64": "",
        "raw": {"len": 0, "sha256": "0" * 64, "b64": "", "trailing_hex": ""},
        "decode": {"schema_ok": True, "warnings": []},
    }


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.app.config.update(TESTING=True)
        cls.client = server.app.test_client()

    def test_01_register_and_upload(self):
        page = self.client.get("/register")
        self.assertEqual(page.status_code, 200)
        token = csrf(page.get_data(as_text=True))
        response = self.client.post(
            "/register",
            data={
                "_csrf": token,
                "username": "tester",
                "password": "test-password-123",
                "confirm": "test-password-123",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Upload", response.data)

        page = self.client.get("/upload")
        token = csrf(page.get_data(as_text=True))
        response = self.client.post(
            "/upload",
            data={
                "_csrf": token,
                "json": json.dumps(profile_doc()),
                "visibility": "public",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"TestPlayer", response.data)
        self.assertIn(b"SCAR-H", response.data)

    def test_02_public_pages(self):
        profile = self.client.get(f"/p/{STEAM_ID}")
        self.assertEqual(profile.status_code, 200)
        self.assertIn(b"123", profile.data)
        board = self.client.get("/leaderboard")
        self.assertEqual(board.status_code, 200)
        self.assertIn(b"TestPlayer", board.data)
        api = self.client.get(f"/api/profiles/{STEAM_ID}")
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.get_json()["player"]["steam_id"], STEAM_ID)

    def test_03_private_profile_is_hidden(self):
        page = self.client.get("/me")
        token = csrf(page.get_data(as_text=True))
        response = self.client.post(
            f"/profiles/{STEAM_ID}/visibility",
            data={"_csrf": token, "visibility": "private"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        owner_view = self.client.get(f"/p/{STEAM_ID}")
        self.assertEqual(owner_view.status_code, 200)
        self.assertIn(b"private", owner_view.data)

        page = self.client.get("/me")
        token = csrf(page.get_data(as_text=True))
        self.client.post("/logout", data={"_csrf": token})

        anonymous = self.client.get(f"/p/{STEAM_ID}")
        self.assertEqual(anonymous.status_code, 404)
        self.assertEqual(self.client.get(f"/api/profiles/{STEAM_ID}").status_code, 404)
        board = self.client.get("/leaderboard")
        self.assertNotIn(b"TestPlayer", board.data)

    def test_04_csrf_required(self):
        response = self.client.post(
            "/login", data={"username": "nobody", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 400)

    def test_05_bad_upload_rejected(self):
        page = self.client.get("/login")
        token = csrf(page.get_data(as_text=True))
        self.client.post(
            "/login",
            data={"_csrf": token, "username": "tester", "password": "test-password-123"},
            follow_redirects=True,
        )
        page = self.client.get("/upload")
        token = csrf(page.get_data(as_text=True))
        response = self.client.post(
            "/upload",
            data={"_csrf": token, "json": '{"schema":"wrong"}', "visibility": "public"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"not a BattleBit Stat Ripper profile", response.data)


    def test_06_profile_edit_avatar_and_socials(self):
        login(self.client, "tester", "test-password-123")
        page = self.client.get(f"/p/{STEAM_ID}/edit")
        token = csrf(page.get_data(as_text=True))
        response = self.client.post(
            f"/p/{STEAM_ID}/edit",
            data={
                "_csrf": token,
                "display_name": "Ace Tester",
                "bio": "Portable record test.",
                "visibility": "public",
                "social_youtube": "https://youtube.com/@test",
                "social_discord": "discord.gg/test",
                "avatar": (png_file(), "portrait.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Ace Tester", response.data)
        self.assertIn(b'src="/media/avatars/', response.data)
        self.assertNotIn(b"%3CMacro", response.data)
        self.assertIn(b"youtube.com/@test", response.data)
        conn = server.db.connect(server.app.config["DATABASE"])
        row = conn.execute(
            "SELECT avatar_path FROM profiles WHERE steam_id = ?", (STEAM_ID,)
        ).fetchone()
        conn.close()
        self.assertTrue(row["avatar_path"].endswith(".webp"))
        image = self.client.get(f"/media/avatars/{row['avatar_path']}")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.content_type, "image/webp")
        image.close()

    def test_07_clan_create_and_profile_badge(self):
        login(self.client, "tester", "test-password-123")
        page = self.client.get("/clans/new")
        token = csrf(page.get_data(as_text=True))
        response = self.client.post(
            "/clans/new",
            data={
                "_csrf": token,
                "name": "Test Clan",
                "tag": "TST",
                "description": "A clan made by the test suite.",
                "join_mode": "open",
                "color": server.H.CLAN_COLORS[0],
                "social_discord": "https://discord.gg/test",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test Clan", response.data)
        profile = self.client.get(f"/p/{STEAM_ID}")
        self.assertIn(b"[TST]", profile.data)

    def test_08_clan_create_rate_limit(self):
        login(self.client, "tester", "test-password-123")
        old = server.site_ext.RATE_LIMITS["clan_create"]
        server.site_ext.RATE_LIMITS["clan_create"] = (1, 3600)
        server.LIMITER.reset("clan_create:")
        try:
            page = self.client.get("/clans/new")
            token = csrf(page.get_data(as_text=True))
            self.client.post(
                "/clans/new",
                data={"_csrf": token, "name": "Rate Clan", "tag": "RATE",
                      "join_mode": "open", "color": server.H.CLAN_COLORS[0]},
                follow_redirects=True,
            )
            page = self.client.get("/clans/new")
            token = csrf(page.get_data(as_text=True))
            blocked = self.client.post(
                "/clans/new",
                data={"_csrf": token, "name": "Rate Clan 2", "tag": "RT2",
                      "join_mode": "open", "color": server.H.CLAN_COLORS[0]},
                follow_redirects=True,
            )
            self.assertEqual(blocked.status_code, 429)
        finally:
            server.site_ext.RATE_LIMITS["clan_create"] = old
            server.LIMITER.reset("clan_create:")

    def test_09_clan_request_and_approve(self):
        login(self.client, "tester", "test-password-123")
        page = self.client.get("/c/test-clan/manage")
        token = csrf(page.get_data(as_text=True))
        self.client.post(
            "/c/test-clan/settings",
            data={
                "_csrf": token,
                "name": "Test Clan",
                "tag": "TST",
                "description": "A clan made by the test suite.",
                "join_mode": "request",
                "color": server.H.CLAN_COLORS[0],
            },
            follow_redirects=True,
        )

        with self.client.session_transaction() as sess:
            sess.clear()
        page = self.client.get("/register")
        token = csrf(page.get_data(as_text=True))
        self.client.post(
            "/register",
            data={
                "_csrf": token,
                "username": "joiner",
                "password": "joiner-password-1",
                "confirm": "joiner-password-1",
            },
            follow_redirects=True,
        )
        page = self.client.get("/c/test-clan")
        token = csrf(page.get_data(as_text=True))
        response = self.client.post(
            "/c/test-clan/join",
            data={"_csrf": token, "message": "Let me in."},
            follow_redirects=True,
        )
        self.assertIn(b"request pending", response.data)

        login(self.client, "tester", "test-password-123")
        conn = server.db.connect(server.app.config["DATABASE"])
        request_row = conn.execute(
            "SELECT id FROM clan_requests WHERE message = 'Let me in.'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(request_row)
        page = self.client.get("/c/test-clan/manage")
        token = csrf(page.get_data(as_text=True))
        response = self.client.post(
            f"/c/test-clan/requests/{request_row['id']}/approve",
            data={"_csrf": token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"joiner", response.data)

    def test_10_social_validation(self):
        login(self.client, "tester", "test-password-123")
        page = self.client.get(f"/p/{STEAM_ID}/edit")
        token = csrf(page.get_data(as_text=True))
        response = self.client.post(
            f"/p/{STEAM_ID}/edit",
            data={
                "_csrf": token,
                "display_name": "Ace Tester",
                "visibility": "public",
                "social_youtube": "https://evil.example/@notyoutube",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"YouTube links must point to youtube.com", response.data)

    def test_12_clan_promote_and_kick(self):
        login(self.client, "tester", "test-password-123")
        conn = server.db.connect(server.app.config["DATABASE"])
        joiner = conn.execute(
            "SELECT id FROM users WHERE username = 'joiner'"
        ).fetchone()
        self.assertIsNotNone(joiner)
        page = self.client.get("/c/test-clan/manage")
        token = csrf(page.get_data(as_text=True))
        response = self.client.post(
            f"/c/test-clan/members/{joiner['id']}/role",
            data={"_csrf": token, "role": "officer"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        role = conn.execute(
            "SELECT role FROM clan_members WHERE user_id = ?", (joiner["id"],)
        ).fetchone()
        self.assertEqual(role["role"], "officer")
        page = self.client.get("/c/test-clan/manage")
        token = csrf(page.get_data(as_text=True))
        response = self.client.post(
            f"/c/test-clan/members/{joiner['id']}/kick",
            data={"_csrf": token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        gone = conn.execute(
            "SELECT 1 FROM clan_members WHERE user_id = ?", (joiner["id"],)
        ).fetchone()
        self.assertIsNone(gone)
        conn.close()

    def test_13_download_routes(self):
        page = self.client.get("/download")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"BattleBitStatRipper", page.data)
        self.assertIn(b"SHA-256", page.data)
        binary = self.client.get("/download/windows")
        self.assertEqual(binary.status_code, 200)
        self.assertGreater(len(binary.data), 1_000_000)
        binary.close()


if __name__ == "__main__":
    unittest.main()
