# KRTC AI CCTV Notification Host V6.6.2

Build date: 2026-08-27
Baseline: 2026-08-26 V6 development snapshot
Scope: system diagnostics, device/inference UI, dashboard status synchronization, persistent runtime path hardening, and AIO test packaging.

## 1. Station system check scope corrected and completed

The system-wide check now covers the following non-destructive checks:

- Active inference hosts: HTTP `/health` diagnostic.
- Active cameras: TCP reachability of the configured camera network endpoint (normally RTSP host/port).
- Active IP broadcast speakers: TCP reachability of the registered speaker network endpoint.
- Active audio files: configured file exists and is non-empty.
- Active AI models: configuration integrity (confidence threshold is valid).
- Active camera mappings: mapping integrity (required camera/model relationship is complete).
- Active broadcast rules: rule integrity (event type, audio and target speaker relationship are complete).

This station check intentionally does NOT perform real speaker playback, NVR recording/export, AI inference accuracy validation, image-quality acceptance, or end-to-end OCC/TEAM+ acceptance. Those remain SIT/acceptance procedures.

## 2. Local devices - camera UI

- `測試端點` renamed to `網路端點`.
- Removed the per-row `映射` column from the camera device table.
- `診斷` renamed to `執行操作`.
- Camera action wording updated to `測試網路`.
- Camera APIs are now login-protected.

## 3. Local devices - broadcast speaker UI

- `IP 擴音器` renamed to `IP 廣播喇叭` in the device/settings UI.
- `診斷` renamed to `執行操作`.
- Speaker network tests now return/persist the current status and refresh the row status immediately.

## 4. Dashboard speaker status synchronization

Dashboard speaker summary now uses the registered enabled speaker inventory and current persisted speaker status:

- 4 registered / 4 online -> `4` (normal).
- 4 registered / 3 online -> `3/4` (abnormal, red emphasis).
- 4 registered / 0 online -> `0/4` (abnormal, red emphasis).

The dashboard live-state API now returns speaker summary data so the card updates without reloading the page.

## 5. Backup/Restore button typography

`檢查備份檔` and `下載設定備份` now share the same button font-size and line-height.

## 6. Inference host connection page

- Tab `主機連線` renamed to `連線主機`.
- Table column `Health URL` renamed to `網路位置`.
- The network location displays `InferenceHost.ip_address`; if missing, it falls back to the hostname parsed from Base URL.

## 7. Dashboard inference abnormal-host display

When inference health is abnormal:

- Dashboard status remains `異常`.
- Up to two abnormal inference host names are visible as two separate information rows.
- If more than two hosts are abnormal, the rows rotate vertically in a two-line viewport.
- Health state continues to be based on fresh `/health` results rather than generic WebSocket state.

## 8. Persistent runtime path hardening (AIO/production foundation)

Environment precedence is now explicit:

1. Windows/process environment variables.
2. `<KRTC_CONFIG_DIR>\\.env` persistent station configuration.
3. Project `.env` development/backward-compatible bootstrap.

When `KRTC_PERSISTENT_ROOT` is explicitly supplied, stale `KRTC_DATA_DIR`, `KRTC_MEDIA_DIR`, or `KRTC_LOG_DIR` values from the source checkout `.env` no longer override the persistent root. Production settings no longer pre-load the project `.env` before base settings.

Expected production layout:

```text
C:\KRTC\NotificationHost\
├─ config\.env
├─ data\db.sqlite3
├─ media\
├─ logs\
└─ backups\
```

## 9. AIO test packaging

Added V6 AIO package builder and helper scripts. The AIO source package excludes environment-specific and sensitive runtime state, including:

- `.env`
- `.git`
- `db.sqlite3` / SQLite databases
- `venv` / `venv_old_*`
- `media`, `logs`, `backups`, `runtime`, `staticfiles`
- `_update_backups`
- Python cache / log files / key files

The AIO package contains `.env.example`, version/build metadata, a SHA256 manifest, and setup/verify/start scripts.

## Validation

Validated on the supplied 2026-08-26 source snapshot:

- Python compile check: PASS.
- JavaScript syntax check: PASS.
- `python manage.py check`: PASS.
- `python manage.py makemigrations --check --dry-run`: PASS (no changes).
- Targeted regression tests: 19/19 PASS.
- V6.6 configuration-backup foundation self-test: PASS.
- Explicit `KRTC_PERSISTENT_ROOT` production path isolation check: PASS.

No model or migration change is introduced by V6.6.2.
