"""Dark, one-click GUI for BattleBit Stat Ripper."""

from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import errors
from .cli import APP_NAME, __version__, default_output_dir, diagnose, rip
from .logging_setup import default_data_dir, default_log_dir, latest_log

BG = "#0f1115"
CARD = "#171a21"
CARD_2 = "#1d212a"
FG = "#e8eaed"
MUTED = "#9aa0a6"
ACCENT = "#f0a43a"
GOOD = "#4ade80"
BAD = "#f87171"
BORDER = "#2a2f3a"
ERR_BG = "#1d1417"
ERR_BORDER = "#5a2a2a"


class RipperApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {__version__}")
        self.geometry("760x720")
        self.minsize(680, 620)
        self.configure(bg=BG)

        self.out_dir = default_output_dir()
        self.last_outcome = None
        self.last_error: errors.RipperError | None = None
        self.last_error_text = ""
        self._busy = False

        self._build_style()
        self._build_ui()
        self._append("Ready. Steam must be running and signed in.")
        self._append(f"Exports: {self.out_dir}")
        self._append(f"Logs: {default_log_dir()}")

    # -- styling -----------------------------------------------------------
    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Rip.TButton",
            background=ACCENT,
            foreground="#16120a",
            borderwidth=0,
            focusthickness=0,
            padding=(18, 10),
            font=("Segoe UI", 11, "bold"),
        )
        style.map("Rip.TButton", background=[("active", "#ffc266"), ("disabled", "#5a4a2a")])
        style.configure(
            "Ghost.TButton",
            background=CARD_2,
            foreground=FG,
            borderwidth=0,
            padding=(11, 7),
            font=("Segoe UI", 9),
        )
        style.map("Ghost.TButton", background=[("active", "#262c38"), ("disabled", "#1a1e26")])

    def _build_ui(self) -> None:
        outer = tk.Frame(self, bg=BG, padx=22, pady=16)
        outer.pack(fill="both", expand=True)

        tk.Label(
            outer,
            text="BATTLEBIT STAT RIPPER",
            bg=BG,
            fg=FG,
            font=("Segoe UI Semibold", 20),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            outer,
            text="Portable player profiles, straight from the official API.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(fill="x", pady=(2, 14))

        card = tk.Frame(outer, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=CARD, padx=18, pady=14)
        inner.pack(fill="x")

        self.status_var = tk.StringVar(value="Ready")
        self.detail_var = tk.StringVar(
            value="Reads only your own profile. No game files are touched, no admin required."
        )
        tk.Label(
            inner,
            textvariable=self.status_var,
            bg=CARD,
            fg=ACCENT,
            font=("Segoe UI Semibold", 13),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            inner,
            textvariable=self.detail_var,
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=660,
        ).pack(fill="x", pady=(4, 10))

        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x")
        self.rip_button = ttk.Button(row, text="Rip my stats", style="Rip.TButton", command=self.start)
        self.rip_button.pack(side="left")
        self.diag_button = ttk.Button(
            row, text="Run diagnostics", style="Ghost.TButton", command=self.run_diagnostics
        )
        self.diag_button.pack(side="left", padx=(10, 0))
        self.folder_button = ttk.Button(
            row, text="Open export folder", style="Ghost.TButton", command=self.open_folder
        )
        self.folder_button.pack(side="left", padx=(10, 0))

        row2 = tk.Frame(inner, bg=CARD)
        row2.pack(fill="x", pady=(8, 0))
        self.data_button = ttk.Button(
            row2, text="Open data folder", style="Ghost.TButton", command=self.open_data_folder
        )
        self.data_button.pack(side="left")
        self.log_button = ttk.Button(
            row2, text="Open latest log", style="Ghost.TButton", command=self.open_latest_log
        )
        self.log_button.pack(side="left", padx=(10, 0))
        self.copy_button = ttk.Button(
            row2, text="Copy profile JSON", style="Ghost.TButton", command=self.copy_json, state="disabled"
        )
        self.copy_button.pack(side="left", padx=(10, 0))

        # Error panel (hidden until a run fails)
        self.error_frame = tk.Frame(
            outer, bg=ERR_BG, highlightbackground=ERR_BORDER, highlightthickness=1
        )
        error_inner = tk.Frame(self.error_frame, bg=ERR_BG, padx=16, pady=12)
        error_inner.pack(fill="x")
        self.error_title = tk.Label(
            error_inner,
            text="",
            bg=ERR_BG,
            fg=BAD,
            font=("Segoe UI Semibold", 11),
            anchor="w",
            justify="left",
            wraplength=660,
        )
        self.error_title.pack(fill="x")
        self.error_body = tk.Label(
            error_inner,
            text="",
            bg=ERR_BG,
            fg=FG,
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=660,
        )
        self.error_body.pack(fill="x", pady=(5, 8))
        error_row = tk.Frame(error_inner, bg=ERR_BG)
        error_row.pack(fill="x")
        ttk.Button(
            error_row, text="Copy error details", style="Ghost.TButton", command=self.copy_error
        ).pack(side="left")
        ttk.Button(
            error_row, text="Open diagnostics folder", style="Ghost.TButton", command=self.open_diagnostics
        ).pack(side="left", padx=(8, 0))

        # Player summary card (hidden until a rip succeeds)
        self.result_frame = tk.Frame(outer, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        self.result_label = tk.Label(
            self.result_frame,
            text="",
            bg=CARD,
            fg=FG,
            font=("Consolas", 10),
            justify="left",
            anchor="w",
            padx=16,
            pady=12,
        )
        self.result_label.pack(fill="x")

        tk.Label(
            outer,
            text="ACTIVITY",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
            anchor="w",
        ).pack(fill="x", pady=(14, 6))
        log_wrap = tk.Frame(outer, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        log_wrap.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_wrap,
            bg=CARD,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            borderwidth=0,
            font=("Consolas", 9),
            padx=12,
            pady=10,
            wrap="word",
            height=9,
        )
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")
        self.log.tag_configure("ok", foreground=GOOD)
        self.log.tag_configure("err", foreground=BAD)
        self.log.tag_configure("muted", foreground=MUTED)

        footer = tk.Frame(outer, bg=BG)
        footer.pack(fill="x", pady=(10, 0))
        tk.Label(
            footer,
            text="Not affiliated with BattleBit Remastered or Steam. Your data is only sent to api.battlebit.cloud.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill="x")

    # -- helpers -----------------------------------------------------------
    def _append(self, message: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"[{self._clock()}] {message}\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    @staticmethod
    def _clock() -> str:
        from datetime import datetime

        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _open_path(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            import webbrowser

            webbrowser.open(path.as_uri())

    def open_folder(self) -> None:
        self._open_path(self.out_dir)

    def open_data_folder(self) -> None:
        self._open_path(default_data_dir())

    def open_diagnostics(self) -> None:
        self._open_path(default_data_dir() / "diagnostics")

    def open_latest_log(self) -> None:
        log = latest_log()
        if log and log.is_file():
            if os.name == "nt":
                os.startfile(str(log))  # type: ignore[attr-defined]
            else:
                self._open_path(log.parent)
        else:
            self._open_path(default_log_dir())

    def copy_json(self) -> None:
        if not self.last_outcome:
            return
        payload = json.dumps(self.last_outcome.profile, indent=2, ensure_ascii=False)
        self.clipboard_clear()
        self.clipboard_append(payload)
        self.status_var.set("Profile JSON copied")
        self.detail_var.set("Paste it into the upload form, or keep it as a backup.")

    def copy_error(self) -> None:
        if not self.last_error_text:
            return
        self.clipboard_clear()
        self.clipboard_append(self.last_error_text)
        self.status_var.set("Error details copied")

    # -- workflow ----------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.rip_button.configure(state=state)
        self.diag_button.configure(state=state)

    def start(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.copy_button.configure(state="disabled")
        self.status_var.set("Working...")
        self.detail_var.set("Asking Steam for your session, then the official API for your profile.")
        self._append("Starting rip...")
        threading.Thread(target=self._work, daemon=True).start()

    def run_diagnostics(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.status_var.set("Running diagnostics...")
        self.detail_var.set("Checking Steam, DNS, TLS, and file paths. No profile is fetched.")
        self._append("Running diagnostics...")
        threading.Thread(target=self._diagnose_work, daemon=True).start()

    def _log_threadsafe(self, message: str) -> None:
        self.after(0, lambda: self._append(message))

    def _work(self) -> None:
        try:
            outcome = rip(out_dir=self.out_dir, log=self._log_threadsafe)
        except Exception as exc:  # surface every failure to the UI
            self.after(0, lambda: self._fail(exc))
            return
        self.after(0, lambda: self._done(outcome))

    def _diagnose_work(self) -> None:
        try:
            outcome = diagnose()
        except Exception as exc:
            self.after(0, lambda: self._fail(exc))
            return
        self.after(0, lambda: self._diagnose_done(outcome))

    def _show_error(self, exc: Exception) -> errors.RipperError:
        err = errors.classify(exc)
        self.last_error = err
        details = err.details or {}
        lines = [err.user_message()]
        if details.get("run_id"):
            lines.append(f"\nRun ID: {details['run_id']}")
        if details.get("log"):
            lines.append(f"Log: {details['log']}")
        if details.get("diagnostics"):
            lines.append(f"Diagnostics: {details['diagnostics']}")
        self.last_error_text = "\n".join(lines)
        self.error_title.configure(text=f"[{err.code}] {err.title}")
        body = f"{err.cause}\n\nFix: {err.fix}"
        if details.get("run_id"):
            body += f"\n\nRun {details['run_id']}"
        if details.get("diagnostics"):
            body += "\nThe diagnostics file has the full log and environment."
        self.error_body.configure(text=body)
        self.error_frame.pack(fill="x", pady=(12, 0), before=self.log.master)
        return err

    def _fail(self, exc: Exception) -> None:
        self._set_busy(False)
        err = self._show_error(exc)
        self.status_var.set(f"Stopped — {err.code}")
        self.detail_var.set(err.title)
        self._append(f"[{err.code}] {err.title}: {err.cause}", "err")
        if err.details.get("log"):
            self._append(f"Log: {err.details['log']}", "muted")
        if err.details.get("diagnostics"):
            self._append(f"Diagnostics: {err.details['diagnostics']}", "muted")

    def _done(self, outcome) -> None:
        self._set_busy(False)
        self.last_outcome = outcome
        self.last_error = None
        self.copy_button.configure(state="normal")
        self.error_frame.pack_forget()
        p = outcome.profile["progress"]
        d = outcome.profile["derived"]
        self.status_var.set("Profile captured")
        self.detail_var.set(
            f"{outcome.persona or 'Player'} - rank {p.get('rank', 0):,} - {len(outcome.paths)} file(s) written."
        )
        history_line = ""
        if outcome.snapshot_id:
            state = "new snapshot" if outcome.snapshot_inserted else "already stored"
            history_line = f"\nHistory: #{outcome.snapshot_id} ({state})"
        summary = (
            f"{outcome.persona or 'Player':<22} {outcome.steam_id}\n"
            f"Rank {p.get('rank', 0):>4,}  Prestige {p.get('prestige', 0):<2}  "
            f"Kills {p.get('kills', 0):>7,}  Deaths {p.get('deaths', 0):>7,}  "
            f"K/D {d.get('kd', 0):.2f}\n"
            f"Wins {p.get('wins', 0):>5,}  Losses {p.get('losses', 0):>5,}  "
            f"Score {p.get('total_score', 0):>12,}  Playtime {d.get('hours_played', 0):,.1f} h"
            f"{history_line}\n"
            f"Files: {outcome.paths[0].name if outcome.paths else '(none)'}"
        )
        self.result_label.configure(text=summary)
        self.result_frame.pack(fill="x", pady=(12, 0), before=self.log.master)
        for path in outcome.paths:
            self._append(f"Wrote {path}", "ok")
        self._append(f"Run {outcome.run_id} · log {outcome.log_path}", "muted")
        self._append("Done. Upload the .bbrstats file to the stats site.", "ok")

    def _diagnose_done(self, outcome) -> None:
        self._set_busy(False)
        self.error_frame.pack_forget()
        checks = outcome.checks
        steam = checks.get("steam", {})
        api = checks.get("api", {})
        tls = api.get("tls") or {}
        self.status_var.set("Diagnostics complete")
        self.detail_var.set(f"Steam: {'OK' if steam.get('ok') else 'FAILED'} · API: {'OK' if tls.get('ok') else 'FAILED'}")
        self._append(f"Steam bridge: {'OK' if steam.get('ok') else 'FAILED'}", "ok" if steam.get("ok") else "err")
        if steam.get("ok"):
            self._append(f"  user {steam.get('persona')} ({steam.get('steam_id')}), ticket {steam.get('ticket_bytes')} bytes", "muted")
        else:
            self._append(f"  [{steam.get('code')}] {steam.get('title')}", "err")
        self._append(f"API TCP/TLS: {'OK' if tls.get('ok') else 'FAILED'} ({tls.get('ms', '?')} ms)", "ok" if tls.get("ok") else "err")
        if tls.get("first_line"):
            self._append(f"  {tls['first_line']} (bare GET probe)", "muted")
        elif tls.get("error"):
            self._append(f"  {tls['error']}", "err")
        self._append(f"Diagnostics: {outcome.diagnostics_path}", "ok")


def main() -> int:
    app = RipperApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
