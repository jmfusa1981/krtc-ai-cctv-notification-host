# KRTC V5 Frontend Settings Management V2

## Scope

This update extends `/dashboard/settings/` so routine operation no longer requires Django Admin.

## Added

- Broadcast schedule create/edit/enable/disable management.
- OCC synchronization state and recent synchronization logs.
- Configuration delivery audit log viewer.
- Frontend account and role management for Operator, Maintainer, and Administrator.
- Account activation/deactivation without deleting history.
- Administrator-only account management tab.
- Superuser exclusion from frontend account creation/editing.

## Security

- Django Admin access helper now permits Superuser only.
- Maintainer can manage operational settings but cannot manage accounts.
- Administrator can manage operational settings and frontend accounts.
- Operator remains read-only.

## Notes

No database migration is required. Existing models are reused.
