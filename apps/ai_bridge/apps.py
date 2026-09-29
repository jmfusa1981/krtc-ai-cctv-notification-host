from __future__ import annotations

from django.apps import AppConfig
from django.conf import settings

from config.runtime_policy import should_start_web_background_services


class AiBridgeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai_bridge"

    def ready(self) -> None:
        """
        Start AI bridge background workers only inside the actual web runtime.

        Management commands, tests, and dedicated service processes must not
        automatically start inference polling, zone-count polling, or the
        inference WebSocket listener.
        """
        if not should_start_web_background_services():
            return

        if getattr(settings, "INFERENCE_POLL_AUTOSTART", False):
            from apps.ai_bridge.background_polling import start_inference_polling

            start_inference_polling()

        if getattr(settings, "ZONE_COUNT_POLL_AUTOSTART", True):
            from apps.ai_bridge.background_zone_counts import start_zone_count_polling

            start_zone_count_polling()

        if getattr(settings, "INFERENCE_WS_AUTOSTART", False):
            from apps.ai_bridge.background_websocket import (
                start_inference_websocket_listener,
            )

            start_inference_websocket_listener()