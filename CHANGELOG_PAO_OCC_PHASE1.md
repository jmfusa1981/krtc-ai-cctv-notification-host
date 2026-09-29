# PAO-OCC Phase 1 update

- Restored dedicated WebSocket receiver, ACK, exponential reconnect and REST `after_id` catch-up.
- Added separate Inference WebSocket and OCC API tokens.
- Added `/api/v1/health/`, `status/`, `version/`, `inference-hosts/`, `devices/`, `events/`, `configuration/` and `configuration/apply/`.
- Added validated, versioned AI model selection per inference host.
- Added immutable configuration acceptance/rejection audit records with secret-field redaction.
- Added production LAN host, CSRF and CORS environment settings.
- Added automated API and WebSocket acceptance tests.
