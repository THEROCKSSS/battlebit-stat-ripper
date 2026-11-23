"""Local Steamworks bridge for BattleBit Stat Ripper.

The ripper never touches the BattleBit process, game files, or EAC.  It asks
the locally running Steam client for the same kind of auth ticket BattleBit
itself uses, then hands that ticket to the official BattleBit API.  The ticket
belongs to the signed-in Steam user, so the API only ever returns that user's
own profile.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from ctypes import (
    POINTER,
    byref,
    c_bool,
    c_char_p,
    c_int,
    c_uint32,
    c_uint64,
    c_void_p,
    create_string_buffer,
)
from dataclasses import dataclass
from pathlib import Path

from . import errors
from .logging_setup import RunLogger

APP_ID = "671860"
GAME_DIR_NAME = "BattleBit Remastered"


class SteamError(RuntimeError):
    """Legacy name kept for callers that catch the Steam bridge broadly."""


def steam_process_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "steam.exe" in result.stdout.lower()
    except Exception:
        return False


@dataclass(frozen=True)
class SteamIdentity:
    steam_id: int
    persona_name: str
    dll_path: Path


def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                value, _ = winreg.QueryValueEx(key, "SteamPath")
                roots.append(Path(value))
        except OSError:
            pass
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"
            ) as key:
                value, _ = winreg.QueryValueEx(key, "InstallPath")
                roots.append(Path(value))
        except OSError:
            pass
    for fallback in (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Steam",
    ):
        roots.append(fallback)

    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _library_paths(steam_root: Path) -> list[Path]:
    libraries = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libraries
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        raw = match.group(1).replace("\\\\", "\\")
        path = Path(raw)
        if path not in libraries:
            libraries.append(path)
    return libraries


def find_battlebit() -> Path:
    """Return the BattleBit install directory, or raise SteamError."""

    candidates: list[Path] = []
    for root in _steam_roots():
        for library in _library_paths(root):
            candidates.append(library / "steamapps" / "common" / GAME_DIR_NAME)

    for candidate in candidates:
        if (candidate / "BattleBit.exe").is_file() and (
            candidate / "BattleBit_Data" / "Plugins" / "x86_64" / "steam_api64.dll"
        ).is_file():
            return candidate

    raise errors.game_not_found([str(c) for c in candidates])


def _dll_path(install: Path) -> Path:
    return install / "BattleBit_Data" / "Plugins" / "x86_64" / "steam_api64.dll"


class SteamSession:
    """Context manager that initialises Steamworks and exposes an auth ticket."""

    def __init__(self, run: RunLogger | None = None) -> None:
        self.run = run
        self.install = find_battlebit()
        self.dll_path = _dll_path(self.install)
        self._old_cwd: str | None = None
        self._tmp_dir: str | None = None
        self._dll: ctypes.CDLL | None = None
        self._user: int | None = None
        self.steam_id: int = 0
        self.persona_name: str = ""
        self.ticket: bytes = b""
        self.ticket_handle: int = 0
        if run:
            run.info(
                "STEAM_FOUND",
                install=str(self.install),
                dll=str(self.dll_path),
                dll_bytes=self.dll_path.stat().st_size if self.dll_path.exists() else 0,
            )

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "SteamSession":
        if sys.platform != "win32":
            raise errors.RipperError(
                "BBR-S002",
                "This build is Windows-only",
                "The Steamworks bridge uses the Windows Steam client.",
                "Run the Windows build on a Windows 10/11 machine.",
            )

        step = self.run.step("steam_init") if self.run else None
        self._old_cwd = os.getcwd()
        self._tmp_dir = tempfile.mkdtemp(prefix="bbr-ripper-steam-")
        # SteamAPI_Init reads steam_appid.txt from the current directory.
        Path(self._tmp_dir, "steam_appid.txt").write_text(APP_ID, encoding="ascii")
        os.chdir(self._tmp_dir)

        try:
            self._dll = ctypes.CDLL(str(self.dll_path))
        except OSError as exc:
            self._restore()
            if self.run:
                self.run.end_step(step, ok=False)
            raise errors.dll_load_failed(str(self.dll_path), exc) from exc

        self._dll.SteamAPI_Init.restype = c_bool
        init_ok = bool(self._dll.SteamAPI_Init())
        if not init_ok:
            self._restore()
            if self.run:
                self.run.end_step(step, ok=False, steam_process=steam_process_running())
            err = errors.steam_not_running()
            err.details["steam_process_running"] = steam_process_running()
            raise err

        self._dll.SteamAPI_SteamUser_v020.restype = c_void_p
        self._user = self._dll.SteamAPI_SteamUser_v020()
        if not self._user:
            self._restore()
            if self.run:
                self.run.end_step(step, ok=False)
            raise errors.RipperError(
                "BBR-S006",
                "Steam did not return a user interface",
                "Steamworks initialised but returned a null ISteamUser pointer.",
                "Restart Steam and try again. If it persists, update Steam and retry.",
            )

        self._dll.SteamAPI_ISteamUser_GetSteamID.argtypes = [c_void_p]
        self._dll.SteamAPI_ISteamUser_GetSteamID.restype = c_uint64
        self.steam_id = int(self._dll.SteamAPI_ISteamUser_GetSteamID(self._user))
        if not self.steam_id:
            self._restore()
            if self.run:
                self.run.end_step(step, ok=False)
            raise errors.RipperError(
                "BBR-S006",
                "Steam reported no Steam ID",
                "The client is running but the signed-in user has no Steam ID.",
                "Sign out of Steam, sign back in, and retry.",
            )

        try:
            self._dll.SteamAPI_SteamFriends_v017.restype = c_void_p
            friends = self._dll.SteamAPI_SteamFriends_v017()
            self._dll.SteamAPI_ISteamFriends_GetPersonaName.argtypes = [c_void_p]
            self._dll.SteamAPI_ISteamFriends_GetPersonaName.restype = c_char_p
            raw_name = self._dll.SteamAPI_ISteamFriends_GetPersonaName(friends)
            self.persona_name = raw_name.decode("utf-8", "replace") if raw_name else ""
        except Exception:
            self.persona_name = ""

        self._acquire_ticket()
        if self.run:
            self.run.end_step(
                step,
                ok=True,
                steam_id=self.steam_id,
                persona=self.persona_name,
                ticket_bytes=len(self.ticket),
            )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._cancel_ticket()
        try:
            if self._dll is not None:
                self._dll.SteamAPI_Shutdown()
        except Exception as shutdown_exc:
            if self.run:
                self.run.warning("STEAM_SHUTDOWN_FAILED", error=str(shutdown_exc))
        self._restore()
        if self.run:
            self.run.info("STEAM_SHUTDOWN", ok=exc_type is None, error=str(exc) if exc else "")

    def _restore(self) -> None:
        if self._old_cwd:
            try:
                os.chdir(self._old_cwd)
            except OSError:
                pass
            self._old_cwd = None
        if self._tmp_dir:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None

    # -- ticket ------------------------------------------------------------
    def _acquire_ticket(self) -> None:
        if self._dll is None or self._user is None:
            raise errors.RipperError(
                "BBR-S002",
                "Steam is not initialised",
                "The ticket request ran before Steamworks finished initialising.",
                "Retry the rip. If it persists, restart Steam.",
            )
        self._dll.SteamAPI_ISteamUser_GetAuthSessionTicket.argtypes = [
            c_void_p,
            c_void_p,
            c_int,
            POINTER(c_uint32),
            POINTER(c_uint32),
        ]
        self._dll.SteamAPI_ISteamUser_GetAuthSessionTicket.restype = c_uint32
        buf = create_string_buffer(8192)
        length = c_uint32(0)
        handle = c_uint32(0)
        step = self.run.step("steam_ticket") if self.run else None
        result = self._dll.SteamAPI_ISteamUser_GetAuthSessionTicket(
            self._user, buf, 8192, byref(length), byref(handle)
        )
        if not result or not length.value:
            if self.run:
                self.run.end_step(step, ok=False, result=result, length=length.value)
            raise errors.ticket_refused(f"result={result} length={length.value}")
        self.ticket = buf.raw[: length.value]
        self.ticket_handle = int(handle.value)
        fingerprint = hashlib.sha256(self.ticket).hexdigest()[:12]
        if self.run:
            self.run.end_step(
                step,
                ok=True,
                bytes=len(self.ticket),
                handle=self.ticket_handle,
                fingerprint=fingerprint,
            )
            # Never log the ticket itself; the fingerprint is enough to
            # correlate a run with an API rejection without exposing it.
            self.run.info(
                "STEAM_TICKET_READY",
                bytes=len(self.ticket),
                fingerprint=fingerprint,
                handle=self.ticket_handle,
            )

    def _cancel_ticket(self) -> None:
        if not self.ticket_handle or self._dll is None or self._user is None:
            return
        try:
            self._dll.SteamAPI_ISteamUser_CancelAuthTicket.argtypes = [c_void_p, c_uint32]
            self._dll.SteamAPI_ISteamUser_CancelAuthTicket(self._user, self.ticket_handle)
            if self.run:
                self.run.info("STEAM_TICKET_CANCELLED", handle=self.ticket_handle)
        except Exception as exc:
            if self.run:
                self.run.warning("STEAM_TICKET_CANCEL_FAILED", error=str(exc))
        self.ticket_handle = 0

    # -- convenience -------------------------------------------------------
    def identity(self) -> SteamIdentity:
        return SteamIdentity(self.steam_id, self.persona_name, self.dll_path)


def probe(run: RunLogger | None = None) -> SteamIdentity:
    """Small diagnostic: initialise Steam, read the identity, and exit."""

    with SteamSession(run=run) as session:
        return session.identity()
