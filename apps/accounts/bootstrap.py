from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import OperationalError, ProgrammingError, transaction


@dataclass(frozen=True)
class DefaultAdminResult:
    username: str
    created: bool
    password_changed: bool
    role_added: bool


def ensure_default_admin(*, reset_password: bool = False) -> DefaultAdminResult | None:
    """Create or repair the built-in frontend administrator account.

    The account is a normal Django user in the Administrator group. It is not
    staff and is not a superuser, so it cannot enter Django Admin.
    """
    if not getattr(settings, "KRTC_DEFAULT_ADMIN_ENABLED", True):
        return None

    username = str(getattr(settings, "KRTC_DEFAULT_ADMIN_USERNAME", "admin")).strip() or "admin"
    password = str(getattr(settings, "KRTC_DEFAULT_ADMIN_PASSWORD", "KrtcAdmin@2026"))
    role_name = "Administrator"
    User = get_user_model()

    try:
        with transaction.atomic():
            role, _ = Group.objects.get_or_create(name=role_name)
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": "系統管理員",
                    "is_active": True,
                    "is_staff": False,
                    "is_superuser": False,
                },
            )

            changed_fields: list[str] = []
            if not user.is_active:
                user.is_active = True
                changed_fields.append("is_active")
            if user.is_staff:
                user.is_staff = False
                changed_fields.append("is_staff")
            if user.is_superuser:
                user.is_superuser = False
                changed_fields.append("is_superuser")
            if not (user.first_name or "").strip():
                user.first_name = "系統管理員"
                changed_fields.append("first_name")

            password_changed = created or reset_password or not user.has_usable_password()
            if password_changed:
                user.set_password(password)
                changed_fields.append("password")

            if changed_fields:
                user.save(update_fields=list(dict.fromkeys(changed_fields)))

            role_added = not user.groups.filter(pk=role.pk).exists()
            if role_added:
                user.groups.add(role)

            return DefaultAdminResult(
                username=username,
                created=created,
                password_changed=password_changed,
                role_added=role_added,
            )
    except (OperationalError, ProgrammingError):
        # Database tables may not exist yet during early startup. post_migrate
        # will call this function again after migrations are complete.
        return None
