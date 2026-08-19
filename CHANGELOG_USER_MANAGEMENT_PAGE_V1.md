# KRTC V5 User Management Page V1

- Removed account management from the general system settings tabs.
- Added `/dashboard/settings/accounts/` as a dedicated user management page.
- The page is visible only to Administrator and Superuser accounts.
- Added create, edit, remove (soft-disable), and restore actions.
- Superusers are excluded from the frontend list and cannot be modified there.
- The current logged-in account cannot remove itself.
- Added a `使用者管理` navigation button for authorized accounts.
