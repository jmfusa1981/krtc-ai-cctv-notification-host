# PAO V4.10 WebSocket and OCC API integration

## Processes

Run Django and the WebSocket receiver as separate processes:

```powershell
python manage.py runserver 0.0.0.0:8000
python manage.py listen_inference_events --host-code INF-TEST-001
```

## OCC station API

- `GET /api/v1/health/` is intentionally public for connectivity monitoring.
- All other `/api/v1/` endpoints require `Authorization: Bearer <KRTC_OCC_API_TOKEN>`.
- `POST /api/v1/configuration/apply/` validates station, PAO, inference host, registered active model, version and operator.
- Tokens and secrets are removed before configuration payloads are stored in audit records.

## Configuration request

```json
{
  "station_code": "TEST-STATION",
  "notification_host_code": "PAO-TEST-001",
  "inference_host_code": "INF-TEST-001",
  "model_code": "fall-detection-v2",
  "config_version": "2026.08.01.001",
  "operator_code": "Skynet"
}
```

## Acceptance boundary

This release completes the PAO WebSocket receiver and OCC-readable station API plus secure model-selection persistence. PAO-initiated heartbeat, device/event push, daily 02:00 synchronization, and OCC Offline/Recovery evaluation belong to the next integration increment.
