"""Steam OpenID 2.0 sign-in (no Web API key required).

The browser is sent to Steam with a signed return URL; Steam redirects back
with openid.* parameters, and the server confirms them by POSTing
check_authentication back to Steam. Only Steam's answer is trusted.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from typing import Mapping

ENDPOINT = "https://steamcommunity.com/openid/login"
NS = "http://specs.openid.net/auth/2.0"
IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"
CLAIMED_RE = re.compile(r"^https://steamcommunity\.com/openid/id/(\d{16,18})$")


def build_login_url(return_to: str, realm: str) -> str:
    params = {
        "openid.ns": NS,
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": realm,
        "openid.identity": IDENTIFIER_SELECT,
        "openid.claimed_id": IDENTIFIER_SELECT,
    }
    return f"{ENDPOINT}?{urllib.parse.urlencode(params)}"


def verify(params: Mapping[str, str], timeout: int = 10) -> str | None:
    """Return the SteamID64 when Steam confirms the assertion, else None."""
    payload = {key: value for key, value in params.items() if key.startswith("openid.")}
    if payload.get("openid.mode") != "id_res":
        return None
    payload["openid.mode"] = "check_authentication"
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "BattleBitProfiles/0.3",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = response.read(32_768).decode("utf-8", errors="ignore")
    except Exception:
        return None
    if not re.search(r"^is_valid:\s*true\s*$", answer, re.MULTILINE):
        return None
    match = CLAIMED_RE.match(params.get("openid.claimed_id", ""))
    return match.group(1) if match else None
