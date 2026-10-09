import json
import tempfile
import uuid
from datetime import datetime, timezone as datetime_timezone
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from apps.cameras.models import Camera
from apps.station_api.integration.client import OccError, OccHttpClient, OccResult
from apps.station_api.integration.config import OccIntegrationConfig
from apps.station_api.integration.heartbeat import (
    HeartbeatSender,
    build_heartbeat_payload,
)
from apps.station_api.integration.signing import (
    body_sha256,
    build_signed_headers,
    canonical_string,
    generate_request_id,
    sign_canonical,
)


class FakeResponse:
    """提供 HTTP client 測試所需的最小 response 介面。"""

    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


def integration_config(secret="test-secret"):
    """建立不依賴全域 settings 的固定測試設定。"""

    return OccIntegrationConfig(
        enabled=True,
        base_url="http://occ.example:8000",
        station_code="KRTC-ST-TEST",
        host_code="PAO-TEST-001",
        shared_secret=secret,
        connect_timeout=3,
        read_timeout=5,
        heartbeat_interval=10,
    )


class OccSigningTests(SimpleTestCase):
    """驗證 HMAC canonical input 與 headers 契約。"""

    def test_deterministic_signature_and_body_hash(self):
        body = b'{"a":1}'
        digest = body_sha256(body)
        canonical = canonical_string(
            "POST",
            "/api/v1/heartbeat/",
            "2026-10-08T00:00:00Z",
            "abc123",
            digest,
        )

        self.assertEqual(
            digest,
            "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862",
        )
        self.assertEqual(
            sign_canonical("test-secret", canonical),
            "28510deb01def2e23ee2e4f7eaf2ad21e20c858e8f28e24ffbe4397e61e3d248",
        )

    def test_request_id_generation_returns_uuid(self):
        request_id = generate_request_id()
        self.assertEqual(str(uuid.UUID(request_id)), request_id)

    def test_headers_include_timestamp_nonce_and_identity(self):
        headers = build_signed_headers(
            method="POST",
            path="/api/v1/heartbeat/",
            body=b"{}",
            station_code="KRTC-ST-TEST",
            host_code="PAO-TEST-001",
            shared_secret="test-secret",
            timestamp="2026-10-08T00:00:00Z",
            nonce="fixed-nonce",
        )

        self.assertEqual(headers["X-KRTC-Timestamp"], "2026-10-08T00:00:00Z")
        self.assertEqual(headers["X-KRTC-Nonce"], "fixed-nonce")
        self.assertEqual(headers["X-KRTC-Station"], "KRTC-ST-TEST")
        self.assertEqual(headers["X-KRTC-Host"], "PAO-TEST-001")

    def test_body_and_path_changes_change_signature(self):
        common = {
            "method": "POST",
            "station_code": "KRTC-ST-TEST",
            "host_code": "PAO-TEST-001",
            "shared_secret": "test-secret",
            "timestamp": "2026-10-08T00:00:00Z",
            "nonce": "fixed-nonce",
        }
        first = build_signed_headers(
            path="/api/v1/heartbeat/", body=b'{"a":1}', **common
        )
        changed_body = build_signed_headers(
            path="/api/v1/heartbeat/", body=b'{"a":2}', **common
        )
        changed_path = build_signed_headers(
            path="/api/v1/other/", body=b'{"a":1}', **common
        )

        self.assertNotEqual(
            first["X-KRTC-Signature"], changed_body["X-KRTC-Signature"]
        )
        self.assertNotEqual(
            first["X-KRTC-Signature"], changed_path["X-KRTC-Signature"]
        )


class OccHttpClientTests(SimpleTestCase):
    """驗證 ACK 與 retry classification，不建立真實網路連線。"""

    def setUp(self):
        self.session = Mock()
        self.client = OccHttpClient(
            config=integration_config(),
            session=self.session,
        )
        self.payload = {"request_id": "request-123", "value": "測試"}

    def test_success_ack_and_utf8_timeout_contract(self):
        self.session.post.return_value = FakeResponse(
            200,
            {
                "success": True,
                "request_id": "request-123",
                "received_at": "2026-10-08T00:00:00Z",
                "result": {"accepted": True},
            },
        )

        result = self.client.post_json("/api/v1/heartbeat/", self.payload)

        self.assertTrue(result.success)
        self.assertEqual(result.result, {"accepted": True})
        kwargs = self.session.post.call_args.kwargs
        self.assertEqual(kwargs["timeout"], (3, 5))
        self.assertEqual(
            kwargs["headers"]["Content-Type"],
            "application/json; charset=utf-8",
        )
        self.assertIn("測試".encode("utf-8"), kwargs["data"])

    def test_timeout_is_retryable(self):
        self.session.post.side_effect = requests.ReadTimeout()
        result = self.client.post_json("/api/v1/heartbeat/", self.payload)
        self.assertFalse(result.success)
        self.assertTrue(result.retryable)
        self.assertEqual(result.error.code, "read_timeout")

    def test_retryable_http_statuses(self):
        for status_code in (429, 500, 503):
            with self.subTest(status_code=status_code):
                self.session.post.return_value = FakeResponse(status_code, {})
                result = self.client.post_json(
                    "/api/v1/heartbeat/", self.payload
                )
                self.assertTrue(result.retryable)

    def test_non_retryable_http_statuses(self):
        for status_code in (400, 401, 403, 404, 422):
            with self.subTest(status_code=status_code):
                self.session.post.return_value = FakeResponse(status_code, {})
                result = self.client.post_json(
                    "/api/v1/heartbeat/", self.payload
                )
                self.assertFalse(result.retryable)

    def test_malformed_json_is_failure(self):
        self.session.post.return_value = FakeResponse(
            200,
            json_error=ValueError("invalid"),
        )
        result = self.client.post_json("/api/v1/heartbeat/", self.payload)
        self.assertEqual(result.error.code, "malformed_json")

    def test_request_id_mismatch_is_failure(self):
        self.session.post.return_value = FakeResponse(
            200,
            {
                "success": True,
                "request_id": "different-request",
                "received_at": "2026-10-08T00:00:00Z",
                "result": {},
            },
        )
        result = self.client.post_json("/api/v1/heartbeat/", self.payload)
        self.assertEqual(result.error.code, "request_id_mismatch")

    def test_received_at_without_timezone_is_failure(self):
        self.session.post.return_value = FakeResponse(
            200,
            {
                "success": True,
                "request_id": "request-123",
                "received_at": "2026-10-08T00:00:00",
                "result": {},
            },
        )
        result = self.client.post_json("/api/v1/heartbeat/", self.payload)
        self.assertEqual(result.error.code, "invalid_received_at")


@override_settings(
    KRTC_APP_VERSION="PAO Notification Host V6.8.0-TEST",
    KRTC_OCC_SYNC_ENABLED=True,
    KRTC_OCC_BASE_URL="http://occ.example:8000",
    KRTC_OCC_SHARED_SECRET="super-secret-value",
    KRTC_STATION_CODE="KRTC-ST-TEST",
    KRTC_NOTIFICATION_HOST_CODE="PAO-TEST-001",
    KRTC_OCC_CONNECT_TIMEOUT_SECONDS=3,
    KRTC_OCC_READ_TIMEOUT_SECONDS=5,
    KRTC_HEARTBEAT_INTERVAL=10,
)
class OccHeartbeatAndHealthTests(TestCase):
    """驗證 heartbeat 使用 canonical media truth 且 API 不洩漏密鑰。"""

    def setUp(self):
        self.camera = Camera.objects.create(
            camera_code="CAM-005",
            name="Camera 5",
            area="A",
            status="offline",
            is_active=True,
        )

    @patch(
        "apps.station_api.integration.heartbeat.collect_mediamtx_path_readiness"
    )
    def test_heartbeat_common_fields_and_canonical_camera_summary(
        self,
        collect_readiness,
    ):
        collect_readiness.return_value = {
            "reachable": True,
            "path_details": {
                "CAM-005": {
                    "media_ready": True,
                    "media_state": "media_ready",
                }
            },
        }
        payload = build_heartbeat_payload(
            integration_config("super-secret-value"),
            request_id="00000000-0000-4000-8000-000000000001",
            now=datetime(2026, 10, 8, tzinfo=datetime_timezone.utc),
            uptime_seconds=123,
        )

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["station_code"], "KRTC-ST-TEST")
        self.assertEqual(payload["host_code"], "PAO-TEST-001")
        self.assertEqual(payload["application_version"], settings.KRTC_APP_VERSION)
        self.assertEqual(payload["uptime_seconds"], 123)
        self.assertEqual(
            str(uuid.UUID(payload["request_id"])),
            "00000000-0000-4000-8000-000000000001",
        )
        self.assertEqual(payload["camera_summary"]["media_available"], 1)
        self.assertEqual(payload["camera_summary"]["media_unavailable"], 0)
        self.assertNotIn("secret", json.dumps(payload).lower())

    def test_health_api_shape_and_secret_absence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            status_path = Path(temporary_directory) / "occ-status.json"
            with override_settings(KRTC_OCC_SERVICE_STATUS_PATH=status_path):
                response = self.client.get("/api/v1/health/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["station_code"], "KRTC-ST-TEST")
        self.assertEqual(payload["host_code"], "PAO-TEST-001")
        self.assertEqual(payload["service"]["status"], "ok")
        self.assertTrue(payload["integration"]["configured"])
        self.assertNotIn("super-secret-value", response.content.decode("utf-8"))

    @patch(
        "apps.station_api.integration.heartbeat.collect_mediamtx_path_readiness"
    )
    def test_runtime_state_marks_http_failure_reachable_and_redacts_secret(
        self,
        collect_readiness,
    ):
        collect_readiness.return_value = {
            "reachable": False,
            "path_details": {},
        }
        client = Mock()
        client.post_json.return_value = OccResult(
            success=False,
            request_id="request-123",
            http_status=401,
            error=OccError(
                code="authentication_failed",
                message="secret=super-secret-value",
                retryable=False,
                http_status=401,
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            status_path = Path(temporary_directory) / "occ-status.json"
            with override_settings(KRTC_OCC_SERVICE_STATUS_PATH=status_path):
                result = HeartbeatSender(
                    config=integration_config("super-secret-value"),
                    client=client,
                ).send()
                state = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertFalse(result.success)
        self.assertTrue(state["occ_reachable"])
        self.assertEqual(state["last_error_code"], "authentication_failed")
        self.assertNotIn("super-secret-value", json.dumps(state))

    @patch(
        "apps.station_api.integration.heartbeat.collect_mediamtx_path_readiness"
    )
    def test_diagnostics_never_displays_secret(self, collect_readiness):
        collect_readiness.return_value = {
            "reachable": False,
            "path_details": {},
        }
        output = StringIO()
        with tempfile.TemporaryDirectory() as temporary_directory:
            status_path = Path(temporary_directory) / "occ-status.json"
            with override_settings(KRTC_OCC_SERVICE_STATUS_PATH=status_path):
                call_command(
                    "diagnose_occ_integration",
                    "--dry-run",
                    stdout=output,
                )

        value = output.getvalue()
        self.assertNotIn("super-secret-value", value)
        self.assertNotIn("X-KRTC-Signature\": \"", value)
        self.assertIn('"signature_header_present": true', value)

    @patch("apps.station_api.management.commands.sync_occ_once.HeartbeatSender")
    def test_sync_occ_once_heartbeat_uses_hmac_sender_without_legacy_token(
        self,
        sender_class,
    ):
        sender_class.return_value.send.return_value = OccResult(
            success=True,
            request_id="request-123",
            http_status=200,
            received_at="2026-10-08T00:00:00Z",
            result={"accepted": True},
        )
        output = StringIO()
        with override_settings(
            KRTC_OCC_SYNC_ENABLED=False,
            KRTC_OCC_API_TOKEN="",
        ):
            call_command(
                "sync_occ_once",
                "--kind",
                "heartbeat",
                "--force",
                stdout=output,
            )

        sender_class.return_value.send.assert_called_once_with()
        self.assertIn("heartbeat:", output.getvalue())
