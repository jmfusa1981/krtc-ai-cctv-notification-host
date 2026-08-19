# KRTC V5 Header Role and Settings Simplification V1

- All dashboard pages now display the authenticated role and username in the shared header.
- Example: `系統管理員 admin`.
- Administrator settings UI is simplified to daily operational functions.
- Advanced diagnostics, AI mapping internals, and execution logs remain visible to superusers.
- Django Admin remains superuser-only.
- Existing non-superuser `admin` account is assigned to the Administrator group by the installer.
