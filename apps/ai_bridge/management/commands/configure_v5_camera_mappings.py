from django.core.management.base import BaseCommand, CommandError

from apps.ai_bridge.models import InferenceCameraMapping, InferenceHost
from apps.cameras.models import Camera


class Command(BaseCommand):
    help = "Configure canonical KMetro v1.3 camera IDs for the physical inference host."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host-code",
            default="INF-KRTC-ST-001-01",
        )

    def handle(self, *args, **options):
        host_code = options["host_code"]
        try:
            host = InferenceHost.objects.get(host_code=host_code)
        except InferenceHost.DoesNotExist as exc:
            raise CommandError(f"Inference host not found: {host_code}") from exc

        configured = 0
        missing = []
        for camera_code in ("CAM-002", "CAM-003", "CAM-004"):
            camera = Camera.objects.filter(camera_code__iexact=camera_code).first()
            if camera is None:
                missing.append(camera_code)
                continue

            mapping = InferenceCameraMapping.objects.filter(
                inference_host=host,
                camera=camera,
            ).first()
            if mapping is None:
                mapping = InferenceCameraMapping.objects.create(
                    inference_host=host,
                    source_camera_id=camera_code,
                    camera=camera,
                    is_active=True,
                    description=(
                        f"KMetro API v1.3 canonical camera_id {camera_code} "
                        f"-> PAO {camera.camera_code}"
                    ),
                )
            else:
                mapping.source_camera_id = camera_code
                mapping.is_active = True
                mapping.description = (
                    f"KMetro API v1.3 canonical camera_id {camera_code} "
                    f"-> PAO {camera.camera_code}"
                )
                mapping.save(
                    update_fields=[
                        "source_camera_id",
                        "is_active",
                        "description",
                        "updated_at",
                    ]
                )
            configured += 1
            self.stdout.write(f"{host_code}: {camera_code} -> {camera.camera_code}")

        self.stdout.write(self.style.SUCCESS(
            f"Configured={configured}, missing={','.join(missing) if missing else 'none'}"
        ))
