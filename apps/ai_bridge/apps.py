from __future__ import annotations

import os
import sys

from django.apps import AppConfig
from django.conf import settings


class AiBridgeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai_bridge"

    def ready(self) -> None:
        if self._must_skip_autostart():
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

    @staticmethod
    def _must_skip_autostart() -> bool:
        argv = {arg.lower() for arg in sys.argv[1:]}
        blocked_commands = {
            "check",
            "collectstatic",
            "makemigrations",
            "migrate",
            "shell",
            "test",
            "poll_inference_hosts",
            "poll_zone_counts",
            "run_inference_listener",
            "run_occ_sync_service",
            "sync_occ_once",
        }
        if argv.intersection(blocked_commands):
            return True

        # Django's development autoreloader launches a parent process and a
        # child process. Start background work only in the serving child.
        if "runserver" in argv and os.environ.get("RUN_MAIN") != "true":
            return True

        return False
