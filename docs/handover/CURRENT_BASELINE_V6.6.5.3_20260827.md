# Current Baseline - KRTC Notification Host V6.6.5.3

Date: 2026-08-27

## Repository
- Repository: `jmfusa1981/krtc-ai-cctv-notification-host`
- Development branch: `feature/v6-ui-security`
- Handover tag to create: `v6.6.5.3-handover-20260827`
- Handover commit SHA: use the commit pointed to by the tag after synchronization.

## Development environment
- Windows
- Python 3.12+
- Django 5.2.15
- SQLite
- VS Code / PowerShell
- Development port: 8010
- Production/service port: 8000

## Project role
PAO Notification Host receives AI inference events, displays station alerts and snapshots, manages cameras/inference hosts/IP broadcast speakers, performs station broadcasts, stores event/system/audit records, and integrates with OCC through station-side APIs.

## V6.6.5.3 current convergence
- V6.6.2: system diagnostics, speaker status synchronization, inference host UI, persistent runtime foundation, configuration backup/restore foundation.
- V6.6.3: Dashboard latest-event ordering by event occurrence time; local device UI simplification; inference connection table readability.
- V6.6.3.1: device summary abnormal count wording/emphasis.
- V6.6.4: Traditional Chinese UI localization and device list two-column layout.
- V6.6.5: management-page consistency; camera/speaker creation flow consistency; broadcast audio localization; button styling.
- V6.6.5.1 to V6.6.5.3: Dashboard blue information-bar title baseline convergence.

## Major implemented functions
- Dashboard / recent AI events / event details
- Event Records / Event Snapshot
- RTSP camera stream integration and authenticated RTSP URL construction
- Monitor Wall 1/4/9/16
- Inference Host health / event polling / WebSocket integration
- Zone Count / area flow
- IP broadcast speaker management
- Manual / automatic / scheduled broadcast framework
- Speaker health framework
- Local station system diagnostics
- Station configuration export / inspect / restore foundation
- RBAC and Superuser USB security
- System Log / Device Fault framework
- Security Audit foundation
- OCC read-only/synchronization API foundation

## Pending / field-validation items
- AIO physical-host validation
- Station SIT and networking validation
- Physical camera / speaker / inference-host end-to-end validation
- NVR delayed event recording retrieval and 2-minute event video convergence
- OCC integration field validation
- TEAM+ / KRTC cloud integration items that remain externally coordinated
- Production deployment/acceptance convergence

## Development startup
```powershell
cd C:\Users\<USER>\krtc_notification_host_v6
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
python manage.py check
python manage.py migrate
python manage.py runserver 0.0.0.0:8010
```

Dashboard: `http://127.0.0.1:8010/dashboard/`

## Repository security exclusions
Do not commit:
`.env`, `db.sqlite3`, `*.key`, `media/`, `staticfiles/`, `runtime/`, `logs/`, `venv/`, `venv_old_*/`, `_update_backups/`, `backups/`.
