# KRTC Notification Host V6 - Developer Regression Checklist

## Basic
- [ ] `python manage.py check` passes.
- [ ] `python manage.py makemigrations --check --dry-run` reports no unexpected model changes.
- [ ] Login page loads.
- [ ] Dashboard loads without 500/JS errors.

## Dashboard
- [ ] Latest AI events are ordered by `detected_at` and show the latest 10 events.
- [ ] Camera count/status is correct.
- [ ] Broadcast speaker summary uses online/registered logic correctly (e.g. 3/4).
- [ ] Inference host abnormal status keeps blue background; title stays white; abnormal value/details are red.
- [ ] Dashboard blue information-bar titles share the same visual top baseline.
- [ ] Zone Count / area flow updates.

## Camera
- [ ] Camera list and station-device list display correctly.
- [ ] Camera network test works.
- [ ] Authenticated RTSP URL construction works with special characters.
- [ ] Monitor Wall stream works for configured camera.
- [ ] Camera API requires authenticated access.

## Inference Host
- [ ] `/health` test updates host status.
- [ ] Connection page displays IP address as network location.
- [ ] Error message column wraps/readable.
- [ ] Event polling imports new events.
- [ ] CAM-004 and other cameras appear in recent Dashboard events when chronologically eligible.

## Events / Snapshot
- [ ] Event Records search/filter works.
- [ ] Event Snapshot page loads local snapshots.
- [ ] Snapshot details correspond to event records.
- [ ] CSV/Excel export works where enabled.

## Broadcast / Speaker
- [ ] Speaker list shows current network state.
- [ ] Speaker network test persists current state.
- [ ] Manual broadcast flow works in the intended test environment.
- [ ] Broadcast rule page supports multi-speaker selection.
- [ ] Scheduled broadcast validation messages are Traditional Chinese.
- [ ] Recent broadcast status labels are localized.

## Settings / Backup
- [ ] Station system check covers inference hosts, cameras, speakers, audio files, AI model/mapping/rule integrity.
- [ ] Configuration backup downloads.
- [ ] Backup inspection/restore preview validates format/schema/hash.
- [ ] Sensitive credentials are not exported.

## Security / RBAC
- [ ] Operator/Maintainer/Administrator/Superuser permissions match design.
- [ ] Django Admin is Superuser-only.
- [ ] Superuser USB security functions as configured.
- [ ] Protected operational media is not anonymously accessible.
- [ ] Audit events do not store secrets.

## Git hygiene
- [ ] `.env` is ignored.
- [ ] `db.sqlite3` is ignored.
- [ ] `media/`, `logs/`, `runtime/`, `backups/`, `_update_backups/`, `venv/` are not staged.
- [ ] Commit message states scope and validation performed.
