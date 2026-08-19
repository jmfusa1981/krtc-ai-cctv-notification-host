from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.ai_bridge.apps import AiBridgeConfig
import apps.ai_bridge.background_websocket as background_websocket


class InferenceWebSocketAutostartTests(SimpleTestCase):
    def setUp(self) -> None:
        background_websocket._started = False

    def tearDown(self) -> None:
        background_websocket._started = False

    @mock.patch("apps.ai_bridge.background_websocket.threading.Thread")
    def test_start_is_idempotent(self, thread_class: mock.Mock) -> None:
        thread = thread_class.return_value

        first = background_websocket.start_inference_websocket_listener()
        second = background_websocket.start_inference_websocket_listener()

        self.assertTrue(first)
        self.assertFalse(second)
        thread_class.assert_called_once()
        thread.start.assert_called_once()

    @override_settings(
        INFERENCE_POLL_AUTOSTART=False,
        INFERENCE_WS_AUTOSTART=True,
    )
    @mock.patch("apps.ai_bridge.background_websocket.start_inference_websocket_listener")
    @mock.patch.object(AiBridgeConfig, "_must_skip_autostart", return_value=False)
    def test_ready_starts_websocket_when_enabled(
        self,
        _skip: mock.Mock,
        start_listener: mock.Mock,
    ) -> None:
        config = AiBridgeConfig(
            "apps.ai_bridge",
            __import__("apps.ai_bridge", fromlist=["*"]),
        )
        config.ready()
        start_listener.assert_called_once_with()

    @override_settings(
        INFERENCE_POLL_AUTOSTART=False,
        INFERENCE_WS_AUTOSTART=False,
    )
    @mock.patch("apps.ai_bridge.background_websocket.start_inference_websocket_listener")
    def test_ready_does_not_start_websocket_when_disabled(
        self,
        start_listener: mock.Mock,
    ) -> None:
        config = AiBridgeConfig(
            "apps.ai_bridge",
            __import__("apps.ai_bridge", fromlist=["*"]),
        )
        config.ready()
        start_listener.assert_not_called()
