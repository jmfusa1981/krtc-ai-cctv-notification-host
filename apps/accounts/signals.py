from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_migrate

_registered = False


def _ensure_default_admin_after_migrate(**kwargs):
    from .bootstrap import ensure_default_admin
    ensure_default_admin(reset_password=False)


def _record_login(sender, request, user, **kwargs):
    try:
        from apps.station_api.security_audit import record_security_audit
        record_security_audit(action="LOGIN_SUCCESS", result="success", request=request, user=user, auth_method="PASSWORD")
    except Exception:
        pass


def _record_logout(sender, request, user, **kwargs):
    try:
        from apps.station_api.security_audit import record_security_audit
        record_security_audit(action="LOGOUT", result="success", request=request, user=user, auth_method="SESSION")
    except Exception:
        pass


def _record_login_failed(sender, credentials, request, **kwargs):
    try:
        from apps.station_api.security_audit import record_security_audit
        username = str((credentials or {}).get("username") or "")
        record_security_audit(action="LOGIN_FAILED", result="failed", request=request, username=username, auth_method="PASSWORD", detail="Authentication failed")
    except Exception:
        pass


def register_default_admin_bootstrap():
    global _registered
    if _registered:
        return
    post_migrate.connect(_ensure_default_admin_after_migrate, dispatch_uid="krtc.accounts.ensure_default_admin", weak=False)
    user_logged_in.connect(_record_login, dispatch_uid="krtc.accounts.audit_login", weak=False)
    user_logged_out.connect(_record_logout, dispatch_uid="krtc.accounts.audit_logout", weak=False)
    user_login_failed.connect(_record_login_failed, dispatch_uid="krtc.accounts.audit_login_failed", weak=False)
    _registered = True
