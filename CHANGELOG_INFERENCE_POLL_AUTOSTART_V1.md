# KRTC V5 Inference Poll Autostart V1

## Changes

- Starts multi-inference-host polling automatically with the Django web process.
- Keeps the existing 5-second health/event polling behavior.
- Prevents duplicate startup in Django runserver's autoreloader parent process.
- Skips autostart for management commands such as migrate, test, shell, and check.
- Adds an in-process singleton guard.
- Adds environment-variable controls and regression tests.

## Default settings

- `INFERENCE_POLL_AUTOSTART=True`
- `INFERENCE_POLL_INTERVAL_SECONDS=5`
- `INFERENCE_POLL_EVENT_LIMIT=100`
- `INFERENCE_POLL_EVENT_OFFSET=0`
- `INFERENCE_POLL_STARTUP_DELAY_SECONDS=2`

After installation, stop the separate `python manage.py poll_inference_hosts` terminal. Starting Django is sufficient.
