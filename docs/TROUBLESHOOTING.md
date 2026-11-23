# Troubleshooting

## First: get the run ID and the diagnostics file

Every run writes:

- `%LOCALAPPDATA%\BBR Stats Ripper\logs\run-<id>.log`
- `%LOCALAPPDATA%\BBR Stats Ripper\logs\runs\<id>.json`
- on failure, `%LOCALAPPDATA%\BBR Stats Ripper\diagnostics\diagnostics-<id>.txt`

In the app, press **Run diagnostics** and **Copy error details**. The diagnostic
file contains the environment, Steam check, DNS/TLS check, steps, and the log
tail. It never contains the Steam auth ticket. It does contain the Steam ID and
public stats, so treat it as public.

CLI:

```powershell
bbr-ripper-cli --diagnose --verbose
bbr-ripper-cli --out "C:\Users\me\Documents\BattleBit Stats Ripper" --verbose
```

## Error codes

| Code | Meaning | Fix |
|---|---|---|
| `BBR-S001` | Steam is not running or not signed in | Open Steam, sign in, leave it running. The game can stay closed. |
| `BBR-S002` | General Steam bridge failure | Restart Steam, retry. If the game just updated, restart Steam. |
| `BBR-S003` | BattleBit not found in a Steam library | Install the game through Steam or add its library in Steam > Settings > Storage. |
| `BBR-S004` | `steam_api64.dll` failed to load | Verify the game files in Steam; restore the DLL from antivirus quarantine. |
| `BBR-S005` | Steam refused an auth ticket | Confirm the account owns BattleBit; wait a few seconds; restart Steam. |
| `BBR-S006` | Steam returned no user/Steam ID | Sign out of Steam, sign back in, retry. |
| `BBR-A001` | Cannot reach `api.battlebit.cloud` | Check internet, VPN, firewall, and proxy. Allow the host on 443. |
| `BBR-A002` | Token request rejected (403) | Steam is not fully signed in or does not own the game. Restart Steam and retry. |
| `BBR-A003` | Stats request rejected (403) | The session expired. Retry; if it persists, restart Steam. |
| `BBR-A004` | API HTTP error | Retry. 429/5xx are retried automatically; wait a minute if they persist. |
| `BBR-A005` | Unexpected token response | The game/API changed. Keep the diagnostics and report the run ID. |
| `BBR-A006` | Empty/truncated stats response | Retry; if it persists, report the run ID and response size. |
| `BBR-U001` | Upload URL missing/invalid | Set `BBR_UPLOAD_URL` or `--upload-url`; must be http(s). |
| `BBR-U002` | Token missing or rejected | Create a new token under Account → Collector tokens. |
| `BBR-U003` | Token bound to another Steam ID | The capture's Steam ID must match the token's bound ID. |
| `BBR-U004` | Site rate limit | Wait for the next scheduled run; limit is 10 uploads/hour/account. |
| `BBR-U005` | Site unreachable or HTTP error | Check the URL, Tailscale, and the site's `/healthz`. |
| `BBR-D001` | Profile layout changed | The raw bytes are preserved. Update the decoder; report the run ID. |
| `BBR-X001` | Could not write the output files | Pick a writable folder, close programs locking the file, check disk space. |
| `BBR-X002` | Unexpected error | Send the diagnostics file with the run ID. |

## Common situations

### "Steam is not running" but it is

Steam may still be starting, or it updated and needs a restart. Run diagnostics;
the report says whether `steam.exe` was visible. Wait for the Steam window to
finish loading, then retry. The BattleBit game itself does not need to be open.

### The game is installed on another drive

Steam > Settings > Storage > add the library. The ripper reads
`libraryfolders.vdf`, so no manual path is needed. If the library was just added,
restart Steam so the file is rewritten.

### Antivirus or SmartScreen

The executable is unsigned. SmartScreen may warn on first run; choose **More
info > Run anyway** only if you trust the build. If antivirus quarantines
`steam_api64.dll`, restore it and allow the BattleBit folder. The ripper loads
that DLL; it does not ship or copy it.

### VPN, proxy, or Cloudflare

`api.battlebit.cloud` is Cloudflare-fronted. A VPN or corporate proxy can block
the POST endpoints. The diagnostics probe does a bare `GET /`; HTTP 403/520 is
normal for that probe and still proves DNS/TLS reachability. The real requests
are POSTs and are logged separately.

### The API returns 403

The ticket is short-lived and tied to the signed-in account. Open Steam, confirm
the account owns BattleBit, and retry. Repeated failures usually clear after a
Steam restart.

### The response size changed

2,590 bytes = no weekly challenge. 2,678 bytes = 88-byte weekly challenge payload.
Both are valid. Other sizes are logged with a SHA-256 and preserved raw.

### The app has no output after a scheduled run

Scheduled runs are silent by design. Check
`%LOCALAPPDATA%\BBR Stats Ripper\logs` and the task history:

```powershell
Get-ScheduledTaskInfo -TaskName "BattleBit Stat Ripper"
```

### Reset local logs/history

Logs and history are separate from the exported files:

```powershell
Remove-Item "$env:LOCALAPPDATA\BBR Stats Ripper\logs" -Recurse -Force
Remove-Item "$env:LOCALAPPDATA\BBR Stats Ripper\history.sqlite3" -Force
```

Deleting history does not delete the `.bbrstats` files in Documents.

### Run automatically

See `scripts/install_startup_task.ps1` for a per-user scheduled task, or
`scripts/run_collector.ps1` for the upload-aware collector loop that starts from
the Startup folder. The collector reads its token from
`%LOCALAPPDATA%\BBR Stats Ripper\collector.json` and appends to
`collector.log`. Upload errors are `BBR-U00x` (see above); the next cycle retries.

```powershell
.\scripts\install_startup_task.ps1 -Hours 6
.\scripts\install_startup_task.ps1 -Hours 3 -RunNow
.\scripts\uninstall_startup_task.ps1
```

The task runs at logon and every N hours, waits up to 5 minutes for Steam, and
appends to local history. It runs as the current user (no admin).

## What to attach to a bug report

1. The run ID.
2. `diagnostics-<id>.txt`.
3. The response size and SHA-256 from the log.
4. Whether the in-game Profile screen matches the decoded numbers.

Do not attach the auth ticket or token; the ripper never writes them. The
diagnostics file is safe to share aside from the Steam ID and public stats.
