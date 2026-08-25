# KRTC V6.5 Audit & OCC Log API Foundation

## Human RBAC
- Operator: no System Log access.
- Maintainer: device/service log only.
- Administrator: device/service + security audit.
- Superuser: all logs.

## Security audit producers
- LOGIN_SUCCESS / LOGIN_FAILED / LOGOUT
- USB_VERIFY_SUCCESS / USB_VERIFY_FAILED
- USB_KEY_REGISTERED / USB_KEY_REGISTER_FAILED / USB_KEY_DISABLED
- USER_CREATED / USER_UPDATED / USER_ENABLED / USER_DISABLED
- STATION_SETTINGS_UPDATED

Passwords, USB tokens, authorization headers and session secrets are not persisted.

## OCC read-only API
`GET /api/v1/audit-log-changes/?since_id=0&limit=200`

Authentication: existing `Authorization: Bearer <KRTC_OCC_API_TOKEN>`.
Cursor: `SecurityAuditLog.id`.
