from __future__ import annotations

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


@dataclass(frozen=True)
class DefaultSuperuserResult:
    username: str
    created: bool
    password_changed: bool
    permissions_repaired: bool


def ensure_default_admin(
    *,
    reset_password: bool = False,
) -> DefaultAdminResult | None:
    """Create or repair the built-in frontend Administrator account.

    The account is a normal Django user in the Administrator group.

    Security policy:
    - active user
    - not Django staff
    - not Django superuser
    - belongs to Administrator group
    - cannot enter Django Admin
    """

    if not getattr(settings, "KRTC_DEFAULT_ADMIN_ENABLED", True):
        return None

    username = str(
        getattr(settings, "KRTC_DEFAULT_ADMIN_USERNAME", "admin")
        or "admin"
    ).strip()

    password = str(
        getattr(settings, "KRTC_DEFAULT_ADMIN_PASSWORD", "")
        or ""
    )

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

            password_changed = False

            if created:
                if password:
                    user.set_password(password)
                else:
                    user.set_unusable_password()

                changed_fields.append("password")
                password_changed = bool(password)

            elif reset_password:
                if not password:
                    raise ValueError(
                        "KRTC_DEFAULT_ADMIN_PASSWORD is required "
                        "when reset_password=True."
                    )

                user.set_password(password)
                changed_fields.append("password")
                password_changed = True

            elif not user.has_usable_password() and password:
                user.set_password(password)
                changed_fields.append("password")
                password_changed = True

            if changed_fields:
                user.save(
                    update_fields=list(
                        dict.fromkeys(changed_fields)
                    )
                )

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
        # Database tables may not exist yet during early startup.
        # post_migrate can call this function again after migrations.
        return None


def ensure_default_superuser(
    *,
    reset_password: bool = False,
) -> DefaultSuperuserResult | None:
    """Create or repair the built-in KRTC engineering Superuser.

    Security policy:
    - active user
    - Django staff
    - Django superuser
    - intended for engineering / Django Admin access
    - production access may additionally require the trusted USB gate

    Existing users are repaired instead of silently accepted with
    incorrect permissions.
    """

    if not getattr(
        settings,
        "KRTC_DEFAULT_SUPERUSER_ENABLED",
        True,
    ):
        return None

    username = str(
        getattr(
            settings,
            "KRTC_DEFAULT_SUPERUSER_USERNAME",
            "skynet",
        )
        or "skynet"
    ).strip()

    password = str(
        getattr(
            settings,
            "KRTC_DEFAULT_SUPERUSER_PASSWORD",
            "",
        )
        or ""
    )

    User = get_user_model()

    try:
        with transaction.atomic():
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": "工程管理員",
                    "is_active": True,
                    "is_staff": True,
                    "is_superuser": True,
                },
            )

            changed_fields: list[str] = []
            permissions_repaired = False

            if not user.is_active:
                user.is_active = True
                changed_fields.append("is_active")
                permissions_repaired = True

            if not user.is_staff:
                user.is_staff = True
                changed_fields.append("is_staff")
                permissions_repaired = True

            if not user.is_superuser:
                user.is_superuser = True
                changed_fields.append("is_superuser")
                permissions_repaired = True

            if not (user.first_name or "").strip():
                user.first_name = "工程管理員"
                changed_fields.append("first_name")

            password_changed = False

            if created:
                if password:
                    user.set_password(password)
                else:
                    user.set_unusable_password()

                changed_fields.append("password")
                password_changed = bool(password)

            elif reset_password:
                if not password:
                    raise ValueError(
                        "KRTC_DEFAULT_SUPERUSER_PASSWORD is required "
                        "when reset_password=True."
                    )

                user.set_password(password)
                changed_fields.append("password")
                password_changed = True

            elif not user.has_usable_password() and password:
                user.set_password(password)
                changed_fields.append("password")
                password_changed = True

            if changed_fields:
                user.save(
                    update_fields=list(
                        dict.fromkeys(changed_fields)
                    )
                )

            return DefaultSuperuserResult(
                username=username,
                created=created,
                password_changed=password_changed,
                permissions_repaired=permissions_repaired,
            )

    except (OperationalError, ProgrammingError):
        return None