"""Official BattleBit profile API client.

Mirrors the game's own master-server handshake (captured 2026-07-12 and verified
again 2026-11-23):

    POST /Tokens/GetToken   body: steamid(u64) + ticket_hex_len(u16) + ticket_hex + u64(1)
    POST /Player/GetStats   body: steamid(u64) + session(u64)

Both calls use the BattleBit user agent and TLS SNI for api.battlebit.cloud.
No password, cookie, or token is stored by the ripper.
"""

from __future__ import annotations

import hashlib
import http.client
import socket
import ssl
import struct
import time
from dataclasses import dataclass
from typing import Any

from . import errors
from .logging_setup import RunLogger

HOST = "api.battlebit.cloud"
PORT = 443
USER_AGENT = "b32bf642b285ca1f0663688e7078f892dc2d0843"
TOKEN_PATH = "/Tokens/GetToken"
STATS_PATH = "/Player/GetStats"
MAX_ATTEMPTS = 3


class ApiError(RuntimeError):
    """The BattleBit API rejected or could not complete the request."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        body: bytes = b"",
        code: str | None = None,
        stage: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.code = code
        self.stage = stage


@dataclass
class TokenInfo:
    session: bytes
    token: str
    build: str
    raw: bytes

    @property
    def session_int(self) -> int:
        return struct.unpack("<Q", self.session)[0]


@dataclass
class FetchResult:
    token: TokenInfo
    stats_raw: bytes
    steam_id: int
    token_request: bytes
    stats_request: bytes


def _post(
    path: str,
    body: bytes,
    timeout: float = 20.0,
    run: RunLogger | None = None,
) -> tuple[int, dict[str, str], bytes]:
    started = time.perf_counter()
    sensitive = path == TOKEN_PATH
    if run:
        run.info(
            "HTTP_REQUEST",
            path=path,
            body_bytes=len(body),
            body_sha256="" if sensitive else hashlib.sha256(body).hexdigest()[:16],
            body_redacted=sensitive,
            timeout_s=timeout,
        )
    context = ssl.create_default_context()
    conn = http.client.HTTPSConnection(HOST, PORT, context=context, timeout=timeout)
    try:
        conn.request(
            "POST",
            path,
            body=body,
            headers={
                "Host": HOST,
                "User-Agent": USER_AGENT,
                "Content-Length": str(len(body)),
                "Connection": "close",
            },
        )
        response = conn.getresponse()
        data = response.read()
        headers = {key.lower(): value for key, value in response.getheaders()}
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        if run:
            run.info(
                "HTTP_RESPONSE",
                path=path,
                status=response.status,
                bytes=len(data),
                ms=elapsed,
                server=headers.get("server", ""),
                cf_ray=headers.get("cf-ray", ""),
                body_head="" if sensitive else (data[:48].hex() if data else ""),
                body_redacted=sensitive,
            )
        return response.status, headers, data
    except (OSError, ssl.SSLError, socket.timeout, http.client.HTTPException) as exc:
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        if run:
            run.error(
                "HTTP_FAILED",
                path=path,
                ms=elapsed,
                error_type=type(exc).__name__,
                error=str(exc),
            )
        raise errors.api_unreachable(exc) from exc
    finally:
        conn.close()


def build_token_request(steam_id: int, ticket: bytes) -> bytes:
    ticket_hex = ticket.hex().encode("ascii")
    if len(ticket_hex) > 0xFFFF:
        raise ApiError(
            "Steam returned an auth ticket larger than the API supports.",
            code="BBR-A005",
            stage="token_request",
        )
    return (
        struct.pack("<Q", steam_id)
        + struct.pack("<H", len(ticket_hex))
        + ticket_hex
        + struct.pack("<Q", 1)
    )


def parse_token_response(raw: bytes) -> TokenInfo:
    if len(raw) < 23 or raw[0] != 0x01:
        raise ApiError(
            "BattleBit returned an unexpected token response. "
            "The game or API may have been updated; run the ripper again or report this.",
            body=raw,
            code="BBR-A005",
            stage="token_response",
        )
    session = raw[1:9]
    token_len = struct.unpack_from("<H", raw, 21)[0]
    token_start = 23
    token_end = token_start + token_len
    if token_end > len(raw):
        raise ApiError(
            "BattleBit token response was truncated.",
            body=raw,
            code="BBR-A005",
            stage="token_response",
        )
    token = raw[token_start:token_end].decode("ascii", "replace")
    pos = token_end
    build = ""
    if pos + 2 <= len(raw):
        build_len = struct.unpack_from("<H", raw, pos)[0]
        build_start = pos + 2
        build_end = build_start + build_len
        if build_end <= len(raw):
            build = raw[build_start:build_end].decode("utf-8", "replace")
    return TokenInfo(session=session, token=token, build=build, raw=raw)


def _retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status < 600


def get_token(
    steam_id: int,
    ticket: bytes,
    run: RunLogger | None = None,
    attempts: int = MAX_ATTEMPTS,
) -> TokenInfo:
    body = build_token_request(steam_id, ticket)
    last_error: ApiError | None = None
    for attempt in range(1, attempts + 1):
        step = run.step("api_get_token", attempt=attempt) if run else None
        try:
            status, _headers, data = _post(TOKEN_PATH, body, run=run)
        except errors.RipperError:
            if run:
                run.end_step(step, ok=False)
            raise
        if status == 403:
            if run:
                run.end_step(step, ok=False, status=status)
            raise ApiError(
                "Steam's auth ticket was rejected by BattleBit (HTTP 403).",
                status=status,
                body=data,
                code="BBR-A002",
                stage="token",
            )
        if status != 200:
            last_error = ApiError(
                f"BattleBit token request failed with HTTP {status}.",
                status=status,
                body=data,
                code="BBR-A004",
                stage="token",
            )
            if _retryable_status(status) and attempt < attempts:
                delay = 1.5 * attempt
                if run:
                    run.warning(
                        "HTTP_RETRY",
                        path=TOKEN_PATH,
                        attempt=attempt,
                        status=status,
                        delay_s=delay,
                    )
                    run.end_step(step, ok=False, status=status, retry=True)
                time.sleep(delay)
                continue
            if run:
                run.end_step(step, ok=False, status=status)
            raise errors.http_error(TOKEN_PATH, status, data)
        token = parse_token_response(data)
        if run:
            run.end_step(
                step,
                ok=True,
                status=status,
                build=token.build,
                token_len=len(token.token),
            )
        return token
    raise last_error or ApiError("Token request failed", code="BBR-A004", stage="token")


def get_stats(
    steam_id: int,
    session: bytes,
    run: RunLogger | None = None,
    attempts: int = MAX_ATTEMPTS,
) -> bytes:
    body = struct.pack("<Q", steam_id) + session
    for attempt in range(1, attempts + 1):
        step = run.step("api_get_stats", attempt=attempt) if run else None
        try:
            status, _headers, data = _post(STATS_PATH, body, run=run)
        except errors.RipperError:
            if run:
                run.end_step(step, ok=False)
            raise
        if status == 403:
            if run:
                run.end_step(step, ok=False, status=status)
            raise ApiError(
                "BattleBit refused the stats request (HTTP 403).",
                status=status,
                body=data,
                code="BBR-A003",
                stage="stats",
            )
        if status != 200:
            if _retryable_status(status) and attempt < attempts:
                delay = 1.5 * attempt
                if run:
                    run.warning(
                        "HTTP_RETRY",
                        path=STATS_PATH,
                        attempt=attempt,
                        status=status,
                        delay_s=delay,
                    )
                    run.end_step(step, ok=False, status=status, retry=True)
                time.sleep(delay)
                continue
            if run:
                run.end_step(step, ok=False, status=status)
            raise errors.http_error(STATS_PATH, status, data)
        if len(data) < 13:
            if run:
                run.end_step(step, ok=False, status=status, bytes=len(data))
            raise ApiError(
                "BattleBit returned an empty or truncated stats response.",
                status=status,
                body=data,
                code="BBR-A006",
                stage="stats",
            )
        if run:
            run.end_step(step, ok=True, status=status, bytes=len(data))
        return data
    raise ApiError("Stats request failed", code="BBR-A004", stage="stats")


def fetch(
    steam_id: int,
    ticket: bytes,
    run: RunLogger | None = None,
) -> FetchResult:
    token_request = build_token_request(steam_id, ticket)
    token = get_token(steam_id, ticket, run=run)
    stats = get_stats(steam_id, token.session, run=run)
    stats_request = struct.pack("<Q", steam_id) + token.session
    if run:
        digest = hashlib.sha256(stats).hexdigest()
        run.info(
            "PROFILE_RECEIVED",
            bytes=len(stats),
            build=token.build,
            sha256=digest,
            sha_prefix=digest[:16],
        )
    return FetchResult(
        token=token,
        stats_raw=stats,
        steam_id=steam_id,
        token_request=token_request,
        stats_request=stats_request,
    )


def probe_api(run: RunLogger) -> dict[str, Any]:
    """Read-only reachability probe used by Diagnostics.  No ticket is sent."""

    dns = run.dns_check(HOST)
    result: dict[str, Any] = {"dns": dns, "tls": None}
    if not dns.get("ok"):
        return result
    started = time.perf_counter()
    try:
        context = ssl.create_default_context()
        with socket.create_connection((HOST, PORT), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=HOST) as tls:
                tls.sendall(
                    (
                        f"GET / HTTP/1.1\r\nHost: {HOST}\r\n"
                        f"User-Agent: {USER_AGENT}\r\nConnection: close\r\n\r\n"
                    ).encode()
                )
                head = tls.recv(256)
        first = head.split(b"\r\n", 1)[0].decode("latin1", "replace")
        status = int(first.split(" ")[1]) if " " in first else 0
        result["tls"] = {
            "ok": True,
            "status": status,
            "first_line": first,
            "ms": round((time.perf_counter() - started) * 1000, 1),
        }
        run.info("API_PROBE_OK", status=status, ms=result["tls"]["ms"])
    except Exception as exc:
        result["tls"] = {
            "ok": False,
            "error": str(exc),
            "ms": round((time.perf_counter() - started) * 1000, 1),
        }
        run.error("API_PROBE_FAILED", error=str(exc))
    return result


def describe_status(result: FetchResult) -> dict[str, Any]:
    """Small debug view used by --verbose and the GUI log."""

    return {
        "host": HOST,
        "token_len": len(result.token.token),
        "session": result.token.session.hex(),
        "build": result.token.build,
        "stats_len": len(result.stats_raw),
    }
