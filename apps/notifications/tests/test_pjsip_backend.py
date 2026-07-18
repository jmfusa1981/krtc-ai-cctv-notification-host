import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.notifications.backends.pjsip import (
    PjsipPlaybackPlan,
    execute_pjsip_playback_plan,
)


class _FakeStdin:
    def __init__(self):
        self.writes = []
        self.flushed = False

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        self.flushed = True


class _TimeoutProcess:
    def __init__(self, require_kill=False):
        self.stdin = _FakeStdin()
        self.returncode = None
        self.require_kill = require_kill
        self.wait_calls = 0
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_calls += 1

        if self.wait_calls == 1:
            raise subprocess.TimeoutExpired("pjsua.exe", timeout)

        if self.wait_calls == 2 and self.require_kill:
            raise subprocess.TimeoutExpired("pjsua.exe", timeout)

        self.returncode = -9 if self.killed else -15
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class PjsipTimeoutCleanupTests(SimpleTestCase):
    def _build_plan(self, log_path):
        return PjsipPlaybackPlan(
            executable_path=Path("pjsua.exe"),
            audio_path=Path("testing.wav"),
            log_path=log_path,
            target_uri="sip:120@192.168.6.120:5060",
            local_ip="192.168.6.26",
            advertise_ip="192.168.6.26",
            local_sip_port=64882,
            local_rtp_port=4004,
            audio_duration_seconds=0.0,
            command=("pjsua.exe",),
        )

    def _execute_with_fake_process(self, process, log_path):
        plan = self._build_plan(log_path)

        with (
            patch(
                "apps.notifications.backends.pjsip.subprocess.Popen",
                return_value=process,
            ),
            patch(
                "apps.notifications.backends.pjsip.time.monotonic",
                side_effect=[0.0, 0.0, 3.0],
            ),
            patch("apps.notifications.backends.pjsip.time.sleep"),
        ):
            return execute_pjsip_playback_plan(
                plan,
                extra_wait_seconds=2.0,
            )

    def test_timeout_requests_hangup_then_terminates_process(self):
        with TemporaryDirectory() as temp_dir:
            process = _TimeoutProcess(require_kill=False)
            result = self._execute_with_fake_process(
                process,
                Path(temp_dir) / "timeout.log",
            )

        self.assertFalse(result.success)
        self.assertEqual(process.stdin.writes, ["h\nq\n"])
        self.assertTrue(process.stdin.flushed)
        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)
        self.assertIsNotNone(process.returncode)

    def test_timeout_kills_process_when_terminate_does_not_finish(self):
        with TemporaryDirectory() as temp_dir:
            process = _TimeoutProcess(require_kill=True)
            result = self._execute_with_fake_process(
                process,
                Path(temp_dir) / "forced_kill.log",
            )

        self.assertFalse(result.success)
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertIsNotNone(process.returncode)
