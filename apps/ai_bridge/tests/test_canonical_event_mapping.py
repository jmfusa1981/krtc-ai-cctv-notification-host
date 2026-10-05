from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.event_importer import EventImporter
from apps.ai_bridge.services.inference_client import InferenceClient
from apps.ai_bridge.services.notify_event_normalizer import normalize_notify_event
from apps.events.event_types import CANONICAL_EVENT_CODE_TO_TYPE
from apps.events.models import Event
from apps.notifications.models import BroadcastRule


class CanonicalEventMappingSourceTests(SimpleTestCase):
    def test_all_official_codes_use_canonical_event_types(self):
        self.assertEqual(
            CANONICAL_EVENT_CODE_TO_TYPE,
            {
                "EVT_FALL": "fall_detected",
                "EVT_FIRE": "fire_detected",
                "EVT_SMOKE": "smoke_detected",
                "EVT_DWELL": "dwell_alert",
                "EVT_CROWD": "crowd_alert",
                "EVT_LUGGAGE_ROLL": "luggage_roll_detected",
                "EVT_LUGGAGE_LARGE": "large_luggage_detected",
                "EVT_WHEELCHAIR": "wheelchair_detected",
            },
        )

    def test_notify_normalizer_uses_authoritative_mapping(self):
        for event_code, expected_type in CANONICAL_EVENT_CODE_TO_TYPE.items():
            with self.subTest(event_code=event_code):
                normalized = normalize_notify_event({"event_code": event_code})
                self.assertEqual(normalized["event_type"], expected_type)

    def test_notify_normalizer_keeps_unknown_code_safe(self):
        normalized = normalize_notify_event({"event_code": "EVT_UNKNOWN"})

        self.assertIsNone(normalized["event_type"])

    def test_new_broadcast_rule_choices_are_canonical_only(self):
        choice_values = {
            value for value, _label in BroadcastRule.EVENT_TYPE_CHOICES
        }

        self.assertEqual(
            choice_values,
            set(CANONICAL_EVENT_CODE_TO_TYPE.values()),
        )
        self.assertNotIn("escalator_fall", choice_values)
        self.assertNotIn("large_luggage_intrusion", choice_values)


@mock.patch(
    "apps.ai_bridge.services.event_importer.schedule_event_snapshot_download"
)
class CanonicalEventIngestionTests(TestCase):
    def setUp(self):
        self.host = InferenceHost.objects.create(
            host_code="INF-CANONICAL-MAPPING",
            name="Canonical mapping test host",
            station_code="KRTC-ST-TEST",
            base_url="http://192.0.2.20:8000",
        )
        self.importer = EventImporter(
            client=InferenceClient(self.host.base_url),
            inference_host=self.host,
        )

    @staticmethod
    def payload(event_code, source_event_id):
        return {
            "id": source_event_id,
            "timestamp": "2026-10-05T10:00:00+08:00",
            "station": "",
            "camera_id": "CAM-CANONICAL-TEST",
            "event_code": event_code,
            "snapshot_url": None,
            "bbox": None,
        }

    def assert_mode_uses_canonical_mapping(self, ingestion_mode):
        for index, (event_code, expected_type) in enumerate(
            CANONICAL_EVENT_CODE_TO_TYPE.items(),
            start=1,
        ):
            source_event_id = f"{ingestion_mode}-{index}"
            with self.subTest(
                ingestion_mode=ingestion_mode,
                event_code=event_code,
            ):
                result = self.importer.import_payload(
                    self.payload(event_code, source_event_id),
                    ingestion_mode=ingestion_mode,
                    allow_broadcast=False,
                )
                event = Event.objects.get(pk=result.event_id)
                self.assertEqual(result.status, "imported")
                self.assertEqual(event.event_type, expected_type)
                self.assertEqual(event.ingestion_mode, ingestion_mode)

    def test_rest_ingestion_uses_all_canonical_mappings(self, _schedule):
        self.assert_mode_uses_canonical_mapping("rest")

    def test_websocket_ingestion_uses_all_canonical_mappings(self, _schedule):
        self.assert_mode_uses_canonical_mapping("websocket")

    def test_unknown_event_code_is_rejected_safely(self, _schedule):
        result = self.importer.import_payload(
            self.payload("EVT_UNKNOWN", "unknown-1"),
            ingestion_mode="rest",
            allow_broadcast=False,
        )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "unknown_event_code")
        self.assertFalse(Event.objects.exists())
