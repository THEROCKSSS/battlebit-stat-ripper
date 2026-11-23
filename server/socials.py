"""Profile and clan social links: validation, storage, and display metadata."""

from __future__ import annotations

import json
from urllib.parse import urlparse

SOCIALS = {
    "discord": {
        "label": "Discord",
        "icon": "discord",
        "hint": "discord.gg/your-invite",
        "hosts": ("discord.gg", "discord.com", "discordapp.com"),
    },
    "youtube": {
        "label": "YouTube",
        "icon": "youtube",
        "hint": "youtube.com/@yourchannel",
        "hosts": ("youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"),
    },
    "twitch": {
        "label": "Twitch",
        "icon": "twitch",
        "hint": "twitch.tv/yourchannel",
        "hosts": ("twitch.tv", "www.twitch.tv", "m.twitch.tv"),
    },
    "x": {
        "label": "X",
        "icon": "x",
        "hint": "x.com/yourhandle",
        "hosts": ("x.com", "www.x.com", "twitter.com", "www.twitter.com"),
    },
    "tiktok": {
        "label": "TikTok",
        "icon": "tiktok",
        "hint": "tiktok.com/@yourhandle",
        "hosts": ("tiktok.com", "www.tiktok.com", "m.tiktok.com"),
    },
    "website": {
        "label": "Website",
        "icon": "globe",
        "hint": "https://your-site.example",
        "hosts": (),
    },
}

MAX_URL = 300


def _normalise_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if len(value) > MAX_URL:
        raise ValueError("That link is too long (max 300 characters).")
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Links must be a full http:// or https:// address.")
    if parsed.username or parsed.password:
        raise ValueError("Links cannot contain a username or password.")
    return value


def parse_socials(form) -> dict[str, str]:
    """Read the six social fields from a form, validating each non-empty one."""
    result: dict[str, str] = {}
    for key, spec in SOCIALS.items():
        raw = (form.get(f"social_{key}") or "").strip()
        if not raw:
            continue
        url = _normalise_url(raw)
        host = (urlparse(url).hostname or "").lower()
        if spec["hosts"] and host not in spec["hosts"]:
            raise ValueError(
                f"{spec['label']} links must point to {spec['hosts'][0]}."
            )
        result[key] = url
    return result


def dumps(socials: dict[str, str]) -> str:
    return json.dumps(socials, ensure_ascii=False, sort_keys=True)


def loads(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    clean = {}
    for key in SOCIALS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            clean[key] = value.strip()
    return clean


def links(raw: str | None) -> list[dict[str, str]]:
    """Return display-ready links in a stable order."""
    values = loads(raw)
    out = []
    for key, spec in SOCIALS.items():
        if key in values:
            out.append(
                {
                    "key": key,
                    "label": spec["label"],
                    "icon": spec["icon"],
                    "url": values[key],
                }
            )
    return out
