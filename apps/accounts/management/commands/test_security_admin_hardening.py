from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings

from apps.settings_app.models import UIConfiguration


class Command(BaseCommand):
    help = "Validate V6.4.6.2 hidden 404 and Superuser USB admin hardening."

    def handle(self, *args, **options):
        failures = []

        def check(condition, message):
            if condition:
                self.stdout.write(self.style.SUCCESS(f"PASS: {message}"))
            else:
                failures.append(message)
                self.stdout.write(self.style.ERROR(f"FAIL: {message}"))

        User = get_user_model()
        regular_username = "__krtc_security_test_user__"
        regular, _ = User.objects.get_or_create(username=regular_username)
        regular.is_active = True
        regular.is_staff = False
        regular.is_superuser = False
        regular.set_unusable_password()
        regular.save()

        superuser = User.objects.filter(is_superuser=True, is_active=True).order_by("id").first()
        config = UIConfiguration.load()
        original = {
            "required": config.superuser_usb_required,
            "digest": config.superuser_usb_token_sha256,
            "key_id": config.superuser_usb_key_id,
        }

        try:
            with override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver", "127.0.0.1", "localhost"]):
                client = Client()

                # Unknown URL must not disclose Django DEBUG URL patterns.
                response = client.get("/usb-key")
                body = response.content.decode("utf-8", errors="replace").strip()
                check(response.status_code == 404, "unknown /usb-key returns HTTP 404")
                check(body == "404 forbidden", "unknown /usb-key hides DEBUG route details")

                # Anonymous/non-Superuser admin access is intentionally undiscoverable.
                response = client.get("/admin/")
                check(response.status_code == 404, "anonymous /admin/ is hidden")
                check(response.content.decode().strip() == "404 forbidden", "anonymous admin response is minimal")

                client.force_login(regular)
                response = client.get("/admin/")
                check(response.status_code == 404, "non-Superuser /admin/ is hidden")
                response = client.get("/admin/usb-key/")
                check(response.status_code == 404, "non-Superuser USB Key manager is hidden")
                client.logout()

                if superuser is None:
                    check(False, "active Superuser exists")
                else:
                    # First-time provisioning must remain possible when enforcement is OFF.
                    config.superuser_usb_required = False
                    config.superuser_usb_token_sha256 = ""
                    config.superuser_usb_key_id = ""
                    config.save(update_fields=[
                        "superuser_usb_required",
                        "superuser_usb_token_sha256",
                        "superuser_usb_key_id",
                        "updated_at",
                    ])

                    client.force_login(superuser)
                    response = client.get("/admin/")
                    check(response.status_code == 200, "Superuser can enter admin when USB enforcement is disabled")
                    admin_body = response.content.decode("utf-8", errors="replace")
                    check("安全管理" in admin_body, "Admin index contains Security Management section")
                    check("Superuser USB Key 管理" in admin_body, "Admin index exposes low-profile USB Key manager link")

                    response = client.get("/admin/usb-key/")
                    check(response.status_code == 200, "Superuser can open USB Key manager for first-time provisioning")

                    # When enforcement is ON, a bogus digest must fail closed.
                    config.superuser_usb_required = True
                    config.superuser_usb_token_sha256 = "0" * 64
                    config.superuser_usb_key_id = "SECURITY-SELF-TEST"
                    config.save(update_fields=[
                        "superuser_usb_required",
                        "superuser_usb_token_sha256",
                        "superuser_usb_key_id",
                        "updated_at",
                    ])

                    response = client.get("/admin/")
                    check(response.status_code == 404, "Superuser without trusted USB is hidden from /admin/")
                    check(response.content.decode().strip() == "404 forbidden", "USB rejection returns minimal hidden 404")

        finally:
            config.superuser_usb_required = original["required"]
            config.superuser_usb_token_sha256 = original["digest"]
            config.superuser_usb_key_id = original["key_id"]
            config.save(update_fields=[
                "superuser_usb_required",
                "superuser_usb_token_sha256",
                "superuser_usb_key_id",
                "updated_at",
            ])
            regular.delete()

        if failures:
            raise CommandError(f"Security Admin Hardening self-test failed: {len(failures)} failure(s).")

        self.stdout.write(self.style.SUCCESS("V6.4.6.2 Security Admin Hardening self-test PASSED."))
