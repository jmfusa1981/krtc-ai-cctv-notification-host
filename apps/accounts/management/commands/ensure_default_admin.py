from django.conf import settings
from django.core.management.base import BaseCommand

from apps.accounts.bootstrap import ensure_default_admin


class Command(BaseCommand):
    help = "Create or repair the built-in KRTC frontend administrator account."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Reset the built-in admin password to KRTC_DEFAULT_ADMIN_PASSWORD.",
        )

    def handle(self, *args, **options):
        result = ensure_default_admin(reset_password=options["reset_password"])
        if result is None:
            self.stdout.write(self.style.WARNING("Default admin bootstrap is disabled or deferred."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Default frontend administrator ready: "
                f"username={result.username}, created={result.created}, "
                f"password_changed={result.password_changed}, role_added={result.role_added}"
            )
        )
        if options["reset_password"]:
            self.stdout.write(
                "Password source: KRTC_DEFAULT_ADMIN_PASSWORD "
                f"(configured={bool(getattr(settings, 'KRTC_DEFAULT_ADMIN_PASSWORD', ''))})"
            )
