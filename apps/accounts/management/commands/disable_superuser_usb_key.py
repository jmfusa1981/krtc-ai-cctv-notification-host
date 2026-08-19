from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.settings_app.models import UIConfiguration


class Command(BaseCommand):
    help = "Emergency local disable of Superuser USB enforcement."

    def handle(self, *args, **options):
        config = UIConfiguration.load()
        config.superuser_usb_required = False
        config.superuser_usb_token_sha256 = ""
        config.superuser_usb_key_id = ""
        config.superuser_usb_updated_at = timezone.now()
        config.save(update_fields=[
            "superuser_usb_required", "superuser_usb_token_sha256",
            "superuser_usb_key_id", "superuser_usb_updated_at", "updated_at",
        ])
        self.stdout.write(self.style.SUCCESS("Superuser USB enforcement has been disabled on this host."))
