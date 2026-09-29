from unittest.mock import patch

from django.core.management.base import BaseCommand

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.inference_client import InferenceClient
from apps.ai_bridge.services.zone_count_sync import sync_zone_counts_for_host
from apps.dashboard.views import get_area_crowd_flow_items
from apps.events.models import ZoneCountState


class Command(BaseCommand):
    help = "Self-test V6.4.6 zone-count integration and permission UI marker."

    def handle(self, *args, **options):
        host, _ = InferenceHost.objects.get_or_create(
            host_code="ZONE-SELFTEST",
            defaults={
                "name": "Zone Count Self Test",
                "base_url": "http://127.0.0.1:65530",
                "is_active": False,
            },
        )
        ZoneCountState.objects.filter(inference_host=host).delete()
        payload = {
            "items": [
                {
                    "camera_id": "cam1",
                    "station": "測試站",
                    "roi_id": "候車區 A",
                    "count": 12,
                    "threshold": 20,
                    "updated_at": "2026-08-21T19:00:00+08:00",
                },
                {
                    "camera_id": "cam1",
                    "station": "測試站",
                    "roi_id": "候車區 B",
                    "count": 21,
                    "threshold": 20,
                    "updated_at": "2026-08-21T19:00:00+08:00",
                },
            ]
        }
        try:
            with patch.object(InferenceClient, "get_zone_counts", return_value=payload):
                result = sync_zone_counts_for_host(host)
            assert result.upserted == 2
            rows = ZoneCountState.objects.filter(inference_host=host)
            assert rows.count() == 2
            assert rows.get(roi_id="候車區 A").count == 12
            assert rows.get(roi_id="候車區 B").is_abnormal is True
            items = [i for i in get_area_crowd_flow_items() if i["zone_key"].startswith(f"{host.id}:")]
            assert {i["zone_label"] for i in items} == {"候車區 A", "候車區 B"}
            assert any(i["count"] == 12 for i in items)

            header = open("templates/dashboard/includes/system_header.html", encoding="utf-8-sig").read()
            assert 'can_access_settings_global and current_page != "settings"' in header

            self.stdout.write(self.style.SUCCESS("PASS: /zone_counts payload maps to ROI-based ZoneCountState."))
            self.stdout.write(self.style.SUCCESS("PASS: Dashboard area-flow items use roi_id/zone_label."))
            self.stdout.write(self.style.SUCCESS("PASS: System Settings header entry is permission-gated."))
            self.stdout.write(self.style.SUCCESS("V6.4.6 Zone Count + Permission self-test PASSED."))
        finally:
            ZoneCountState.objects.filter(inference_host=host).delete()
            if host.host_code == "ZONE-SELFTEST":
                host.delete()
