from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.dashboard.views import _aggregate_zone_count_rows


class Command(BaseCommand):
    help = "Self-test V6.4.6.1 RC1 final convergence behaviors."

    def handle(self, *args, **options):
        now = timezone.now()
        host = SimpleNamespace(id=1, host_code="IF-TEST")
        camera_a = SimpleNamespace(camera_code="CAM-001")
        camera_b = SimpleNamespace(camera_code="CAM-002")
        camera_c = SimpleNamespace(camera_code="CAM-003")

        rows = [
            SimpleNamespace(
                inference_host=host,
                inference_host_id=1,
                camera=camera_a,
                camera_id=1,
                source_camera_id="CAM-001",
                station="R16_左營",
                roi_id="月台候車區",
                count=5,
                threshold=20,
                source_updated_at=now,
                received_at=now,
            ),
            SimpleNamespace(
                inference_host=host,
                inference_host_id=1,
                camera=camera_b,
                camera_id=2,
                source_camera_id="CAM-002",
                station="R16_左營",
                roi_id="月台候車區",
                count=7,
                threshold=20,
                source_updated_at=now,
                received_at=now,
            ),
            SimpleNamespace(
                inference_host=host,
                inference_host_id=1,
                camera=camera_c,
                camera_id=3,
                source_camera_id="CAM-003",
                station="R16_左營",
                roi_id="穿堂層",
                count=2,
                threshold=10,
                source_updated_at=now,
                received_at=now,
            ),
        ]

        items = _aggregate_zone_count_rows(rows)
        by_zone = {item["zone_label"]: item for item in items}

        platform = by_zone.get("月台候車區")
        if not platform:
            raise CommandError("FAIL: aggregated zone is missing.")
        if platform["count"] != 12:
            raise CommandError(f"FAIL: expected aggregated count 12, got {platform['count']}.")
        if platform["threshold"] != 20:
            raise CommandError("FAIL: threshold convergence is incorrect.")
        if len(platform.get("source_cameras", [])) != 2:
            raise CommandError("FAIL: source camera list did not preserve both cameras.")
        if len(items) != 2:
            raise CommandError(f"FAIL: expected 2 zones, got {len(items)}.")

        self.stdout.write(self.style.SUCCESS("PASS: same zone across different cameras is summed."))
        self.stdout.write(self.style.SUCCESS("PASS: different zones remain separate."))
        self.stdout.write(self.style.SUCCESS("PASS: source cameras are preserved as secondary information."))
        self.stdout.write(self.style.SUCCESS("V6.4.6.1 RC1 final convergence self-test PASSED."))
