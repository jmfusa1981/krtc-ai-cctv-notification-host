# KRTC Notification Host V6.6.3 - Dashboard Sync and Device UI Tuning

Date: 2026-08-27
Target: Development host (`C:\Users\user\krtc_notification_host_v6`)
Baseline: V6.6.2 Full Adjustment

## 1. Dashboard recent AI event consistency

### Root cause
The Dashboard `get_recent_events()` query sorted by `created_at`, while Event Records and Event Snapshots use the event occurrence time (`detected_at`). When older inference events are received/imported later in a batch, their newer `created_at` values can displace genuinely newer detections such as CAM-004 from the Dashboard's latest 10 rows.

### Fix
Dashboard recent events now use:

`ORDER BY detected_at DESC, id DESC LIMIT 10`

This aligns the Dashboard event ordering with Event Records. Event Snapshots remain a snapshot-bearing/local-snapshot subset, but their event chronology also uses `detected_at`.

No camera/event-type de-duplication is applied to the recent 10-event list.

## 2. Inference host connection table readability

Rebalanced the host diagnostic table widths so the `最後檢查` / error-message column has materially more space. Error text retains wrapping and is no longer compressed by oversized network-location/action columns.

## 3. Local device page simplification

### Summary cards
Removed `已建立映射` from the local-device summary.

Only these two cards remain:
- `線上攝影機`
- `線上廣播喇叭`

### Device layout
Changed the device-management body to a two-panel layout on wide screens:
- Left: IP 攝影機
- Right: IP 廣播喇叭

Both panels retain their full status and operation controls. Each panel has its own scrollable table area. Below 1450 px the layout automatically falls back to a single-column stack to prevent excessive compression.

## Validation
The patch installer runs:
- `python manage.py check`
- `python manage.py makemigrations --check --dry-run`
- V6.6.3 recent-event regression test
- V6.6.3 settings layout regression test
- V6.6.2 dashboard/settings regression tests
- persistent local-alarm regression tests

No model or migration changes are introduced by V6.6.3.
