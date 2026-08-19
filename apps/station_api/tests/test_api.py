import json

from django.test import TestCase, override_settings

from apps.ai_bridge.models import AIModel, InferenceHost


@override_settings(KRTC_OCC_API_TOKEN="occ-secret", KRTC_STATION_CODE="TEST-STATION", KRTC_NOTIFICATION_HOST_CODE="PAO-TEST-001")
class StationApiTests(TestCase):
    def setUp(self):
        self.auth = {"HTTP_AUTHORIZATION": "Bearer occ-secret"}
        self.host = InferenceHost.objects.create(host_code="INF-TEST-001", name="Inference", base_url="http://192.168.6.25:9000", is_active=True)
        self.model = AIModel.objects.create(name="Fall V2", model_code="fall-detection-v2", is_active=True)

    def test_health_has_timezone(self):
        response = self.client.get("/api/v1/health/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("+08:00", response.json()["time"])

    def test_invalid_token_is_rejected(self):
        self.assertEqual(self.client.get("/api/v1/status/", HTTP_AUTHORIZATION="Bearer wrong").status_code, 401)

    def test_legal_configuration_is_applied(self):
        payload = {"station_code": "TEST-STATION", "notification_host_code": "PAO-TEST-001", "inference_host_code": "INF-TEST-001", "model_code": "fall-detection-v2", "config_version": "2026.08.01.001", "operator_code": "Skynet"}
        response = self.client.post("/api/v1/configuration/apply/", data=json.dumps(payload), content_type="application/json", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "applied")

    def test_unknown_model_is_rejected_and_audited(self):
        payload = {"station_code": "TEST-STATION", "notification_host_code": "PAO-TEST-001", "inference_host_code": "INF-TEST-001", "model_code": "unknown", "config_version": "2026.08.01.002", "operator_code": "Skynet"}
        response = self.client.post("/api/v1/configuration/apply/", data=json.dumps(payload), content_type="application/json", **self.auth)
        self.assertEqual(response.status_code, 422)
