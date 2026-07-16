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


def can_access_django_admin(user):
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return user.is_staff and user.groups.filter(name=ROLE_MAINTAINER).exists()
