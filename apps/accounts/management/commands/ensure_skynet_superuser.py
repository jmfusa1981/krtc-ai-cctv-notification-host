from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.bootstrap import ensure_default_superuser


class Command(BaseCommand):
    help = (
        "Create or repair the built-in KRTC engineering Superuser account."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help=(
                "Reset the built-in Superuser password to "
                "KRTC_DEFAULT_SUPERUSER_PASSWORD."
            ),
        )

    def handle(self, *args, **options):
        reset_password = bool(options["reset_password"])

        try:
            result = ensure_default_superuser(
                reset_password=reset_password,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if result is None:
            self.stdout.write(
                self.style.WARNING(
                    "Default Superuser bootstrap is disabled or deferred."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Default engineering Superuser ready: "
                f"username={result.username}, "
                f"created={result.created}, "
                f"password_changed={result.password_changed}, "
                f"permissions_repaired={result.permissions_repaired}"
            )
        )

        if reset_password:
            self.stdout.write(
                "Password source: KRTC_DEFAULT_SUPERUSER_PASSWORD "
                f"(configured={bool(getattr(settings, 'KRTC_DEFAULT_SUPERUSER_PASSWORD', ''))})"
            )