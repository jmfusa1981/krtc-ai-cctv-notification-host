from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.ai_bridge.apps import AiBridgeConfig
import apps.ai_bridge.background_polling as background_polling


class InferencePollingAutostartTests(SimpleTestCase):
    def setUp(self) -> None:
        background_polling._started = False

    def tearDown(self) -> None:
        background_polling._started = False

    @mock.patch("apps.ai_bridge.background_polling.threading.Thread")
    def test_start_is_idempotent(self, thread_class: mock.Mock) -> None:
        thread = thread_class.return_value

        first = background_polling.start_inference_polling()
        second = background_polling.start_inference_polling()

        self.assertTrue(first)
        self.assertFalse(second)
        thread_class.assert_called_once()
        thread.start.assert_called_once()

    @override_settings(INFERENCE_POLL_AUTOSTART=True, INFERENCE_WS_AUTOSTART=False)
    @mock.patch("apps.ai_bridge.background_polling.start_inference_polling")
    @mock.patch.object(AiBridgeConfig, "_must_skip_autostart", return_value=False)
    def test_ready_starts_polling_when_enabled(
        self,
        _skip: mock.Mock,
        start_polling: mock.Mock,
    ) -> None:
        config = AiBridgeConfig("apps.ai_bridge", __import__("apps.ai_bridge", fromlist=["*"]))
        config.ready()
        start_polling.assert_called_once_with()

    @override_settings(INFERENCE_POLL_AUTOSTART=False, INFERENCE_WS_AUTOSTART=False)
    @mock.patch("apps.ai_bridge.background_polling.start_inference_polling")
    def test_ready_does_not_start_polling_when_disabled(
        self,
        start_polling: mock.Mock,
    ) -> None:
        config = AiBridgeConfig("apps.ai_bridge", __import__("apps.ai_bridge", fromlist=["*"]))
        config.ready()
        start_polling.assert_not_called()
