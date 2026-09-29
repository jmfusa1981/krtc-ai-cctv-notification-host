from django.test import TestCase, override_settings

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.event_importer import EventImporter
from apps.ai_bridge.services.inference_client import InferenceClient
from apps.cameras.models import Camera
from apps.events.models import Event


@override_settings(KRTC_EXTERNAL_STATION_MAPPING={"R16_左營": "KRTC-ST-001"})
class CameraCodeFallbackTests(TestCase):
    def setUp(self):
        self.camera = Camera.objects.create(
            camera_code="CAM-003",
            name="CAM-003 下行電扶梯攝影機",
            area="下行電扶梯區",
            is_active=True,
        )
        self.host = InferenceHost.objects.create(
            host_code="INF-KRTC-ST-001-01",
            name="Physical",
            station_code="KRTC-ST-001",
            base_url="http://192.168.6.20:8000",
        )
        self.importer = EventImporter(
            client=InferenceClient(self.host.base_url),
            inference_host=self.host,
        )

    def payload(self):
        return {
            "id": 20260804000349,
            "timestamp": "2026-08-04T15:53:08.462582+08:00",
            "station": "R16_左營",
            "camera_id": "CAM-003",
            "roi_id": "global",
            "event_code": "EVT_SMOKE",
            "snapshot_url": "http://192.168.6.20:8000/snapshots/test.jpg",
            "bbox": None,
        }

    def test_canonical_camera_code_links_without_explicit_mapping(self):
        result = self.importer.import_payload(self.payload())
        self.assertEqual(result.status, "imported")
        event = Event.objects.get()
        self.assertEqual(event.camera_id, self.camera.pk)
        self.assertEqual(event.mapping_status, "resolved")

    def test_duplicate_import_repairs_previously_unmapped_event(self):
        Event.objects.create(
            event_id="INF-KRTC-ST-001-01:20260804000349",
            source_event_id="20260804000349",
            inference_host_code="INF-KRTC-ST-001-01",
            station_code="KRTC-ST-001",
            camera_code="CAM-003",
            mapping_status="unmapped",
            event_type="smoke_detected",
            detected_at="2026-08-04T15:53:08+08:00",
        )
        result = self.importer.import_payload(self.payload())
        self.assertEqual(result.status, "duplicate")
        event = Event.objects.get()
        self.assertEqual(event.camera_id, self.camera.pk)
        self.assertEqual(event.mapping_status, "resolved")
