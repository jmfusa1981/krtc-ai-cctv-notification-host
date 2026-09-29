from __future__ import annotations

from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from apps.ai_bridge.apps import AiBridgeConfig
from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.websocket_client import InferenceWebSocketReceiver
from apps.settings_app.forms import InferenceHostForm


def _form_data(*, base_url: str, websocket_url: str = "") -> dict:
    return {
        "host_code": "INF-WS-001",
        "name": "Inference WebSocket test host",
        "station_code": "KRTC-ST-001",
        "host_type": "physical",
        "ip_address": "192.168.6.20",
        "port": 8000,
        "base_url": base_url,
        "configuration_url": "",
        "health_url": "",
        "events_url": "",
        "websocket_url": websocket_url,
        "websocket_auth_mode": "none",
        "timeout_seconds": 10,
        "is_active": "on",
        "description": "",
    }


class InferenceWebSocketFormTests(TestCase):
    def test_http_base_url_generates_ws_default(self) -> None:
        form = InferenceHostForm(
            data=_form_data(base_url="http://192.168.6.20:8000")
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["websocket_url"],
            "ws://192.168.6.20:8000/ws/alerts",
        )

    def test_https_base_url_still_generates_ws_default(self) -> None:
        form = InferenceHostForm(
            data=_form_data(base_url="https://inference.example:8443/")
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["websocket_url"],
            "ws://inference.example:8443/ws/alerts",
        )

    def test_explicit_ws_url_is_accepted_and_preserved(self) -> None:
        explicit_url = "ws://192.168.6.21:9000/custom/alerts"
        form = InferenceHostForm(
            data=_form_data(
                base_url="http://192.168.6.20:8000",
                websocket_url=explicit_url,
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["websocket_url"], explicit_url)

    def test_explicit_wss_url_is_rejected_with_clear_error(self) -> None:
        form = InferenceHostForm(
            data=_form_data(
                base_url="https://inference.example:8443",
                websocket_url="wss://inference.example:8443/custom/alerts",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "目前系統僅支援 ws:// WebSocket 連線。",
            form.errors["websocket_url"],
        )

    def test_explicit_http_url_is_rejected(self) -> None:
        form = InferenceHostForm(
            data=_form_data(
                base_url="http://192.168.6.20:8000",
                websocket_url="http://192.168.6.20:8000/ws/alerts",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("websocket_url", form.errors)

    def test_explicit_https_url_is_rejected(self) -> None:
        form = InferenceHostForm(
            data=_form_data(
                base_url="http://192.168.6.20:8000",
                websocket_url="https://192.168.6.20:8000/ws/alerts",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("websocket_url", form.errors)

    def test_malformed_websocket_url_is_rejected(self) -> None:
        form = InferenceHostForm(
            data=_form_data(
                base_url="http://192.168.6.20:8000",
                websocket_url="not-a-websocket-url",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("websocket_url", form.errors)

    def test_websocket_url_without_host_is_rejected(self) -> None:
        form = InferenceHostForm(
            data=_form_data(
                base_url="http://192.168.6.20:8000",
                websocket_url="ws:///ws/alerts",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("websocket_url", form.errors)

    def test_websocket_url_with_invalid_port_is_rejected(self) -> None:
        form = InferenceHostForm(
            data=_form_data(
                base_url="http://192.168.6.20:8000",
                websocket_url="ws://192.168.6.20:99999/ws/alerts",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("websocket_url", form.errors)

    def test_websocket_url_with_fragment_is_rejected(self) -> None:
        form = InferenceHostForm(
            data=_form_data(
                base_url="http://192.168.6.20:8000",
                websocket_url="ws://192.168.6.20:8000/ws/alerts#fragment",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("websocket_url", form.errors)


class InferenceWebSocketRuntimeTests(TestCase):
    def _host(self, *, base_url: str, websocket_url: str = "") -> InferenceHost:
        return InferenceHost(
            host_code="INF-WS-RUNTIME",
            name="Runtime host",
            base_url=base_url,
            websocket_url=websocket_url,
        )

    def test_receiver_fallback_always_uses_ws(self) -> None:
        for base_url in (
            "http://192.168.6.20:8000",
            "https://inference.example:8443",
        ):
            with self.subTest(base_url=base_url):
                receiver = InferenceWebSocketReceiver(
                    inference_host=self._host(base_url=base_url)
                )

                self.assertTrue(receiver.ws_url.startswith("ws://"))
                self.assertFalse(receiver.ws_url.startswith("wss://"))

    def test_receiver_preserves_valid_explicit_url(self) -> None:
        explicit_url = "ws://gateway.example/custom/alerts"
        receiver = InferenceWebSocketReceiver(
            inference_host=self._host(
                base_url="http://192.168.6.20:8000",
                websocket_url=explicit_url,
            )
        )

        self.assertEqual(receiver.ws_url, explicit_url)

    def test_receiver_rejects_stored_wss_url(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "目前系統僅支援 ws:// WebSocket 連線。",
        ):
            InferenceWebSocketReceiver(
                inference_host=self._host(
                    base_url="http://192.168.6.20:8000",
                    websocket_url="wss://gateway.example/ws/alerts",
                )
            )

    def test_receiver_rejects_malformed_explicit_url(self) -> None:
        with self.assertRaises(ValueError):
            InferenceWebSocketReceiver(
                inference_host=self._host(
                    base_url="http://192.168.6.20:8000",
                    websocket_url="192.168.6.20:8000/ws/alerts",
                )
            )


class InferenceWebSocketProductionDefaultsTests(SimpleTestCase):
    def test_websocket_autostart_default_is_enabled(self) -> None:
        self.assertTrue(settings.INFERENCE_WS_AUTOSTART)

    @override_settings(
        INFERENCE_POLL_AUTOSTART=False,
        ZONE_COUNT_POLL_AUTOSTART=False,
        INFERENCE_WS_AUTOSTART=True,
    )
    @mock.patch("apps.ai_bridge.background_polling.start_inference_polling")
    @mock.patch("apps.ai_bridge.background_websocket.start_inference_websocket_listener")
    @mock.patch.object(AiBridgeConfig, "_must_skip_autostart", return_value=False)
    def test_websocket_autostart_does_not_enable_rest_poller(
        self,
        _skip: mock.Mock,
        start_websocket: mock.Mock,
        start_poller: mock.Mock,
    ) -> None:
        config = AiBridgeConfig(
            "apps.ai_bridge",
            __import__("apps.ai_bridge", fromlist=["*"]),
        )

        config.ready()

        start_websocket.assert_called_once_with()
        start_poller.assert_not_called()
