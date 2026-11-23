"""Fetch public Steam profile data and cache its media locally.

Uses Steam's public profile XML (name, real name, summary, avatar, location,
member-since) plus the public profile HTML for the avatar frame, level, status,
and animated-background poster. No Steam Web API key is required, and private
profiles still expose their public header fields.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

XML_URL = "https://steamcommunity.com/profiles/{steam_id}/?xml=1"
VANITY_URL = "https://steamcommunity.com/id/{vanity}/?xml=1"
HTML_URL = "https://steamcommunity.com/profiles/{steam_id}/?l=english"
USER_AGENT = (
    "BattleBitProfiles/0.3 (+https://github.com/THEROCKSSS/battlebit-stat-ripper)"
)
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_HOST_SUFFIXES = (
    ".steamstatic.com",
    ".steamusercontent.com",
)
STEAM_ID_RE = re.compile(r"^\d{16,18}$")
_MIME_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
}
_TAG_RE = re.compile(r"<[^>]+>")


class SteamError(RuntimeError):
    """The Steam profile could not be resolved or read."""


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = _TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def resolve_steam_id(value: str) -> str:
    """Accept a SteamID64, a /profiles/ URL, or a vanity name or /id/ URL."""
    raw = (value or "").strip()
    if not raw:
        raise SteamError("Enter a Steam ID, profile URL, or vanity name.")
    if STEAM_ID_RE.match(raw):
        return raw
    match = re.search(r"/profiles/(\d{16,18})", raw)
    if match:
        return match.group(1)
    vanity = ""
    match = re.search(r"/id/([A-Za-z0-9_.-]{2,64})", raw)
    if match:
        vanity = match.group(1)
    elif re.fullmatch(r"[A-Za-z0-9_.-]{2,64}", raw):
        vanity = raw
    if not vanity:
        raise SteamError(
            "That does not look like a Steam ID, profile link, or vanity name."
        )
    data = _get(VANITY_URL.format(vanity=urllib.parse.quote(vanity)))
    details = parse_xml(data)
    return details["steam_id"]


def _get(url: str, timeout: int = 15) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise SteamError("Steam profile URLs must use HTTPS.")
    host = (parsed.hostname or "").lower()
    if not (host == "steamcommunity.com" or host.endswith(".steamcommunity.com")):
        raise SteamError("Only steamcommunity.com profile URLs are supported.")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(MAX_PAGE_BYTES + 1)[:MAX_PAGE_BYTES]
    except Exception as exc:  # urllib raises several unrelated types
        raise SteamError(f"Steam did not answer for that profile ({exc}).") from exc


def parse_xml(data: bytes) -> dict[str, Any]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SteamError("Steam returned an unreadable profile document.") from exc
    error = root.findtext("error")
    if error:
        raise SteamError(clean_text(error) or "That Steam profile could not be found.")

    def text(tag: str) -> str:
        return clean_text(root.findtext(tag))

    steam_id = text("steamID64")
    if not STEAM_ID_RE.match(steam_id):
        raise SteamError("Steam did not return a SteamID64 for that profile.")
    created = text("timecreated")
    member_since = ""
    if created.isdigit():
        from datetime import datetime, timezone

        member_since = (
            datetime.fromtimestamp(int(created), timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )
    return {
        "steam_id": steam_id,
        "persona_name": text("steamID") or f"Player {steam_id[-4:]}",
        "real_name": text("realname"),
        "summary": text("summary"),
        "avatar_url": text("avatarFull") or text("avatarMedium"),
        "location": text("location"),
        "member_since": member_since,
        "online_state": text("onlineState"),
        "state_message": text("stateMessage"),
        "profile_url": f"https://steamcommunity.com/profiles/{steam_id}/",
    }


def parse_html(markup: str) -> dict[str, Any]:
    """Pull the header extras that only exist in the profile page."""
    result: dict[str, Any] = {
        "level": None,
        "status": "",
        "frame_url": "",
        "background_url": "",
    }
    level = re.search(r'friendPlayerLevelNum">\s*(\d+)\s*<', markup)
    if level:
        result["level"] = int(level.group(1))
    status = re.search(r'profile_in_game_header">([^<]+)<', markup)
    if status:
        text = clean_text(status.group(1))
        if text.lower().startswith("currently "):
            text = text[10:]
        result["status"] = text

    frame_at = markup.find("profile_avatar_frame")
    if frame_at != -1:
        block = markup[frame_at : frame_at + 1600]
        image = re.search(r'<img[^>]+src="([^"]+)"', block)
        if image:
            result["frame_url"] = html.unescape(image.group(1))
        else:
            source = re.search(r'srcset="([^"]+)"', block)
            if source:
                result["frame_url"] = html.unescape(source.group(1))

    background_at = markup.find("profile_animated_background")
    if background_at != -1:
        block = markup[background_at : background_at + 2400]
        poster = re.search(r'poster="([^"]+)"', block)
        if poster:
            result["background_url"] = html.unescape(poster.group(1))
        else:
            style = re.search(r"background-image:\s*url\(['\"]?([^'\")]+)", block)
            if style:
                result["background_url"] = html.unescape(style.group(1))
    return result


def _safe_asset_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host.endswith(suffix) for suffix in ALLOWED_HOST_SUFFIXES
    )


def download_asset(url: str, root: Path, stem: str, timeout: int = 20) -> str | None:
    """Download a Steam image into media_root/steam and return its filename."""
    if not url or not _safe_asset_url(url):
        return None
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            size = int(response.headers.get("Content-Length") or 0)
            if size > MAX_IMAGE_BYTES:
                return None
            payload = response.read(MAX_IMAGE_BYTES + 1)
            if len(payload) > MAX_IMAGE_BYTES:
                return None
            content_type = (response.headers.get("Content-Type") or "").split(";")[0]
    except Exception:
        return None
    extension = _MIME_EXT.get(content_type.strip().lower())
    if not extension:
        suffix = Path(urllib.parse.urlparse(url).path).suffix.lower().lstrip(".")
        extension = suffix if suffix in _MIME_EXT.values() else "img"
    target_dir = root / "steam"
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{stem}.{extension}"
    target = target_dir / filename
    if not target.exists() or target.stat().st_size != len(payload):
        target.write_bytes(payload)
    return filename


def fetch_all(steam_id: str) -> dict[str, Any]:
    xml = _get(XML_URL.format(steam_id=steam_id))
    markup = ""
    try:
        markup = _get(HTML_URL.format(steam_id=steam_id)).decode("utf-8", errors="ignore")
    except SteamError:
        markup = ""
    return {"xml": xml, "html": markup}


def build_record(
    steam_id: str,
    xml: bytes,
    markup: str,
    media_root: Path,
) -> dict[str, Any]:
    details = parse_xml(xml)
    extras = parse_html(markup) if markup else {
        "level": None,
        "status": "",
        "frame_url": "",
        "background_url": "",
    }
    avatar = download_asset(details["avatar_url"], media_root, f"{steam_id}-avatar")
    frame = download_asset(extras["frame_url"], media_root, f"{steam_id}-frame")
    background = download_asset(
        extras["background_url"], media_root, f"{steam_id}-background"
    )
    details.update(
        {
            "level": extras["level"],
            "status": extras["status"],
            "avatar_path": avatar,
            "frame_path": frame,
            "background_path": background,
        }
    )
    return details


def refresh_player(
    conn,
    steam_id: str,
    media_root: Path,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Fetch Steam data for one id and upsert it into the players table."""
    if not STEAM_ID_RE.match(steam_id):
        raise SteamError("That is not a valid SteamID64.")
    data = (fetcher or fetch_all)(steam_id)
    record = build_record(steam_id, data["xml"], data.get("html", ""), media_root)
    timestamp = now or _utc_now()
    conn.execute(
        """
        INSERT INTO players (
            steam_id, persona_name, real_name, summary, avatar_path, frame_path,
            background_path, location, member_since, level, status, profile_url,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(steam_id) DO UPDATE SET
            persona_name = excluded.persona_name,
            real_name = excluded.real_name,
            summary = excluded.summary,
            avatar_path = COALESCE(excluded.avatar_path, players.avatar_path),
            frame_path = COALESCE(excluded.frame_path, players.frame_path),
            background_path = COALESCE(excluded.background_path, players.background_path),
            location = excluded.location,
            member_since = excluded.member_since,
            level = excluded.level,
            status = excluded.status,
            profile_url = excluded.profile_url,
            updated_at = excluded.updated_at
        """,
        (
            record["steam_id"],
            record["persona_name"],
            record["real_name"],
            record["summary"],
            record["avatar_path"],
            record["frame_path"],
            record["background_path"],
            record["location"],
            record["member_since"],
            record["level"],
            record["status"],
            record["profile_url"],
            timestamp,
            timestamp,
        ),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM players WHERE steam_id = ?", (steam_id,)).fetchone())


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
