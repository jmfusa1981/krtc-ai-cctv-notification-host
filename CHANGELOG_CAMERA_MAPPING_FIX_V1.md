# KRTC V5 Camera Mapping Fix V1

## Purpose

Fix Dashboard events that displayed `未指定攝影機` even though KMetro API v1.3 supplied a canonical `camera_id`, for example `CAM-003`.

## Changes

- Match `InferenceCameraMapping.source_camera_id` case-insensitively.
- Fall back safely to `Camera.camera_code` for canonical IDs such as `CAM-003`.
- Repair previously imported duplicate events when mapping becomes available.
- Add `repair_event_camera_links` command for historical events.
- Add `configure_v5_camera_mappings` command for CAM-002, CAM-003, and CAM-004.
- Add `R16_左營=KRTC-ST-001` to the default external station mapping.
- Add regression tests for canonical camera ID fallback and duplicate repair.
