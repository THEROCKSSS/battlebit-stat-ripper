import struct
import unittest

from bbr_ripper.api import build_token_request, parse_token_response, ApiError


class ApiWireTests(unittest.TestCase):
    def test_token_request_layout(self) -> None:
        ticket = b"\x14\x00\x00\x00" + b"\xaa" * 20
        body = build_token_request(76561198869453515, ticket)
        self.assertEqual(struct.unpack_from("<Q", body, 0)[0], 76561198869453515)
        ticket_len = struct.unpack_from("<H", body, 8)[0]
        self.assertEqual(ticket_len, len(ticket.hex()))
        self.assertEqual(body[10 : 10 + ticket_len], ticket.hex().encode())
        self.assertEqual(struct.unpack_from("<Q", body, 10 + ticket_len)[0], 1)

    def test_token_response_layout(self) -> None:
        session = b"\x50\x05\x44\x57\x00\x00\x00\x00"
        token = b"ADF23397BFC1A7B812B63391EDE6A73F"
        build = b"Production 2.2.5 Hotfix"
        raw = (
            b"\x01"
            + session
            + b"\xab\xfc\x2d\x45\x84\x6a\xc7\xfa"
            + struct.pack("<I", 164)
            + struct.pack("<H", len(token))
            + token
            + struct.pack("<H", len(build))
            + build
        )
        parsed = parse_token_response(raw)
        self.assertEqual(parsed.session, session)
        self.assertEqual(parsed.token, token.decode())
        self.assertEqual(parsed.build, build.decode())
        self.assertEqual(parsed.session_int, 0x57440550)

    def test_bad_token_response(self) -> None:
        with self.assertRaises(ApiError):
            parse_token_response(b"\x00" + b"\x00" * 40)


if __name__ == "__main__":
    unittest.main()
