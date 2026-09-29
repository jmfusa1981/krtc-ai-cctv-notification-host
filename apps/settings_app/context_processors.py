from .models import StationLocalSettings
from apps.accounts.permissions import can_manage_frontend_settings, can_view_advanced_settings, can_view_security_audit


def station_identity(request):
    """Expose the configured station identity to every rendered page."""
    try:
        local_settings = StationLocalSettings.load()
        station_name = (local_settings.station_name or "").strip()
        station_code = (local_settings.station_code or "").strip()
        notification_host_name = (local_settings.notification_host_name or "").strip()
        system_version = (local_settings.system_version or "").strip()
    except Exception:
        station_name = ""
        station_code = ""
        notification_host_name = ""
        system_version = ""

    return {
        "station_name": station_name or "站區名",
        "station_code": station_code,
        "notification_host_name": notification_host_name,
        "system_version": system_version or "V6",
    }


def current_user_identity(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"current_user_role_label": "", "current_user_display": ""}

    if user.is_superuser:
        role_label = "開發者"
    elif user.groups.filter(name="Administrator").exists():
        role_label = "系統管理員"
    elif user.groups.filter(name="Maintainer").exists():
        role_label = "維護人員"
    elif user.groups.filter(name="Operator").exists():
        role_label = "操作人員"
    else:
        role_label = "使用者"

    can_manage_accounts = bool(
        user.is_superuser or user.groups.filter(name="Administrator").exists()
    )
    can_access_settings = can_manage_frontend_settings(user)

    return {
        "current_user_role_label": role_label,
        "current_user_display": f"{role_label} {user.get_username()}",
        "can_manage_accounts_global": can_manage_accounts,
        "can_access_settings_global": can_access_settings,
        "can_view_system_log_global": can_view_advanced_settings(user),
        "can_view_security_audit_global": can_view_security_audit(user),
    }
