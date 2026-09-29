from django.core.management.base import BaseCommand

from apps.cameras.models import Camera
from apps.events.models import Event


class Command(BaseCommand):
    help = "Backfill Event.camera from source camera_code values such as CAM-003."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cameras = {
            camera.camera_code.casefold(): camera
            for camera in Camera.objects.filter(is_active=True)
        }

        scanned = 0
        repaired = 0
        unresolved = 0

        events = Event.objects.filter(camera__isnull=True).exclude(camera_code="")
        for event in events.iterator():
            scanned += 1
            camera = cameras.get((event.camera_code or "").strip().casefold())
            if camera is None:
                unresolved += 1
                continue

            repaired += 1
            if not dry_run:
                event.camera = camera
                if event.mapping_status == "unmapped":
                    event.mapping_status = "resolved"
                    event.save(update_fields=["camera", "mapping_status", "updated_at"])
                else:
                    event.save(update_fields=["camera", "updated_at"])

        mode = "DRY RUN" if dry_run else "UPDATED"
        self.stdout.write(self.style.SUCCESS(
            f"{mode}: scanned={scanned}, repaired={repaired}, unresolved={unresolved}"
        ))
