# KRTC V5 Default Frontend Administrator Bootstrap V1

- Adds an internal bootstrap for the normal frontend administrator account `admin`.
- The account is active and belongs to the `Administrator` group.
- The account is explicitly not staff and not superuser; Django Admin remains superuser-only.
- New databases create the account automatically after migrations.
- Normal startup never overwrites a usable password already changed by the user.
- The update installer resets the existing `admin` password once to the configured initial password.

Default development credentials:

- Username: `admin`
- Password: `KrtcAdmin@2026`

Production deployments should set `KRTC_DEFAULT_ADMIN_PASSWORD` before installation and change the password after first login.
