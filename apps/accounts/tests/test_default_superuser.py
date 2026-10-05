from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.accounts.bootstrap import ensure_default_superuser


@override_settings(
    KRTC_DEFAULT_SUPERUSER_ENABLED=True,
    KRTC_DEFAULT_SUPERUSER_USERNAME="skynet",
    KRTC_DEFAULT_SUPERUSER_PASSWORD="TestSkynet@2026",
)
class DefaultSuperuserBootstrapTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

    def test_create_superuser(self):
        result = ensure_default_superuser()

        self.assertIsNotNone(result)
        self.assertTrue(result.created)

        user = self.User.objects.get(username="skynet")

        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("TestSkynet@2026"))

    def test_existing_user_permissions_are_repaired(self):
        user = self.User.objects.create_user(
            username="skynet",
            password="ExistingPassword@2026",
            is_active=False,
            is_staff=False,
            is_superuser=False,
        )

        result = ensure_default_superuser()

        user.refresh_from_db()

        self.assertFalse(result.created)
        self.assertTrue(result.permissions_repaired)

        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

        # Bootstrap must not overwrite an existing usable password.
        self.assertTrue(
            user.check_password("ExistingPassword@2026")
        )

    def test_existing_password_is_not_overwritten(self):
        self.User.objects.create_superuser(
            username="skynet",
            password="CustomPassword@2026",
        )

        result = ensure_default_superuser()

        user = self.User.objects.get(username="skynet")

        self.assertFalse(result.created)
        self.assertFalse(result.password_changed)
        self.assertTrue(
            user.check_password("CustomPassword@2026")
        )
        self.assertFalse(
            user.check_password("TestSkynet@2026")
        )

    def test_reset_password_is_explicit(self):
        self.User.objects.create_superuser(
            username="skynet",
            password="OldPassword@2026",
        )

        result = ensure_default_superuser(
            reset_password=True,
        )

        user = self.User.objects.get(username="skynet")

        self.assertTrue(result.password_changed)
        self.assertTrue(
            user.check_password("TestSkynet@2026")
        )

    @override_settings(
        KRTC_DEFAULT_SUPERUSER_PASSWORD="",
    )
    def test_create_without_password_uses_unusable_password(self):
        result = ensure_default_superuser()

        user = self.User.objects.get(username="skynet")

        self.assertTrue(result.created)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertFalse(user.has_usable_password())

    @override_settings(
        KRTC_DEFAULT_SUPERUSER_PASSWORD="",
    )
    def test_reset_without_configured_password_fails(self):
        self.User.objects.create_superuser(
            username="skynet",
            password="ExistingPassword@2026",
        )

        with self.assertRaises(ValueError):
            ensure_default_superuser(
                reset_password=True,
            )

    @override_settings(
        KRTC_DEFAULT_SUPERUSER_ENABLED=False,
    )
    def test_disabled_bootstrap_does_nothing(self):
        result = ensure_default_superuser()

        self.assertIsNone(result)
        self.assertFalse(
            self.User.objects.filter(
                username="skynet",
            ).exists()
        )