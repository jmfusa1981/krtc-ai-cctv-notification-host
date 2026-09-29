from __future__ import annotations

import os
import sys

from django.conf import settings


DEDICATED_SERVICE_COMMANDS = {
    "run_occ_sync_service",
    "run_event_recording_service",
    "run_broadcast_scheduler",
    "run_pao_service_watchdog",
    "poll_inference_hosts",
    "poll_zone_counts",
    "run_inference_listener",
}


def current_management_command() -> str:
    """
    Return the Django management command when the current process was started
    through manage.py.

    Examples:
        python manage.py runserver       -> "runserver"
        python manage.py migrate         -> "migrate"
        python manage.py createsuperuser -> "createsuperuser"
    """
    argv = [str(item).strip() for item in sys.argv]

    for index, item in enumerate(argv):
        if item.lower().endswith("manage.py") and index + 1 < len(argv):
            return argv[index + 1].lower()

    return ""


def is_dedicated_service_runtime() -> bool:
    """
    True when this process is running one of the dedicated KRTC worker/service
    management commands.
    """
    return current_management_command() in DEDICATED_SERVICE_COMMANDS


def is_django_management_runtime() -> bool:
    """
    True for manage.py commands except the web-serving runserver command.

    Dedicated KRTC services are also management commands, but they must remain
    isolated from web-process background autostart.
    """
    command = current_management_command()

    if not command:
        return False

    return command != "runserver"


def is_runserver_worker() -> bool:
    """
    True only for the Django development web-serving process.

    Django runserver normally launches an autoreloader parent plus the actual
    serving child. Background workers must start only in the serving child.
    """
    if current_management_command() != "runserver":
        return False

    argv = {str(item).lower() for item in sys.argv}

    if "--noreload" in argv:
        return True

    return os.environ.get("RUN_MAIN", "").lower() == "true"


def is_waitress_web_runtime() -> bool:
    """
    True only for the production Waitress web process.
    """
    if not getattr(settings, "KRTC_PRODUCTION", False):
        return False

    return any("waitress" in str(item).lower() for item in sys.argv)


def should_start_web_background_services() -> bool:
    """
    Central V6.8 runtime gate.

    Web-process background services may start only inside:
      - the actual Django runserver serving process, or
      - the production Waitress web process.

    They must not start during:
      - migrate / makemigrations
      - check / test
      - shell
      - createsuperuser / changepassword
      - collectstatic
      - dedicated OCC / recording / scheduler workers
      - arbitrary management commands
    """
    if is_dedicated_service_runtime():
        return False

    if is_django_management_runtime():
        return False

    return is_runserver_worker() or is_waitress_web_runtime()


def runtime_mode() -> str:
    """
    Human-readable runtime classification for diagnostics and tests.
    """
    command = current_management_command()

    if is_dedicated_service_runtime():
        return f"dedicated-service:{command}"

    if is_runserver_worker():
        return "web:runserver"

    if is_waitress_web_runtime():
        return "web:waitress"

    if command:
        return f"management:{command}"

    return "other"