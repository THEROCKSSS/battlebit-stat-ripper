"""Upload a capture to a BattleBit profile site.

Used by ``--upload-url`` / ``--upload-token`` and the headless ``--watch`` loop.
The token is bound to one Steam ID server-side, so an upload cannot overwrite
another player's record.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class UploadError(RuntimeError):
    """The profile site rejected or could not receive the capture."""

    def __init__(self, message: str, code: str = "BBR-U001", status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def upload_profile(
    profile: dict[str, Any],
    base_url: str,
    token: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise UploadError("No upload URL was configured.", code="BBR-U001")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https"):
        raise UploadError("The upload URL must start with http:// or https://.", "BBR-U001")
    if not token:
        raise UploadError("No upload token was configured.", code="BBR-U002")

    body = json.dumps(profile, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + "/api/captures",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "BattleBitStatRipper/0.2",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(65_536)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read(8_192).decode("utf-8", "replace"))
            detail = str(payload.get("error") or "")
        except Exception:
            detail = ""
        status = exc.code
        if status == 401:
            raise UploadError(
                "The site rejected the upload token. Create a new token in Account.",
                code="BBR-U002",
                status=status,
            ) from exc
        if status == 403:
            raise UploadError(
                "That token is bound to a different Steam ID." + (f" {detail}" if detail else ""),
                code="BBR-U003",
                status=status,
            ) from exc
        if status == 429:
            raise UploadError(
                "The site is rate limiting uploads. The next scheduled run will retry.",
                code="BBR-U004",
                status=status,
            ) from exc
        raise UploadError(
            f"Upload failed with HTTP {status}." + (f" {detail}" if detail else ""),
            code="BBR-U005",
            status=status,
        ) from exc
    except Exception as exc:
        raise UploadError(f"Could not reach the site: {exc}", code="BBR-U005") from exc

    try:
        answer = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise UploadError("The site returned an unreadable upload response.", "BBR-U005") from exc
    if not answer.get("ok"):
        raise UploadError(str(answer.get("error") or "The site rejected the capture."), "BBR-U005")
    return answer
