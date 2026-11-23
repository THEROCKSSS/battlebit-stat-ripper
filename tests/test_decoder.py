import base64
import struct
import unittest

from bbr_ripper.decoder import FIELDS, DecodeError, decode

STEAM_ID = 76561198869453515


def build_payload(
    fields: dict[str, int] | None = None,
    tools: list[tuple[int, int, int]] | None = None,
    challenge: bytes = b"",
) -> bytes:
    values = {key: 0 for key, _label in FIELDS}
    values.update(fields or {})
    body = b"\x01" + struct.pack("<Q", STEAM_ID) + struct.pack("<I", 44)
    for key, _label in FIELDS:
        body += struct.pack("<I", values[key])

    tools = tools if tools is not None else [(34, values["kills"], 0)]
    body += struct.pack("<H", len(tools) * 10)
    for tool_id, kills, extra in tools:
        body += struct.pack("<HII", tool_id, kills, extra)

    body += struct.pack("<H", 0)  # achievements
    selections = b"\x02\x00\x00\x00" + b"\x00" * 20
    body += struct.pack("<H", len(selections)) + selections
    body += struct.pack("<H", 0)  # inventory
    body += b"\x01" + struct.pack("<Q", 82989) + b"\xff"  # clan
    body += b"\x00\x00"  # banned, timed out
    body += struct.pack("<H", len(challenge)) + challenge
    body += struct.pack("<Q", 1)  # role
    body += struct.pack("<H", 0)  # username length
    body += b"\x00" * 14
    return body


class DecoderTests(unittest.TestCase):
    def test_core_profile(self) -> None:
        raw = build_payload(
            fields={
                "kills": 3873,
                "deaths": 8073,
                "wins": 333,
                "losses": 368,
                "headshots": 332,
                "shots_fired": 419549,
                "shots_hit": 10591,
                "rank": 200,
                "prestige": 1,
                "total_score": 15865086,
                "playtime_seconds": 920278,
            },
            tools=[(34, 3873, 0)],
        )
        decoded = decode(raw)
        self.assertTrue(decoded.schema_ok)
        self.assertEqual(decoded.steam_id, STEAM_ID)
        self.assertEqual(decoded.fields["kills"], 3873)
        self.assertEqual(decoded.fields["deaths"], 8073)
        self.assertEqual(decoded.tools[0].tool_id, 34)
        self.assertEqual(decoded.tools[0].kills, 3873)
        self.assertAlmostEqual(decoded.derived["kd"], 0.4797, places=4)
        self.assertEqual(decoded.derived["full_rank"], 400)
        self.assertTrue(decoded.clan["in_clan"])
        self.assertEqual(decoded.clan["clan_id"], 82989)
        self.assertFalse(decoded.flags["is_banned"])
        self.assertEqual(decoded.role, 1)

    def test_tool_kills_sum_to_global(self) -> None:
        raw = build_payload(
            fields={"kills": 30},
            tools=[(1, 10, 0), (2, 20, 0), (3, 0, 50)],
        )
        decoded = decode(raw)
        self.assertEqual(sum(t.kills for t in decoded.tools), 30)
        self.assertEqual(decoded.tools[0].tool_id, 2)  # sorted by kills desc
        self.assertEqual(decoded.tools[0].total, 20)

    def test_weekly_challenge_length_is_skipped(self) -> None:
        raw = build_payload(fields={"kills": 1}, challenge=b"\xab" * 88)
        decoded = decode(raw)
        self.assertTrue(decoded.schema_ok)
        self.assertTrue(decoded.challenge_present)
        self.assertEqual(decoded.challenge_len, 88)
        self.assertEqual(decoded.role, 1)
        self.assertEqual(base64.b64decode(decoded.challenge_raw_b64), b"\xab" * 88)

    def test_raw_bytes_are_preserved(self) -> None:
        raw = build_payload(fields={"kills": 7})
        decoded = decode(raw)
        self.assertEqual(decoded.raw_len, len(raw))
        self.assertEqual(base64.b64decode(decoded.raw_b64), raw)
        self.assertEqual(len(decoded.raw_sha256), 64)

    def test_truncated_payload_raises(self) -> None:
        raw = build_payload(fields={"kills": 7})
        with self.assertRaises(DecodeError):
            decode(raw[:10])


if __name__ == "__main__":
    unittest.main()
