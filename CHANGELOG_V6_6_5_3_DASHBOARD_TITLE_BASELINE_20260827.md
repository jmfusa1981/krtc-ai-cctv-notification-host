# KRTC Notification Host V6.6.5.3 - Dashboard Title Baseline Alignment

Date: 2026-08-27

## Scope
- Dashboard blue information bar only.
- Aligns the small heading labels to a common top baseline.

## Changes
- Normalizes `latest-event-kicker` from legacy flex layout to block/grid-item behavior.
- Changes the inference-host metric from vertical centering to top alignment.
- Moves only the event-warning title upward while preserving the warning lamp and Resolve All button geometry.
- No model, API, event, device, broadcast, or database behavior changes.

## Expected visual result
The following labels share the same visual top baseline:
- Latest Event
- Station Cameras
- Station Broadcast Speakers
- Station Inference Host Status
- Area Flow
- Event Warning

No database migration is introduced.
