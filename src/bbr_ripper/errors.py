"""Stable error codes and user-facing remediation for BattleBit Stat Ripper.

Every failure that can stop a run is classified here.  The GUI and CLI show the
same code, cause, and fix, and the run log records the full traceback.

Codes are stable.  If a support thread says `BBR-A002`, the meaning does not
change between releases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RipperError(Exception):
    code: str
    title: str
    cause: str
    fix: str
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    original: BaseException | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, f"{self.code}: {self.title}")

    def user_message(self) -> str:
        lines = [
            f"[{self.code}] {self.title}",
            "",
            f"What happened: {self.cause}",
            "",
            f"What to do: {self.fix}",
        ]
        if self.details:
            lines.append("")
            lines.append("Details:")
            for key, value in self.details.items():
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "cause": self.cause,
            "fix": self.fix,
            "details": self.details,
            "retryable": self.retryable,
            "exception": type(self).__name__,
        }


# Common factories -----------------------------------------------------------

def steam_not_running() -> RipperError:
    return RipperError(
        "BBR-S001",
        "Steam is not running or not signed in",
        "The Steam client did not accept the local Steamworks initialisation.",
        "Open Steam, sign in, and leave it running. The BattleBit game itself "
        "does not need to be open. Then press Rip again.",
        retryable=True,
    )


def game_not_found(searched: list[str] | None = None) -> RipperError:
    return RipperError(
        "BBR-S003",
        "BattleBit Remastered is not installed in a Steam library",
        "The app could not find BattleBit.exe and the game's steam_api64.dll.",
        "Install BattleBit through Steam, or move it into a Steam library that "
        "Steam knows about. If it is installed on another drive, open Steam > "
        "Settings > Storage and add that library.",
        details={"searched": "; ".join(searched or [])[:1200]},
    )


def dll_load_failed(path: str, exc: BaseException) -> RipperError:
    return RipperError(
        "BBR-S004",
        "The game's Steam library could not be loaded",
        f"Windows refused to load {path}: {exc}",
        "Check that BattleBit is fully installed (Steam > right-click > "
        "Properties > Installed Files > Verify integrity). If an antivirus "
        "quarantined steam_api64.dll, restore it and allow the game folder.",
        details={"dll": path, "error": str(exc)},
        original=exc,
    )


def ticket_refused(detail: str = "") -> RipperError:
    return RipperError(
        "BBR-S005",
        "Steam would not issue an auth ticket",
        "Steamworks returned no ticket. This usually means Steam is offline, "
        "the account does not own BattleBit, or the Steam client is still starting.",
        "Make sure Steam is signed in to the account that owns BattleBit, wait a "
        "few seconds, and try again. If Steam just updated, restart Steam.",
        details={"steam_detail": detail} if detail else {},
        retryable=True,
    )


def api_unreachable(exc: BaseException) -> RipperError:
    return RipperError(
        "BBR-A001",
        "Could not reach api.battlebit.cloud",
        f"The HTTPS request failed: {exc}",
        "Check your internet connection and any VPN/firewall. The API is "
        "Cloudflare-fronted; if a proxy is blocking it, allow "
        "api.battlebit.cloud on port 443. Try again in a minute.",
        details={"error": str(exc)},
        retryable=True,
        original=exc,
    )


def token_rejected(status: int, body: bytes) -> RipperError:
    return RipperError(
        "BBR-A002",
        "BattleBit rejected the Steam session (HTTP 403)",
        "The master server did not accept the auth ticket. The ticket can be "
        "rejected if Steam is not fully signed in, the account does not own the "
        "game, or a previous ticket was already consumed.",
        "Open Steam, confirm you are signed in to the owning account, then press "
        "Rip again. If it keeps failing, restart Steam and retry.",
        details={
            "status": status,
            "response_bytes": len(body),
            "response_head": body[:80].hex(),
        },
        retryable=True,
    )


def stats_rejected(status: int, body: bytes) -> RipperError:
    return RipperError(
        "BBR-A003",
        "BattleBit rejected the stats request (HTTP 403)",
        "The session token was not accepted for /Player/GetStats.",
        "Try again. If it persists, close and reopen Steam, then rip again. The "
        "game does not need to be running.",
        details={
            "status": status,
            "response_bytes": len(body),
            "response_head": body[:80].hex(),
        },
        retryable=True,
    )


def http_error(path: str, status: int, body: bytes) -> RipperError:
    retryable = status == 429 or 500 <= status < 600
    return RipperError(
        "BBR-A004",
        f"BattleBit API returned HTTP {status}",
        f"The request to {path} failed with status {status}.",
        "Wait a minute and try again. If it is a 5xx or 429, the API is busy; "
        "the ripper already retries transient failures.",
        details={
            "path": path,
            "status": status,
            "response_bytes": len(body),
            "response_head": body[:120].hex(),
        },
        retryable=retryable,
    )


def token_malformed(body: bytes) -> RipperError:
    return RipperError(
        "BBR-A005",
        "BattleBit returned an unexpected token response",
        "The /Tokens/GetToken response did not match the known layout. The game "
        "or API may have been updated.",
        "Try again. If it keeps happening, keep the log and open an issue with "
        "the run ID; the raw response is in the log folder.",
        details={"response_bytes": len(body), "response_head": body[:120].hex()},
    )


def stats_malformed(body: bytes) -> RipperError:
    return RipperError(
        "BBR-A006",
        "BattleBit returned an empty or truncated stats response",
        "The /Player/GetStats response was too short to contain a profile.",
        "Try again. If it persists, check the run log for the response length "
        "and open an issue with the run ID.",
        details={"response_bytes": len(body), "response_head": body[:120].hex()},
        retryable=True,
    )


def decode_failed(message: str, raw: bytes) -> RipperError:
    return RipperError(
        "BBR-D001",
        "The BattleBit profile layout changed",
        f"The response arrived ({len(raw):,} bytes) but could not be decoded: {message}",
        "Update the ripper. The raw response is saved so a new parser can "
        "recover it. Open an issue with the run ID and the size above.",
        details={"raw_bytes": len(raw), "raw_head": raw[:64].hex()},
    )


def export_failed(path: str, exc: BaseException) -> RipperError:
    return RipperError(
        "BBR-X001",
        "Could not write the profile files",
        f"Writing to {path} failed: {exc}",
        "Choose a folder you can write to (for example Documents), close any "
        "program locking the file, and try again.",
        details={"path": path, "error": str(exc)},
        original=exc,
    )


def unexpected(exc: BaseException) -> RipperError:
    return RipperError(
        "BBR-X002",
        "Unexpected error",
        f"{type(exc).__name__}: {exc}",
        "The run log has the full traceback. Copy the diagnostics from the app "
        "or open the log folder and attach the newest log to an issue.",
        details={"exception": type(exc).__name__},
        original=exc,
    )


# Mapping --------------------------------------------------------------------

def classify(exc: BaseException) -> RipperError:
    """Convert any exception into the stable user-facing error model."""

    if isinstance(exc, RipperError):
        return exc

    # Import locally to avoid circular imports at module load.
    try:
        from .api import ApiError
    except Exception:  # pragma: no cover
        ApiError = ()  # type: ignore[assignment]

    try:
        from .decoder import DecodeError
    except Exception:  # pragma: no cover
        DecodeError = ()  # type: ignore[assignment]

    try:
        from .steam import SteamError
    except Exception:  # pragma: no cover
        SteamError = ()  # type: ignore[assignment]

    if isinstance(exc, DecodeError):
        return decode_failed(str(exc), getattr(exc, "raw", b""))
    if isinstance(exc, ApiError):
        status = getattr(exc, "status", None)
        body = getattr(exc, "body", b"")
        code = getattr(exc, "code", None)
        if code == "BBR-A002":
            return token_rejected(status or 403, body)
        if code == "BBR-A003":
            return stats_rejected(status or 403, body)
        if code == "BBR-A005":
            return token_malformed(body)
        if code == "BBR-A006":
            return stats_malformed(body)
        if status is not None:
            return http_error("api.battlebit.cloud", status, body)
        return api_unreachable(exc)
    if isinstance(exc, SteamError):
        return RipperError(
            "BBR-S002",
            "Steam bridge failed",
            str(exc),
            "Open Steam, sign in, and retry. If the game was just updated, "
            "restart Steam so the local Steamworks interface is available.",
            retryable=True,
            original=exc,
        )
    if isinstance(exc, PermissionError):
        return export_failed("the output folder", exc)
    if isinstance(exc, (TimeoutError,)):
        return RipperError(
            "BBR-A001",
            "The BattleBit API timed out",
            "The HTTPS request did not finish in time.",
            "Check your connection and try again.",
            retryable=True,
            original=exc,
        )
    return unexpected(exc)
