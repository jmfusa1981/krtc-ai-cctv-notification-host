from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the default Skynet Superuser if it does not already exist."

    def handle(self, *args, **options):
        if not getattr(settings, "KRTC_DEFAULT_SUPERUSER_ENABLED", True):
            self.stdout.write("Default Superuser bootstrap is disabled.")
            return

        username = settings.KRTC_DEFAULT_SUPERUSER_USERNAME
        password = settings.KRTC_DEFAULT_SUPERUSER_PASSWORD
        User = get_user_model()

        user = User.objects.filter(username=username).first()
        if user:
            self.stdout.write(
                self.style.WARNING(
                    f"{username} already exists. Password and permissions were not overwritten."
                )
            )
            return

        user = User.objects.create_superuser(username=username, email="", password=password)
        self.stdout.write(self.style.SUCCESS(f"Created Superuser: {user.username}"))
