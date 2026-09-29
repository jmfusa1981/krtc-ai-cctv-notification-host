import asyncio
import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.event_importer import EventImporter
from apps.ai_bridge.services.inference_client import InferenceClient
from apps.cameras.models import Camera
from apps.events.models import Event
from apps.notifications.models import AudioFile, BroadcastLog, BroadcastRule, SpeakerDevice


@override_settings(
    KRTC_EXTERNAL_STATION_MAPPING={"美麗島站": "KRTC-ST-001"},
    AUTO_BROADCAST_PROCESS_ON_IMPORT=False,
    AUTO_BROADCAST_COOLDOWN_SECONDS=15,
)
class V5ListenerContractTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="krtc_v5_listener_test_")
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.host = InferenceHost.objects.create(
            host_code="INF-KRTC-ST-001-01", name="Physical", station_code="KRTC-ST-001",
            host_type="physical", ip_address="192.168.6.20", port=8000,
            base_url="http://192.168.6.20:8000", websocket_url="ws://192.168.6.20:8000/ws/alerts")
        self.importer = EventImporter(client=InferenceClient(self.host.base_url), inference_host=self.host)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def payload(self, **changes):
        value = {"id": 20260803000028, "timestamp": "2026-08-03T13:32:22.706505+08:00",
                 "station": "美麗島站", "camera_id": "cam2", "roi_id": "luggage_zone_0",
                 "event_code": "EVT_LUGGAGE_LARGE",
                 "snapshot_url": "http://192.168.6.20:8000/snapshots/missing.jpg",
                 "bbox": [0, 298, 219, 654]}
        value.update(changes)
        return value

    def test_unmapped_event_is_stored_with_exact_source_id_and_metadata(self):
        result = self.importer.import_payload(self.payload())
        self.assertEqual(result.status, "imported")
        event = Event.objects.get()
        self.assertEqual(event.source_event_id, "20260803000028")
        self.assertEqual(event.mapping_status, "unmapped")
        self.assertEqual(event.roi_id, "luggage_zone_0")
        self.assertEqual(event.bbox, [0, 298, 219, 654])
        self.assertEqual(BroadcastLog.objects.count(), 0)

    def test_websocket_rest_overlap_is_idempotent(self):
        first = self.importer.import_payload(self.payload(), ingestion_mode="websocket")
        second = self.importer.import_payload(self.payload(), ingestion_mode="catchup", allow_broadcast=False)
        self.assertEqual(first.status, "imported")
        self.assertEqual(second.status, "duplicate")
        self.assertEqual(Event.objects.count(), 1)

    def test_fire_is_accepted_but_never_auto_broadcast(self):
        result = self.importer.import_payload(self.payload(id=29, event_code="EVT_FIRE"))
        self.assertEqual(result.status, "imported")
        self.assertEqual(Event.objects.get().event_type, "fire_detected")
        self.assertEqual(BroadcastLog.objects.count(), 0)

    def test_invalid_bbox_is_rejected_without_crashing(self):
        result = self.importer.import_payload(self.payload(bbox=[1, 2]))
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "invalid_bbox")

    def test_duplicate_event_can_create_missing_auto_broadcast_once(self):
        camera = Camera.objects.create(
            camera_code="cam2",
            name="Camera 2",
            rtsp_url="rtsp://127.0.0.1/cam2",
            is_active=True,
        )
        speaker = SpeakerDevice.objects.create(
            speaker_code="SPK-002",
            name="Speaker 2",
            ip_address="192.0.2.2",
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
        )
        audio = AudioFile.objects.create(
            audio_code="AUD-LUGGAGE",
            name="Luggage warning",
            audio_type=AudioFile.AUDIO_TYPE_ALERT,
            file=SimpleUploadedFile("luggage.wav", b"fake wav"),
            is_active=True,
        )
        BroadcastRule.objects.create(
            rule_code="RULE-LUGGAGE-CAM2-SPK2",
            name="Luggage rule",
            event_type="large_luggage_intrusion",
            camera=camera,
            speaker=speaker,
            audio_file=audio,
            auto_broadcast=True,
            is_active=True,
        )

        first = self.importer.import_payload(self.payload(), allow_broadcast=False)
        self.assertEqual(first.status, "imported")
        self.assertEqual(BroadcastLog.objects.count(), 0)

        second = self.importer.import_payload(self.payload(), ingestion_mode="catchup")
        self.assertEqual(second.status, "duplicate")
        self.assertEqual(second.broadcast_logs_created, 1)
        self.assertEqual(BroadcastLog.objects.count(), 1)

        third = self.importer.import_payload(self.payload(), ingestion_mode="catchup")
        self.assertEqual(third.status, "duplicate")
        self.assertEqual(third.broadcast_logs_created, 0)
        self.assertEqual(BroadcastLog.objects.count(), 1)

    def test_global_rule_can_broadcast_unmapped_event(self):
        speaker = SpeakerDevice.objects.create(
            speaker_code="SPK-003",
            name="Speaker 3",
            ip_address="192.0.2.3",
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
        )
        audio = AudioFile.objects.create(
            audio_code="AUD-LUGGAGE",
            name="Luggage warning",
            audio_type=AudioFile.AUDIO_TYPE_ALERT,
            file=SimpleUploadedFile("luggage.wav", b"fake wav"),
            is_active=True,
        )
        BroadcastRule.objects.create(
            rule_code="RULE-LUGGAGE-GLOBAL",
            name="Global luggage rule",
            event_type="large_luggage_intrusion",
            camera=None,
            speaker=speaker,
            audio_file=audio,
            auto_broadcast=True,
            is_active=True,
        )

        result = self.importer.import_payload(self.payload())
        self.assertEqual(result.status, "imported")
        self.assertEqual(result.broadcast_logs_created, 1)
        self.assertEqual(BroadcastLog.objects.count(), 1)
        log = BroadcastLog.objects.get()
        self.assertEqual(log.request_payload["camera_code"], "cam2")

    def test_auto_broadcast_cooldown_skips_event_burst_for_same_rule(self):
        speaker = SpeakerDevice.objects.create(
            speaker_code="SPK-005",
            name="Speaker 5",
            ip_address="192.0.2.5",
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
        )
        audio = AudioFile.objects.create(
            audio_code="AUD-LUGGAGE-COOLDOWN",
            name="Luggage warning cooldown",
            audio_type=AudioFile.AUDIO_TYPE_ALERT,
            file=SimpleUploadedFile("luggage-cooldown.wav", b"fake wav"),
            is_active=True,
        )
        BroadcastRule.objects.create(
            rule_code="RULE-LUGGAGE-COOLDOWN",
            name="Luggage cooldown rule",
            event_type="large_luggage_intrusion",
            camera=None,
            speaker=speaker,
            audio_file=audio,
            auto_broadcast=True,
            is_active=True,
        )

        first = self.importer.import_payload(self.payload(id=20260803000031))
        self.assertEqual(first.broadcast_logs_created, 1)

        second = self.importer.import_payload(self.payload(id=20260803000032))
        self.assertEqual(second.broadcast_logs_created, 0)
        self.assertEqual(second.broadcast_logs_skipped, 1)
        self.assertEqual(BroadcastLog.objects.count(), 1)

    def test_auto_broadcast_cooldown_does_not_block_different_rule(self):
        speaker_a = SpeakerDevice.objects.create(
            speaker_code="SPK-006",
            name="Speaker 6",
            ip_address="192.0.2.6",
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
        )
        speaker_b = SpeakerDevice.objects.create(
            speaker_code="SPK-007",
            name="Speaker 7",
            ip_address="192.0.2.7",
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
        )
        audio_a = AudioFile.objects.create(
            audio_code="AUD-LUGGAGE-RULE-A",
            name="Luggage warning A",
            audio_type=AudioFile.AUDIO_TYPE_ALERT,
            file=SimpleUploadedFile("luggage-rule-a.wav", b"fake wav"),
            is_active=True,
        )
        audio_b = AudioFile.objects.create(
            audio_code="AUD-LUGGAGE-RULE-B",
            name="Luggage warning B",
            audio_type=AudioFile.AUDIO_TYPE_ALERT,
            file=SimpleUploadedFile("luggage-rule-b.wav", b"fake wav"),
            is_active=True,
        )
        BroadcastRule.objects.create(
            rule_code="RULE-LUGGAGE-SCOPE-A",
            name="Luggage scoped rule A",
            event_type="large_luggage_intrusion",
            camera=None,
            speaker=speaker_a,
            audio_file=audio_a,
            auto_broadcast=True,
            is_active=True,
        )
        BroadcastRule.objects.create(
            rule_code="RULE-LUGGAGE-SCOPE-B",
            name="Luggage scoped rule B",
            event_type="large_luggage_intrusion",
            camera=None,
            speaker=speaker_b,
            audio_file=audio_b,
            auto_broadcast=True,
            is_active=True,
        )

        result = self.importer.import_payload(self.payload(id=20260803000033))
        self.assertEqual(result.broadcast_logs_created, 2)
        self.assertEqual(BroadcastLog.objects.count(), 2)
        self.assertEqual(
            set(BroadcastLog.objects.values_list("rule__rule_code", flat=True)),
            {"RULE-LUGGAGE-SCOPE-A", "RULE-LUGGAGE-SCOPE-B"},
        )
        self.assertEqual(
            set(BroadcastLog.objects.values_list("request_payload__cooldown_scope", flat=True)),
            {"rule_speaker_audio_source"},
        )

    def test_single_rule_can_target_multiple_speakers(self):
        speaker_a = SpeakerDevice.objects.create(
            speaker_code="SPK-008",
            name="Speaker 8",
            ip_address="192.0.2.8",
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
        )
        speaker_b = SpeakerDevice.objects.create(
            speaker_code="SPK-009",
            name="Speaker 9",
            ip_address="192.0.2.9",
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
        )
        audio = AudioFile.objects.create(
            audio_code="AUD-LUGGAGE-MULTI",
            name="Luggage warning multi speaker",
            audio_type=AudioFile.AUDIO_TYPE_ALERT,
            file=SimpleUploadedFile("luggage-multi.wav", b"fake wav"),
            is_active=True,
        )
        rule = BroadcastRule.objects.create(
            rule_code="RULE-LUGGAGE-MULTI-SPEAKER",
            name="Luggage multi speaker rule",
            event_type="large_luggage_intrusion",
            camera=None,
            audio_file=audio,
            auto_broadcast=True,
            is_active=True,
        )
        rule.speakers.set([speaker_a, speaker_b])

        result = self.importer.import_payload(self.payload(id=20260803000034))
        self.assertEqual(result.broadcast_logs_created, 2)
        self.assertEqual(BroadcastLog.objects.count(), 2)
        self.assertEqual(
            set(BroadcastLog.objects.values_list("speaker__speaker_code", flat=True)),
            {"SPK-008", "SPK-009"},
        )
        self.assertEqual(
            set(BroadcastLog.objects.values_list("request_payload__target_speaker_count", flat=True)),
            {2},
        )

    def test_reconcile_existing_event_creates_missing_rule_log_once(self):
        camera = Camera.objects.create(
            camera_code="cam2",
            name="Camera 2",
            rtsp_url="rtsp://127.0.0.1/cam2",
            is_active=True,
        )
        speaker = SpeakerDevice.objects.create(
            speaker_code="SPK-004",
            name="Speaker 4",
            ip_address="192.0.2.4",
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
        )
        audio = AudioFile.objects.create(
            audio_code="AUD-FALL",
            name="Fall warning",
            audio_type=AudioFile.AUDIO_TYPE_ALERT,
            file=SimpleUploadedFile("fall.wav", b"fake wav"),
            is_active=True,
        )

        event_result = self.importer.import_payload(
            self.payload(event_code="EVT_FALL"),
            allow_broadcast=False,
        )
        event = Event.objects.get(pk=event_result.event_id)

        BroadcastRule.objects.create(
            rule_code="RULE-FALL-GLOBAL",
            name="Fall global rule",
            event_type="escalator_fall",
            camera=None,
            speaker=speaker,
            audio_file=audio,
            auto_broadcast=True,
            is_active=True,
        )

        result = self.importer.reconcile_existing_event(event)
        self.assertEqual(result.broadcast_logs_created, 1)
        self.assertEqual(BroadcastLog.objects.count(), 1)

        second = self.importer.reconcile_existing_event(event)
        self.assertEqual(second.broadcast_logs_created, 0)
        self.assertEqual(BroadcastLog.objects.count(), 1)
