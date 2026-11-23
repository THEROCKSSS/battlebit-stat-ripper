"""Command-line entry point for BattleBit Stat Ripper."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import errors, history
from .api import ApiError, fetch, probe_api
from .decoder import DecodeError, decode
from .exporter import build_profile, write_exports
from .logging_setup import (
    RunLogger,
    default_data_dir,
    default_log_dir,
    latest_log,
)
from .steam import SteamSession, steam_process_running
from .tool_names import TOOL_NAMES, pretty_name

__version__ = "0.2.0"
APP_NAME = "BattleBit Stat Ripper"
TOOL_LABELS = {tool_id: pretty_name(tool_id) for tool_id in TOOL_NAMES}


@dataclass
class RipOutcome:
    profile: dict
    paths: list[Path]
    persona: str
    steam_id: int
    run_id: str
    log_path: Path
    diagnostics_path: Path | None = None
    snapshot_id: int | None = None
    snapshot_inserted: bool = False
    previous_snapshot: dict[str, Any] | None = None


@dataclass
class DiagnoseOutcome:
    run_id: str
    log_path: Path
    diagnostics_path: Path
    checks: dict[str, Any] = field(default_factory=dict)


def default_output_dir() -> Path:
    documents = Path.home() / "Documents"
    if not documents.is_dir():
        documents = Path.home()
    return documents / "BattleBit Stats Ripper"


def _make_run(log_dir: Path | None = None, console: bool = False) -> RunLogger:
    return RunLogger(log_dir=log_dir, version=__version__, console=console)


def _wait_for_steam(run: RunLogger, seconds: int) -> None:
    if seconds <= 0:
        return
    deadline = time.monotonic() + seconds
    step = run.step("wait_for_steam", timeout_s=seconds)
    while time.monotonic() < deadline:
        if steam_process_running():
            run.end_step(step, ok=True)
            return
        time.sleep(3)
    run.end_step(step, ok=False, timeout=True)
    err = errors.steam_not_running()
    err.details["waited_seconds"] = seconds
    raise err


def rip(
    out_dir: Path | None = None,
    log: Callable[[str], None] | None = None,
    write_json: bool = True,
    write_text: bool = True,
    run: RunLogger | None = None,
    keep_history: bool = True,
    wait_for_steam: int = 0,
) -> RipOutcome:
    """Capture and export the signed-in Steam user's BattleBit profile."""

    run = run or _make_run()
    target = (out_dir or default_output_dir()).expanduser().resolve()
    diagnostics: Path | None = None

    def emit(message: str) -> None:
        run.info("USER", text=message)
        if log:
            log(message)

    try:
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise errors.export_failed(str(target), exc) from exc
        emit(f"Output folder: {target}")
        emit(f"Run ID: {run.run_id}")

        if wait_for_steam:
            emit(f"Waiting up to {wait_for_steam}s for Steam...")
            _wait_for_steam(run, wait_for_steam)

        emit("Looking for the BattleBit install...")
        with SteamSession(run=run) as steam:
            identity = steam.identity()
            emit(f"Steam user: {identity.persona_name or '(no persona)'} ({identity.steam_id})")

            emit("Requesting a BattleBit session from the official API...")
            result = fetch(steam.steam_id, steam.ticket, run=run)
            emit(f"Received {len(result.stats_raw):,} bytes ({result.token.build or 'unknown build'}).")

            step = run.step("decode", bytes=len(result.stats_raw))
            decoded = decode(result.stats_raw, tool_names=TOOL_LABELS)
            run.end_step(
                step,
                ok=decoded.schema_ok,
                fields=len(decoded.fields),
                tools=len(decoded.tools),
                warnings=decoded.warnings,
                raw_sha256=decoded.raw_sha256,
            )
            if not decoded.schema_ok:
                emit("Warning: response does not match the verified schema; raw bytes are preserved.")
            emit(
                f"Profile: rank {decoded.fields.get('rank', 0):,}, "
                f"{decoded.fields.get('kills', 0):,} kills, "
                f"{decoded.fields.get('deaths', 0):,} deaths."
            )

            profile = build_profile(result, decoded, identity, version=__version__)
            profile["run_id"] = run.run_id
            snapshot_id = None
            inserted = False
            previous = None
            if keep_history:
                hstep = run.step("history")
                try:
                    snapshot_id, inserted, previous = history.append_snapshot(
                        profile, run_id=run.run_id
                    )
                    run.end_step(
                        hstep,
                        ok=True,
                        snapshot_id=snapshot_id,
                        inserted=inserted,
                        previous=previous,
                    )
                    if inserted:
                        emit(f"Saved snapshot #{snapshot_id} to local history.")
                    else:
                        emit(f"Snapshot #{snapshot_id} already in local history.")
                except Exception as exc:
                    run.end_step(hstep, ok=False, error=str(exc))
                    run.warning("HISTORY_FAILED", error=str(exc))
                    emit(f"Warning: local history was not updated: {exc}")

            profile["local"] = {
                "snapshot_id": snapshot_id,
                "snapshot_inserted": inserted,
                "history_db": str(history.default_history_path()),
                "run_id": run.run_id,
            }

            estep = run.step("export", target=str(target))
            try:
                paths = write_exports(
                    profile,
                    target,
                    persona=identity.persona_name,
                    write_json=write_json,
                    write_text=write_text,
                )
            except OSError as exc:
                run.end_step(estep, ok=False, error=str(exc))
                raise errors.export_failed(str(target), exc) from exc
            run.end_step(estep, ok=True, files=[str(p) for p in paths], json=write_json, text=write_text)
            emit(f"Wrote {len(paths)} file(s) to {target}")

            run.finish(
                "ok",
                persona=identity.persona_name,
                steam_id=identity.steam_id,
                raw_bytes=len(result.stats_raw),
                rank=decoded.fields.get("rank"),
                kills=decoded.fields.get("kills"),
                deaths=decoded.fields.get("deaths"),
                schema_ok=decoded.schema_ok,
                snapshot_id=snapshot_id,
                snapshot_inserted=inserted,
                files=[str(p) for p in paths],
                output_dir=str(target),
            )
            run.cleanup()
            return RipOutcome(
                profile=profile,
                paths=paths,
                persona=identity.persona_name,
                steam_id=identity.steam_id,
                run_id=run.run_id,
                log_path=run.log_path,
                snapshot_id=snapshot_id,
                snapshot_inserted=inserted,
                previous_snapshot=previous,
            )
    except KeyboardInterrupt:
        run.finish("cancelled")
        run.cleanup()
        raise
    except BaseException as exc:
        classified = errors.classify(exc)
        run.record_error(classified.original or exc, code=classified.code)
        run.result = {"status": "error", "code": classified.code, "title": classified.title}
        try:
            diagnostics = run.write_diagnostics()
        except Exception as diag_exc:
            run.warning("DIAGNOSTICS_FAILED", error=str(diag_exc))
        run.finish(
            "error",
            code=classified.code,
            title=classified.title,
            cause=classified.cause,
            diagnostics=str(diagnostics) if diagnostics else "",
            log=str(run.log_path),
        )
        run.cleanup()
        classified.details.setdefault("run_id", run.run_id)
        classified.details.setdefault("log", str(run.log_path))
        if diagnostics:
            classified.details.setdefault("diagnostics", str(diagnostics))
        raise classified from exc


def diagnose(log_dir: Path | None = None, console: bool = False) -> DiagnoseOutcome:
    """Environment + Steam + API reachability.  Never fetches a profile."""

    run = _make_run(log_dir=log_dir, console=console)
    checks: dict[str, Any] = {}
    try:
        env = run.environment()
        checks["environment"] = env
        try:
            with SteamSession(run=run) as steam:
                ident = steam.identity()
                checks["steam"] = {
                    "ok": True,
                    "steam_id": ident.steam_id,
                    "persona": ident.persona_name,
                    "dll": str(ident.dll_path),
                    "ticket_bytes": len(steam.ticket),
                }
        except Exception as exc:
            err = errors.classify(exc)
            run.record_error(err.original or exc, code=err.code)
            checks["steam"] = {"ok": False, **err.to_dict()}
        try:
            checks["api"] = probe_api(run)
        except Exception as exc:
            err = errors.classify(exc)
            run.record_error(err.original or exc, code=err.code)
            checks["api"] = {"ok": False, **err.to_dict()}
        ok = bool(checks.get("steam", {}).get("ok")) and bool(
            checks.get("api", {}).get("tls", {}).get("ok")
        )
        status = "ok" if ok else "warn"
        run.result = {"status": status, "checks": checks}
        diagnostics = run.write_diagnostics()
        run.finish(status, checks=checks, diagnostics=str(diagnostics))
        run.cleanup()
        return DiagnoseOutcome(
            run_id=run.run_id,
            log_path=run.log_path,
            diagnostics_path=diagnostics,
            checks=checks,
        )
    except BaseException as exc:
        classified = errors.classify(exc)
        run.record_error(classified.original or exc, code=classified.code)
        run.result = {"status": "error", "code": classified.code, "title": classified.title}
        diagnostics = run.write_diagnostics()
        run.finish("error", code=classified.code, diagnostics=str(diagnostics))
        run.cleanup()
        raise classified from exc


def _open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        import subprocess

        subprocess.Popen(["open", str(path)])
    else:
        webbrowser.open(path.as_uri())


def _print_summary(outcome: RipOutcome) -> None:
    p = outcome.profile["progress"]
    d = outcome.profile["derived"]
    print()
    print("=" * 62)
    print(f"  {outcome.persona or 'Player'}  ({outcome.steam_id})")
    print("=" * 62)
    print(f"  Rank        : {p.get('rank', 0):,} (prestige {p.get('prestige', 0):,})")
    print(f"  Kills       : {p.get('kills', 0):,}")
    print(f"  Deaths      : {p.get('deaths', 0):,}")
    print(f"  K/D         : {d.get('kd', 0):.2f}")
    print(f"  Wins/Losses : {p.get('wins', 0):,} / {p.get('losses', 0):,}")
    print(f"  Total score : {p.get('total_score', 0):,}")
    print(f"  Playtime    : {d.get('hours_played', 0):,.1f} hours")
    print()
    if outcome.snapshot_id:
        state = "saved" if outcome.snapshot_inserted else "already present"
        print(f"  History     : snapshot #{outcome.snapshot_id} ({state})")
    print(f"  Log         : {outcome.log_path}")
    for path in outcome.paths:
        print(f"  File        : {path}")
    print()


def _print_diagnose(outcome: DiagnoseOutcome) -> None:
    checks = outcome.checks
    steam = checks.get("steam", {})
    api = checks.get("api", {})
    print()
    print("=" * 62)
    print("  DIAGNOSTICS")
    print("=" * 62)
    print(f"  Run ID      : {outcome.run_id}")
    print(f"  Steam       : {'OK' if steam.get('ok') else 'FAILED'}")
    if steam.get("ok"):
        print(f"    User      : {steam.get('persona')} ({steam.get('steam_id')})")
        print(f"    DLL       : {steam.get('dll')}")
        print(f"    Ticket    : {steam.get('ticket_bytes')} bytes")
    else:
        print(f"    [{steam.get('code')}] {steam.get('title')}")
    dns = api.get("dns", {})
    tls = api.get("tls") or {}
    print(f"  API DNS     : {'OK' if dns.get('ok') else 'FAILED'} ({dns.get('ms')} ms)")
    print(f"  API TLS     : {'OK' if tls.get('ok') else 'FAILED'} ({tls.get('ms')} ms)")
    if tls.get("ok"):
        print(f"    Response  : {tls.get('first_line')} (bare GET probe; the POST endpoints are separate)")
    elif tls:
        print(f"    Error     : {tls.get('error')}")
    print(f"  Log         : {outcome.log_path}")
    print(f"  Diagnostics : {outcome.diagnostics_path}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bbr-ripper",
        description="Capture your own BattleBit Remastered profile using Steam.",
    )
    parser.add_argument("--out", type=Path, default=None, help="Output directory")
    parser.add_argument("--json-only", action="store_true", help="Do not write the .txt sheet")
    parser.add_argument("--quiet", action="store_true", help="Only print the output paths")
    parser.add_argument("--verbose", action="store_true", help="Print detailed progress")
    parser.add_argument("--open", action="store_true", help="Open the output folder when done")
    parser.add_argument("--probe", action="store_true", help="Only check Steam and print the identity")
    parser.add_argument("--diagnose", action="store_true", help="Run Steam + API diagnostics and write a report")
    parser.add_argument("--log-dir", type=Path, default=None, help="Override the log directory")
    parser.add_argument("--no-history", action="store_true", help="Do not append to local history")
    parser.add_argument("--history-csv", type=Path, default=None, help="Export local history to CSV and exit")
    parser.add_argument(
        "--wait-for-steam",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait up to N seconds for Steam before starting",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    def log(message: str) -> None:
        if not args.quiet:
            print(f"[*] {message}")

    try:
        if args.history_csv:
            target = history.export_csv(args.history_csv)
            print(target)
            return 0

        if args.diagnose:
            outcome = diagnose(log_dir=args.log_dir, console=args.verbose)
            if args.quiet:
                print(outcome.diagnostics_path)
            else:
                _print_diagnose(outcome)
            return 0

        if args.probe:
            run = _make_run(log_dir=args.log_dir)
            try:
                with SteamSession(run=run) as steam:
                    ident = steam.identity()
                    print(f"Steam user : {ident.persona_name}")
                    print(f"Steam ID   : {ident.steam_id}")
                    print(f"Steam DLL  : {ident.dll_path}")
                    print(f"Ticket     : {len(steam.ticket)} bytes")
                run.finish("ok", probe="steam")
            except BaseException as exc:
                classified = errors.classify(exc)
                run.record_error(classified.original or exc, code=classified.code)
                run.result = {"status": "error", "code": classified.code, "title": classified.title}
                diagnostics = run.write_diagnostics()
                run.finish("error", code=classified.code)
                print(classified.user_message(), file=sys.stderr)
                print(f"Diagnostics: {diagnostics}", file=sys.stderr)
                return 2
            finally:
                run.cleanup()
            return 0

        outcome = rip(
            out_dir=args.out,
            log=log if (args.verbose or not args.quiet) else None,
            write_json=True,
            write_text=not args.json_only,
            keep_history=not args.no_history,
            wait_for_steam=args.wait_for_steam,
        )
        if args.quiet:
            for path in outcome.paths:
                print(path)
        else:
            _print_summary(outcome)
        if args.open:
            _open_folder(args.out or default_output_dir())
        return 0
    except errors.RipperError as exc:
        print("\n" + exc.user_message(), file=sys.stderr)
        print(f"\nLog: {exc.details.get('log', latest_log(args.log_dir) or 'n/a')}", file=sys.stderr)
        if exc.details.get("diagnostics"):
            print(f"Diagnostics: {exc.details['diagnostics']}", file=sys.stderr)
        code = exc.code
        if code.startswith("BBR-S"):
            return 2
        if code.startswith("BBR-A"):
            return 3
        if code.startswith("BBR-D"):
            return 4
        return 5
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
