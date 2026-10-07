from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse


class GlobalHomeNavigationTests(TestCase):
    """驗證登入後正式前台共用Home導覽與既有權限語意。"""

    def setUp(self):
        administrator_group, _ = Group.objects.get_or_create(
            name="Administrator"
        )
        self.user = get_user_model().objects.create_user(
            username="global-nav-admin",
            password="Pass1234!",
        )
        self.user.groups.add(administrator_group)
        self.client.force_login(self.user)

    def test_shared_header_pages_have_one_named_dashboard_home_link(self):
        home_url = reverse("dashboard:home")
        route_names = (
            "dashboard:event_record_list",
            "dashboard:device_list",
            "dashboard:event_snapshot_list",
            "dashboard:station_broadcast",
            "settings_app:station_settings",
            "settings_app:user_management",
        )

        for route_name in route_names:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response,
                    'class="system-header__button system-header__button--home"',
                    count=1,
                )
                self.assertContains(response, f'href="{home_url}"')
                self.assertContains(
                    response,
                    f'action="{reverse("logout")}"',
                )

    def test_dashboard_does_not_link_home_to_itself(self):
        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "system-header__button--home")

    def test_monitor_keeps_dark_header_home_link(self):
        response = self.client.get(reverse("dashboard:monitor"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="back-dashboard-link"', count=1)
        self.assertContains(response, f'href="{reverse("dashboard:home")}"')
        self.assertNotContains(response, "system-header__button--home")
