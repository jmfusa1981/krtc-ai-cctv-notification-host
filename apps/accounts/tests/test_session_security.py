import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse


class SessionPolicyTests(SimpleTestCase):
    def test_browser_session_cookie_policy_is_enabled(self):
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")

    def test_http_deployment_does_not_require_secure_cookies(self):
        self.assertFalse(settings.SESSION_COOKIE_SECURE)
        self.assertFalse(settings.CSRF_COOKIE_SECURE)

        production_source = (
            Path(settings.BASE_DIR) / "config" / "settings_production.py"
        ).read_text(encoding="utf-8")
        self.assertIn("KRTC_ENABLE_HTTPS", production_source)
        self.assertIn("SESSION_COOKIE_SECURE = False", production_source)
        self.assertIn("CSRF_COOKIE_SECURE = False", production_source)

    def test_https_production_policy_is_explicit_and_lab_safe(self):
        production_source = (
            Path(settings.BASE_DIR) / "config" / "settings_production.py"
        ).read_text(encoding="utf-8")

        self.assertIn("SECURE_SSL_REDIRECT = True", production_source)
        self.assertIn("SESSION_COOKIE_SECURE = True", production_source)
        self.assertIn("CSRF_COOKIE_SECURE = True", production_source)
        self.assertIn(
            'os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0")',
            production_source,
        )
        self.assertIn("SECURE_CONTENT_TYPE_NOSNIFF = True", production_source)
        self.assertIn('X_FRAME_OPTIONS = "DENY"', production_source)
        self.assertIn(
            'SECURE_PROXY_SSL_HEADER = (\n    "HTTP_X_FORWARDED_PROTO",\n    "https",\n)',
            production_source,
        )

    def test_database_session_backend_remains_in_use(self):
        self.assertEqual(
            settings.SESSION_ENGINE,
            "django.contrib.sessions.backends.db",
        )

    def test_no_idle_timeout_setting_was_added(self):
        for relative_path in ("config/settings.py", "config/settings_production.py"):
            source = (Path(settings.BASE_DIR) / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("SESSION_COOKIE_AGE", source)


class BrowserStorageAuditTests(SimpleTestCase):
    def _javascript_sources(self):
        static_root = Path(settings.BASE_DIR) / "static" / "js"
        return {
            path: path.read_text(encoding="utf-8")
            for path in static_root.rglob("*.js")
        }

    def test_browser_storage_contains_no_authentication_secret(self):
        forbidden = re.compile(
            r"password|credential|auth[_-]?token|session[_-]?key|access[_-]?token",
            re.IGNORECASE,
        )
        statements = []
        for source in self._javascript_sources().values():
            statements.extend(
                re.findall(r"(?:localStorage|sessionStorage)\.[^;\n]+", source)
            )

        self.assertTrue(statements)
        for statement in statements:
            self.assertIsNone(forbidden.search(statement), statement)

    def test_unload_handlers_do_not_perform_logout(self):
        marker = re.compile(r"beforeunload|pagehide|(?<!before)unload")
        for path, source in self._javascript_sources().items():
            lines = source.splitlines()
            for index, line in enumerate(lines):
                if not marker.search(line):
                    continue
                nearby = "\n".join(lines[max(0, index - 5):index + 6])
                self.assertNotIn("logout", nearby.lower(), str(path))

    def test_javascript_does_not_write_cookies(self):
        source = "\n".join(self._javascript_sources().values())
        self.assertNotRegex(source, r"document\.cookie\s*=")


class SessionLifecycleTests(TestCase):
    password = "SessionTest@2026"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="session-user",
            password=self.password,
        )

    def _login(self, client=None, user=None):
        client = client or self.client
        user = user or self.user
        response = client.post(
            reverse("login"),
            {"username": user.username, "password": self.password},
        )
        self.assertEqual(response.status_code, 302)
        return client, response

    def test_login_creates_browser_session_and_authenticated_access(self):
        client, response = self._login()
        session = client.session

        self.assertEqual(int(session["_auth_user_id"]), self.user.pk)
        self.assertTrue(session.session_key)
        self.assertEqual(client.get(reverse("dashboard:home")).status_code, 200)

        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertEqual(cookie["expires"], "")
        self.assertEqual(cookie["max-age"], "")
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertFalse(cookie["secure"])

    def test_manual_logout_invalidates_server_session_and_old_key(self):
        client, _response = self._login()
        old_session_key = client.session.session_key
        old_session_client = Client()
        old_session_client.cookies[settings.SESSION_COOKIE_NAME] = old_session_key

        logout_response = client.post(reverse("logout"))

        self.assertEqual(logout_response.status_code, 302)
        self.assertFalse(Session.objects.filter(session_key=old_session_key).exists())
        self.assertNotIn("_auth_user_id", client.session)
        denied = old_session_client.get(reverse("dashboard:home"))
        self.assertEqual(denied.status_code, 302)
        self.assertIn(reverse("login"), denied.url)

    def test_shared_session_works_across_tabs_then_logout_revokes_both(self):
        tab_a, _response = self._login()
        shared_key = tab_a.session.session_key
        tab_b = Client()
        tab_b.cookies[settings.SESSION_COOKIE_NAME] = shared_key

        self.assertEqual(tab_b.get(reverse("dashboard:home")).status_code, 200)
        self.assertEqual(tab_a.post(reverse("logout")).status_code, 302)
        denied = tab_b.get(reverse("dashboard:home"))
        self.assertEqual(denied.status_code, 302)
        self.assertIn(reverse("login"), denied.url)

    def test_logout_is_post_only_and_csrf_protection_remains_active(self):
        self._login()
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)

        csrf_client = Client(enforce_csrf_checks=True)
        rejected_login = csrf_client.post(
            reverse("login"),
            {"username": self.user.username, "password": self.password},
        )
        self.assertIn(rejected_login.status_code, {403, 404})

        csrf_client.force_login(self.user)
        rejected_logout = csrf_client.post(reverse("logout"))
        self.assertIn(rejected_logout.status_code, {403, 404})

    def test_all_existing_frontend_roles_can_authenticate(self):
        for role_name in ("Administrator", "Maintainer", "Operator"):
            with self.subTest(role=role_name):
                group, _created = Group.objects.get_or_create(name=role_name)
                user = get_user_model().objects.create_user(
                    username=f"session-{role_name.lower()}",
                    password=self.password,
                )
                user.groups.add(group)
                client, _response = self._login(Client(), user)
                self.assertEqual(client.get(reverse("dashboard:home")).status_code, 200)

    def test_superuser_can_authenticate(self):
        user = get_user_model().objects.create_superuser(
            username="session-superuser",
            email="root@example.com",
            password=self.password,
        )
        client, _response = self._login(Client(), user)
        self.assertEqual(client.get(reverse("dashboard:home")).status_code, 200)

    @mock.patch(
        "apps.settings_app.ui_context.resolve_login_background_url",
        return_value="/media/ui/login/custom-background.jpg",
    )
    def test_custom_login_background_context_is_preserved(self, _resolver):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/media/ui/login/custom-background.jpg")
