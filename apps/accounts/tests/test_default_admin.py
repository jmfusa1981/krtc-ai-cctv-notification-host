from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase, override_settings

from apps.accounts.bootstrap import ensure_default_admin


@override_settings(
    KRTC_DEFAULT_ADMIN_ENABLED=True,
    KRTC_DEFAULT_ADMIN_USERNAME="admin",
    KRTC_DEFAULT_ADMIN_PASSWORD="TestAdmin@2026",
)
class DefaultAdminBootstrapTests(TestCase):
    def test_creates_loginable_non_superuser_administrator(self):
        result = ensure_default_admin(reset_password=True)
        self.assertIsNotNone(result)

        user = get_user_model().objects.get(username="admin")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.groups.filter(name="Administrator").exists())
        self.assertIsNotNone(authenticate(username="admin", password="TestAdmin@2026"))

    def test_normal_bootstrap_does_not_overwrite_changed_password(self):
        ensure_default_admin(reset_password=True)
        user = get_user_model().objects.get(username="admin")
        user.set_password("ChangedByUser@2026")
        user.save(update_fields=["password"])

        ensure_default_admin(reset_password=False)
        self.assertIsNotNone(authenticate(username="admin", password="ChangedByUser@2026"))
        self.assertIsNone(authenticate(username="admin", password="TestAdmin@2026"))
