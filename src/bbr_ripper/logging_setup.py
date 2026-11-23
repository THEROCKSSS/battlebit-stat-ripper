"""Durable run logs and shareable diagnostics.

Every run gets:

  %LOCALAPPDATA%\\BBR Stats Ripper\\logs\\run-<id>.log   full text log
  %LOCALAPPDATA%\\BBR Stats Ripper\\logs\\runs\\<id>.json structured summary
  %LOCALAPPDATA%\\BBR Stats Ripper\\diagnostics\\diagnostics-<id>.txt

The log never contains the Steam auth ticket.  It does contain the Steam ID and
public profile values, so treat a shared log as public information.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import socket
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_NAME = "BattleBit Stat Ripper"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(message)s"
LOG_DATE = "%Y-%m-%d %H:%M:%S"


def default_data_dir() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / "BBR Stats Ripper"
    return Path.home() / ".bbr-stats-ripper"


def default_log_dir() -> Path:
    return default_data_dir() / "logs"


def _safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    return str(value)


def _new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + os.urandom(2).hex()


@dataclass
class Step:
    name: str
    started_at: float
    fields: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


class RunLogger:
    """One logger per rip/diagnostic run."""

    def __init__(
        self,
        log_dir: Path | None = None,
        run_id: str | None = None,
        version: str = "0.1.0",
        level: int = logging.INFO,
        console: bool = False,
    ) -> None:
        self.run_id = run_id or _new_run_id()
        self.version = version
        self.log_dir = (log_dir or default_log_dir()).expanduser().resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / "runs").mkdir(exist_ok=True)
        (default_data_dir() / "diagnostics").mkdir(parents=True, exist_ok=True)

        self.log_path = self.log_dir / f"run-{self.run_id}.log"
        self.summary_path = self.log_dir / "runs" / f"{self.run_id}.json"
        self.steps: list[Step] = []
        self.errors: list[dict[str, Any]] = []
        self.result: dict[str, Any] = {}
        self.started_at = time.time()
        self._started_perf = time.perf_counter()
        self._step_stack: list[Step] = []

        self.logger = logging.getLogger(f"bbr.ripper.{self.run_id}")
        self.logger.setLevel(level)
        self.logger.propagate = False
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
        handler = logging.FileHandler(self.log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE))
        self.logger.addHandler(handler)
        self._file_handler = handler
        if console:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE))
            self.logger.addHandler(console_handler)

        self.info("RUN_START", run_id=self.run_id, version=version, pid=os.getpid())
        self.info("ENVIRONMENT", **self.environment())

    # -- basic logging -----------------------------------------------------
    def info(self, message: str, **fields: Any) -> None:
        self.logger.info(self._format(message, fields))

    def debug(self, message: str, **fields: Any) -> None:
        self.logger.debug(self._format(message, fields))

    def warning(self, message: str, **fields: Any) -> None:
        self.logger.warning(self._format(message, fields))

    def error(self, message: str, **fields: Any) -> None:
        self.logger.error(self._format(message, fields))

    @staticmethod
    def _format(message: str, fields: dict[str, Any]) -> str:
        if not fields:
            return message
        parts = []
        for key, value in fields.items():
            parts.append(f"{key}={_safe(value)!r}")
        return f"{message} " + " ".join(parts)

    # -- steps -------------------------------------------------------------
    def step(self, name: str, **fields: Any) -> Step:
        step = Step(name=name, started_at=time.perf_counter(), fields=_safe(fields))
        self._step_stack.append(step)
        self.info(f"STEP_START {name}", **fields)
        return step

    def end_step(self, step: Step | None = None, **fields: Any) -> Step:
        step = step or (self._step_stack[-1] if self._step_stack else None)
        if step is None:
            raise RuntimeError("end_step called with no active step")
        step.duration_ms = round((time.perf_counter() - step.started_at) * 1000, 1)
        step.fields.update(_safe(fields))
        if step in self._step_stack:
            self._step_stack.remove(step)
        self.steps.append(step)
        self.info(f"STEP_END {step.name} duration_ms={step.duration_ms}", **fields)
        return step

    # -- errors ------------------------------------------------------------
    def record_error(self, exc: BaseException, code: str | None = None) -> None:
        entry = {
            "code": code,
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }
        self.errors.append(entry)
        self.logger.error("ERROR code=%s type=%s message=%s", code, entry["type"], entry["message"])
        for line in entry["traceback"].rstrip().splitlines():
            self.logger.error("  %s", line)

    def finish(self, status: str, **result: Any) -> None:
        self.result = {"status": status, **_safe(result)}
        elapsed = round((time.perf_counter() - self._started_perf) * 1000, 1)
        summary = {
            "run_id": self.run_id,
            "app": APP_NAME,
            "version": self.version,
            "status": status,
            "started_at": datetime.fromtimestamp(self.started_at, timezone.utc).isoformat(),
            "duration_ms": elapsed,
            "result": self.result,
            "steps": [
                {"name": s.name, "duration_ms": s.duration_ms, "fields": s.fields}
                for s in self.steps
            ],
            "errors": self.errors,
            "environment": self.environment(),
            "log_file": str(self.log_path),
        }
        self.summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.info("RUN_END", status=status, duration_ms=elapsed, summary=str(self.summary_path))
        self._close_handlers()

    def _close_handlers(self) -> None:
        for handler in list(self.logger.handlers):
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass
            self.logger.removeHandler(handler)

    # -- environment -------------------------------------------------------
    def environment(self) -> dict[str, Any]:
        env: dict[str, Any] = {
            "platform": platform.platform(),
            "windows": platform.win32_ver()[0] if sys.platform == "win32" else "",
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "frozen": bool(getattr(sys, "frozen", False)),
            "cwd": os.getcwd(),
            "user_home": str(Path.home()),
            "log_dir": str(self.log_dir),
            "battlebit": "",
            "steam_api": "",
            "steam_running": False,
        }
        try:
            from .steam import find_battlebit

            install = find_battlebit()
            env["battlebit"] = str(install)
            env["steam_api"] = str(
                install / "BattleBit_Data" / "Plugins" / "x86_64" / "steam_api64.dll"
            )
        except Exception as exc:
            env["battlebit_error"] = str(exc)
        if sys.platform == "win32":
            try:
                import subprocess

                result = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                env["steam_running"] = "steam.exe" in result.stdout.lower()
            except Exception:
                pass
        return env

    def dns_check(self, host: str = "api.battlebit.cloud") -> dict[str, Any]:
        started = time.perf_counter()
        try:
            addresses = sorted({addr[4][0] for addr in socket.getaddrinfo(host, 443)})
            return {
                "host": host,
                "ok": True,
                "addresses": addresses[:8],
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }
        except Exception as exc:
            return {
                "host": host,
                "ok": False,
                "error": str(exc),
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }

    # -- diagnostics -------------------------------------------------------
    def diagnostics_text(self) -> str:
        env = self.environment()
        lines = [
            f"{APP_NAME} diagnostics",
            f"run_id: {self.run_id}",
            f"version: {self.version}",
            f"status: {self.result.get('status', 'running')}",
            f"log: {self.log_path}",
            "",
            "ENVIRONMENT",
        ]
        for key in sorted(env):
            lines.append(f"  {key}: {env[key]}")
        lines += ["", "DNS", f"  {json.dumps(_safe(self.dns_check()), indent=2)}"]
        lines += ["", "STEPS"]
        for step in self.steps:
            lines.append(f"  {step.name} ({step.duration_ms} ms) {json.dumps(step.fields, default=str)}")
        lines += ["", "ERRORS"]
        if not self.errors:
            lines.append("  (none)")
        for error in self.errors:
            lines.append(f"  [{error.get('code')}] {error['type']}: {error['message']}")
        lines += ["", "LOG TAIL"]
        lines.append(self.tail(160))
        lines += [
            "",
            "NOTE: no Steam auth ticket is stored in this file. It does contain",
            "the Steam ID and public profile values.",
        ]
        return "\n".join(lines) + "\n"

    def write_diagnostics(self, target: Path | None = None) -> Path:
        target = target or (default_data_dir() / "diagnostics" / f"diagnostics-{self.run_id}.txt")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.diagnostics_text(), encoding="utf-8")
        self.info("DIAGNOSTICS_WRITTEN", path=str(target))
        return target

    def tail(self, lines: int = 200) -> str:
        try:
            content = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(content[-lines:])
        except OSError as exc:
            return f"(could not read log: {exc})"

    # -- housekeeping ------------------------------------------------------
    def cleanup(self, keep: int = 40) -> None:
        try:
            logs = sorted(self.log_dir.glob("run-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in logs[keep:]:
                old.unlink(missing_ok=True)
            runs = sorted(
                (self.log_dir / "runs").glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in runs[keep:]:
                old.unlink(missing_ok=True)
            diag = sorted(
                (default_data_dir() / "diagnostics").glob("diagnostics-*.txt"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in diag[keep:]:
                old.unlink(missing_ok=True)
        except OSError:
            pass


def latest_log(log_dir: Path | None = None) -> Path | None:
    directory = log_dir or default_log_dir()
    logs = sorted(directory.glob("run-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def copy_diagnostics(source: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / source.name
    shutil.copy2(source, destination)
    return destination
