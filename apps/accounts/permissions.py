from django.http import HttpResponse

ROLE_OPERATOR = "Operator"
ROLE_ADMINISTRATOR = "Administrator"
ROLE_MAINTAINER = "Maintainer"

EVENT_PROCESSING_ROLES = {
    ROLE_OPERATOR,
    ROLE_ADMINISTRATOR,
    ROLE_MAINTAINER,
}

FRONTEND_SETTINGS_ROLES = {
    ROLE_ADMINISTRATOR,
    ROLE_MAINTAINER,
}

ADVANCED_SETTINGS_VIEW_ROLES = {
    ROLE_ADMINISTRATOR,
    ROLE_MAINTAINER,
}

AI_SETTINGS_EDIT_ROLES = {
    ROLE_ADMINISTRATOR,
}


def user_has_any_role(user, role_names):
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return user.groups.filter(name__in=role_names).exists()


def can_process_events(user):
    return user_has_any_role(user, EVENT_PROCESSING_ROLES)


def can_manage_frontend_settings(user):
    return user_has_any_role(user, FRONTEND_SETTINGS_ROLES)


def can_view_advanced_settings(user):
    return user_has_any_role(user, ADVANCED_SETTINGS_VIEW_ROLES)


def can_manage_ai_settings(user):
    return user_has_any_role(user, AI_SETTINGS_EDIT_ROLES)


def can_access_django_admin(user):
    """Django admin is reserved for technical superusers only."""
    return bool(user and user.is_authenticated and user.is_superuser)


# KRTC V6.4.6.1 - hide protected backend routes from unauthorized users
def hidden_forbidden_response():
    return HttpResponse(
        "404 forbidden",
        status=404,
        content_type="text/plain; charset=utf-8",
    )

SECURITY_AUDIT_VIEW_ROLES = {
    ROLE_ADMINISTRATOR,
}


def can_view_security_audit(user):
    """Security/audit records are limited to Administrator and Superuser."""
    return user_has_any_role(user, SECURITY_AUDIT_VIEW_ROLES)
