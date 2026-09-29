from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse


class UserManagementPageTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_group, _ = Group.objects.get_or_create(name="Administrator")
        self.operator_group, _ = Group.objects.get_or_create(name="Operator")

        self.admin = User.objects.create_user(username="admin-test", password="Pass1234!")
        self.admin.groups.add(self.admin_group)
        self.operator = User.objects.create_user(username="operator-test", password="Pass1234!")
        self.operator.groups.add(self.operator_group)

    def test_administrator_can_open_user_management(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("settings_app:user_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "使用者管理")

    def test_operator_cannot_open_user_management(self):
        self.client.force_login(self.operator)
        response = self.client.get(reverse("settings_app:user_management"))
        self.assertEqual(response.status_code, 403)

    def test_remove_user_soft_disables_account(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("settings_app:user_remove", args=[self.operator.pk]))
        self.assertRedirects(response, reverse("settings_app:user_management"))
        self.operator.refresh_from_db()
        self.assertFalse(self.operator.is_active)
