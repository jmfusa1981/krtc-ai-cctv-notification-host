import io
import socket
import tempfile
import wave
from io import StringIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.notifications.backends.pjsip import PjsipPreflightError
from apps.notifications.models import AudioFile, SpeakerDevice
from apps.notifications.pjsip_readiness import prepare_pjsip_readiness
from apps.notifications.runtime_config import get_broadcast_runtime_config
from apps.settings_app.models import BroadcastEngineeringSettings


def _wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(b"\x00\x00" * 800)
    return buffer.getvalue()


def _available_udp_port():
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp_socket.bind(("127.0.0.1", 0))
        return udp_socket.getsockname()[1]
    finally:
        udp_socket.close()


@override_settings(
    KRTC_PRODUCTION=False,
    BROADCAST_PLAYBACK_MODE="pjsip",
    PJSIP_EXECUTABLE_PATH="",
    PJSIP_LOCAL_IP="",
    PJSIP_ADVERTISE_IP="",
)
class PjsipReadinessTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.media_override = override_settings(
            MEDIA_ROOT=self.temporary_directory.name,
            PJSIP_LOG_DIR=Path(self.temporary_directory.name) / "logs",
        )
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

        self.executable_path = (
            Path(self.temporary_directory.name) / "pjsua.exe"
        )
        self.executable_path.write_bytes(b"test executable")
        sip_port = _available_udp_port()
        rtp_port = _available_udp_port()
        while rtp_port == sip_port:
            rtp_port = _available_udp_port()

        self.engineering = BroadcastEngineeringSettings.objects.create(
            broadcast_test_mode=False,
            pjsip_executable_path=str(self.executable_path),
            pjsip_local_ip="127.0.0.1",
            pjsip_advertise_ip=None,
            pjsip_local_sip_port_base=sip_port,
            pjsip_local_rtp_port_base=rtp_port,
            pjsip_port_step=2,
            pjsip_audio_gain_percent=100,
        )
        self.speaker = SpeakerDevice.objects.create(
            speaker_code="LAB-SPK-001",
            name="Lab Speaker",
            ip_address="192.168.6.120",
            port=5060,
            protocol=SpeakerDevice.PROTOCOL_SIP,
            username="voip",
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
            deployment_state=SpeakerDevice.DEPLOYMENT_DEPLOYED,
        )
        self.audio = AudioFile.objects.create(
            audio_code="TEST-004",
            name="Lab Test Audio",
            audio_type=AudioFile.AUDIO_TYPE_TEST,
            file=SimpleUploadedFile("test.wav", _wav_bytes()),
            is_active=True,
        )

    def _prepare(self, **overrides):
        arguments = {
            "speaker_code": self.speaker.speaker_code,
            "audio_code": self.audio.audio_code,
            "log_path": Path(self.temporary_directory.name) / "preflight.log",
            "check_ports": False,
        }
        arguments.update(overrides)
        return prepare_pjsip_readiness(**arguments)

    def test_database_values_override_settings_and_advertise_uses_db_local_ip(self):
        with override_settings(
            PJSIP_LOCAL_IP="192.0.2.10",
            PJSIP_ADVERTISE_IP="192.0.2.11",
            PJSIP_LOCAL_SIP_PORT_BASE=62000,
            PJSIP_LOCAL_RTP_PORT_BASE=42000,
            PJSIP_PORT_STEP=10,
            PJSIP_AUDIO_GAIN_PERCENT=80,
        ):
            runtime_config = get_broadcast_runtime_config()

        self.assertEqual(runtime_config.pjsip_local_ip, "127.0.0.1")
        self.assertEqual(runtime_config.pjsip_advertise_ip, "127.0.0.1")
        self.assertEqual(
            runtime_config.pjsip_executable_path,
            str(self.executable_path),
        )
        self.assertEqual(
            runtime_config.pjsip_local_sip_port_base,
            self.engineering.pjsip_local_sip_port_base,
        )
        self.assertEqual(
            runtime_config.pjsip_local_rtp_port_base,
            self.engineering.pjsip_local_rtp_port_base,
        )
        self.assertEqual(runtime_config.pjsip_port_step, 2)
        self.assertEqual(runtime_config.pjsip_audio_gain_percent, 100.0)
        self.assertEqual(runtime_config.source, "broadcast-engineering-settings")

    def test_empty_local_ip_fails(self):
        self.engineering.pjsip_local_ip = None
        self.engineering.save(update_fields=["pjsip_local_ip"])

        with self.assertRaisesRegex(PjsipPreflightError, "local IP is required"):
            self._prepare()

    def test_missing_pjsua_fails(self):
        self.engineering.pjsip_executable_path = str(
            Path(self.temporary_directory.name) / "missing.exe"
        )
        self.engineering.save(update_fields=["pjsip_executable_path"])

        with self.assertRaisesRegex(
            PjsipPreflightError,
            "PJSUA executable not found",
        ):
            self._prepare()

    def test_inactive_speaker_fails(self):
        self.speaker.is_active = False
        self.speaker.save(update_fields=["is_active"])

        with self.assertRaisesRegex(PjsipPreflightError, "is inactive"):
            self._prepare()

    def test_offline_speaker_fails(self):
        self.speaker.status = SpeakerDevice.STATUS_OFFLINE
        self.speaker.save(update_fields=["status"])

        with self.assertRaisesRegex(PjsipPreflightError, "must be online"):
            self._prepare()

    def test_non_deployed_speaker_fails(self):
        self.speaker.deployment_state = SpeakerDevice.DEPLOYMENT_PLANNED
        self.speaker.save(update_fields=["deployment_state"])

        with self.assertRaisesRegex(PjsipPreflightError, "deployed state"):
            self._prepare()

    def test_inactive_and_missing_audio_fail(self):
        self.audio.is_active = False
        self.audio.save(update_fields=["is_active"])
        with self.assertRaisesRegex(PjsipPreflightError, "is inactive"):
            self._prepare()

        self.audio.delete()
        with self.assertRaisesRegex(PjsipPreflightError, "AudioFile not found"):
            self._prepare()

    def test_lab_speaker_resolves_expected_uri(self):
        self.assertEqual(
            self.speaker.resolved_sip_uri,
            "sip:voip@192.168.6.120:5060",
        )
        readiness = self._prepare()
        self.assertEqual(
            readiness.plan.target_uri,
            "sip:voip@192.168.6.120:5060",
        )

    def test_preflight_reports_effective_configuration_and_pass(self):
        output = StringIO()

        call_command(
            "pjsip_preflight",
            speaker=self.speaker.speaker_code,
            audio=self.audio.audio_code,
            stdout=output,
        )

        report = output.getvalue()
        self.assertIn("Environment: development", report)
        self.assertIn(
            "Config Source: broadcast-engineering-settings",
            report,
        )
        self.assertIn("Operational Backend: pjsip", report)
        self.assertIn("Speaker Code: LAB-SPK-001", report)
        self.assertIn("Speaker IP: 192.168.6.120", report)
        self.assertIn(
            "Resolved SIP URI: sip:voip@192.168.6.120:5060",
            report,
        )
        self.assertIn("Audio Code: TEST-004", report)
        self.assertIn("Overall: PREFLIGHT PASS", report)

    @override_settings(KRTC_PRODUCTION=True, BROADCAST_PLAYBACK_MODE="simulation")
    def test_production_backend_is_pjsip(self):
        self.assertEqual(
            get_broadcast_runtime_config().operational_backend,
            "pjsip",
        )

    @override_settings(KRTC_PRODUCTION=False, BROADCAST_PLAYBACK_MODE="simulation")
    def test_development_simulation_remains_available(self):
        self.engineering.broadcast_test_mode = None
        self.engineering.save(
            update_fields=["broadcast_test_mode", "updated_at"]
        )

        self.assertEqual(
            get_broadcast_runtime_config().operational_backend,
            "simulation",
        )

    def test_gain_outside_engineering_range_fails(self):
        self.engineering.pjsip_audio_gain_percent = 201
        self.engineering.save(update_fields=["pjsip_audio_gain_percent"])

        with self.assertRaisesRegex(PjsipPreflightError, "between 0 and 200"):
            self._prepare()
