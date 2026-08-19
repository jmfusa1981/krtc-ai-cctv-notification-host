import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from apps.notifications.scheduler_process import (
    SchedulerAlreadyRunning,
    SchedulerProcessLock,
    write_scheduler_status,
)


class SchedulerProcessTests(SimpleTestCase):
    def test_second_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "scheduler.lock"
            with SchedulerProcessLock(lock_path):
                with self.assertRaises(SchedulerAlreadyRunning):
                    SchedulerProcessLock(lock_path).acquire()

    def test_status_file_is_valid_utf8_json(self):
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "status.json"
            write_scheduler_status(
                status_path,
                state="running",
                last_error="測試訊息",
            )
            payload = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["state"], "running")
        self.assertEqual(payload["last_error"], "測試訊息")
        self.assertIn("pid", payload)
        self.assertIn("updated_at", payload)
