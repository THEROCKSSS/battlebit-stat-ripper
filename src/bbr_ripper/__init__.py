"""BattleBit Stat Ripper - portable player profiles from the official API."""

from .api import ApiError, FetchResult, fetch
from .decoder import DecodeError, DecodedStats, ToolProgress, decode
from .errors import RipperError
from .exporter import SCHEMA, build_profile, render_text, write_exports
from .logging_setup import RunLogger, default_data_dir, default_log_dir
from .steam import SteamError, SteamSession, find_battlebit

__all__ = [
    "ApiError",
    "DecodeError",
    "DecodedStats",
    "FetchResult",
    "RipperError",
    "RunLogger",
    "SCHEMA",
    "SteamError",
    "SteamSession",
    "ToolProgress",
    "build_profile",
    "decode",
    "default_data_dir",
    "default_log_dir",
    "fetch",
    "find_battlebit",
    "render_text",
    "write_exports",
]

__version__ = "0.2.0"
