import inspect
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase

from apps.cameras import mosaic, stream_pool


def wait_until(predicate, timeout=2.0):
    """在測試期限內輪詢非同步狀態，避免固定長時間sleep。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


class ControlledCapture:
    """模擬可量測OPEN併發且持續提供frame的FFmpeg capture。"""

    lock = threading.Lock()
    active_opens = 0
    peak_opens = 0
    established_urls = set()
    constructor_calls = []
    open_delay = 0.02
    failed_urls = set()

    @classmethod
    def reset(cls):
        with cls.lock:
            cls.active_opens = 0
            cls.peak_opens = 0
            cls.established_urls = set()
            cls.constructor_calls = []
            cls.open_delay = 0.02
            cls.failed_urls = set()

    def __init__(self, url, backend, parameters):
        self.url = url
        self.opened = False
        capture_type = type(self)
        with capture_type.lock:
            capture_type.constructor_calls.append((url, backend, list(parameters)))
            capture_type.active_opens += 1
            capture_type.peak_opens = max(
                capture_type.peak_opens,
                capture_type.active_opens,
            )
        try:
            time.sleep(capture_type.open_delay)
            self.opened = url not in capture_type.failed_urls
            if self.opened:
                with capture_type.lock:
                    capture_type.established_urls.add(url)
        finally:
            with capture_type.lock:
                capture_type.active_opens -= 1

    def isOpened(self):
        return self.opened

    def set(self, *_args):
        return True

    def read(self):
        time.sleep(0.003)
        if not self.opened:
            return False, None
        return True, np.zeros((12, 16, 3), dtype=np.uint8)

    def release(self):
        self.opened = False


class SharedCameraAcquisitionTests(SimpleTestCase):
    def setUp(self):
        ControlledCapture.reset()

    def _create_streams(self, count, *, failed_urls=()):
        ControlledCapture.failed_urls = set(failed_urls)
        startup_slots = threading.BoundedSemaphore(3)
        streams = [
            stream_pool.SharedCameraStream(
                camera_id=index,
                rtsp_url=f"rtsp://camera-{index}/live",
                idle_retention_seconds=0.03,
                startup_slots=startup_slots,
                reconnect_initial_seconds=0.01,
                reconnect_max_seconds=0.03,
            )
            for index in range(1, count + 1)
        ]
        for stream in streams:
            self.assertTrue(stream.subscribe())
        return streams

    @staticmethod
    def _stop_streams(streams):
        for stream in streams:
            stream.unsubscribe()
        for stream in streams:
            stream._thread.join(timeout=1.0)

    @patch("apps.cameras.stream_pool.cv2.VideoCapture", ControlledCapture)
    def test_sixteen_acquisitions_bound_startup_but_all_establish(self):
        startup_slots = threading.BoundedSemaphore(3)
        owner_type = stream_pool.SharedCameraStream

        def owner_factory(camera_id, rtsp_url):
            return owner_type(
                camera_id,
                rtsp_url,
                idle_retention_seconds=0.03,
                startup_slots=startup_slots,
                reconnect_initial_seconds=0.01,
                reconnect_max_seconds=0.03,
            )

        with stream_pool._streams_lock:
            stream_pool._streams.clear()
        streams = []
        try:
            with patch(
                "apps.cameras.stream_pool.SharedCameraStream",
                side_effect=owner_factory,
            ):
                with ThreadPoolExecutor(max_workers=16) as executor:
                    streams = list(
                        executor.map(
                            lambda camera_id: stream_pool.acquire_camera_stream(
                                camera_id,
                                f"rtsp://camera-{camera_id}/live",
                            ),
                            range(1, 17),
                        )
                    )
            self.assertTrue(
                wait_until(
                    lambda: all(stream.connection_state == "frame" for stream in streams),
                    timeout=2.0,
                )
            )
            self.assertLessEqual(ControlledCapture.peak_opens, 3)
            self.assertEqual(len(ControlledCapture.established_urls), 16)
        finally:
            self._stop_streams(streams)
            with stream_pool._streams_lock:
                stream_pool._streams.clear()

        self.assertTrue(all(stream.stopped for stream in streams))

    @patch("apps.cameras.stream_pool.cv2.VideoCapture", ControlledCapture)
    def test_one_failed_camera_does_not_block_fifteen_healthy_cameras(self):
        failed_url = "rtsp://camera-6/live"
        streams = self._create_streams(16, failed_urls=(failed_url,))
        try:
            healthy = [stream for stream in streams if stream.rtsp_url != failed_url]
            failed = next(stream for stream in streams if stream.rtsp_url == failed_url)
            self.assertTrue(
                wait_until(
                    lambda: all(stream.connection_state == "frame" for stream in healthy),
                    timeout=2.0,
                )
            )
            self.assertTrue(
                wait_until(lambda: failed.connection_state == "failed", timeout=1.0)
            )
            self.assertEqual(len(ControlledCapture.established_urls), 15)
            self.assertLessEqual(ControlledCapture.peak_opens, 3)
        finally:
            self._stop_streams(streams)

    @patch("apps.cameras.stream_pool.cv2.VideoCapture", ControlledCapture)
    def test_open_and_read_timeouts_are_passed_at_capture_creation(self):
        stream = stream_pool.SharedCameraStream(
            1,
            "rtsp://camera-1/live",
            idle_retention_seconds=0.02,
            open_timeout_msec=1234,
            read_timeout_msec=2345,
            reconnect_initial_seconds=0.01,
            reconnect_max_seconds=0.02,
        )
        stream.subscribe()
        try:
            self.assertTrue(wait_until(lambda: bool(ControlledCapture.constructor_calls)))
            _url, backend, parameters = ControlledCapture.constructor_calls[0]
            self.assertEqual(backend, stream_pool.cv2.CAP_FFMPEG)
            self.assertEqual(
                parameters,
                [
                    stream_pool.cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    1234,
                    stream_pool.cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    2345,
                ],
            )
        finally:
            self._stop_streams((stream,))

    @patch("apps.cameras.stream_pool.cv2.VideoCapture", ControlledCapture)
    def test_failed_open_retries_use_bounded_backoff(self):
        url = "rtsp://camera-failed/live"
        ControlledCapture.failed_urls = {url}
        ControlledCapture.open_delay = 0.0
        stream = stream_pool.SharedCameraStream(
            1,
            url,
            idle_retention_seconds=0.02,
            startup_slots=threading.BoundedSemaphore(1),
            reconnect_initial_seconds=0.01,
            reconnect_max_seconds=0.04,
        )
        stream.subscribe()
        try:
            time.sleep(0.13)
            attempts = len(ControlledCapture.constructor_calls)
            self.assertGreaterEqual(attempts, 3)
            self.assertLessEqual(attempts, 6)
            self.assertEqual(stream.connection_state, "failed")
        finally:
            self._stop_streams((stream,))

    @patch("apps.cameras.stream_pool.cv2.VideoCapture", ControlledCapture)
    def test_retention_reuses_owner_then_stops_after_idle_window(self):
        stream = stream_pool.SharedCameraStream(
            1,
            "rtsp://camera-1/live",
            idle_retention_seconds=0.08,
            reconnect_initial_seconds=0.01,
            reconnect_max_seconds=0.02,
        )
        stream.subscribe()
        self.assertTrue(wait_until(lambda: stream.connection_state == "frame"))
        stream.unsubscribe()
        time.sleep(0.03)
        self.assertFalse(stream.stopped)
        self.assertTrue(stream.subscribe())
        stream.unsubscribe()
        time.sleep(0.04)
        self.assertFalse(stream.stopped)
        self.assertTrue(wait_until(lambda: stream.stopped, timeout=0.3))
        stream._thread.join(timeout=1.0)

    @patch("apps.cameras.stream_pool.cv2.VideoCapture", ControlledCapture)
    def test_rapid_subscribe_unsubscribe_does_not_leak_capture_thread(self):
        stream = stream_pool.SharedCameraStream(
            1,
            "rtsp://camera-1/live",
            idle_retention_seconds=0.03,
            reconnect_initial_seconds=0.01,
            reconnect_max_seconds=0.02,
        )
        for _index in range(20):
            self.assertTrue(stream.subscribe())
            stream.unsubscribe()
        self.assertTrue(wait_until(lambda: stream.stopped, timeout=0.5))
        stream._thread.join(timeout=1.0)
        self.assertFalse(stream._thread.is_alive())

    def test_same_camera_concurrent_acquire_creates_one_owner(self):
        created = []

        class FakeOwner:
            def __init__(self, camera_id, rtsp_url):
                self.camera_id = camera_id
                self.rtsp_url = rtsp_url
                self.stopped = False
                created.append(self)

            def subscribe(self):
                return True

        with stream_pool._streams_lock:
            stream_pool._streams.clear()
        try:
            with patch("apps.cameras.stream_pool.SharedCameraStream", FakeOwner):
                with ThreadPoolExecutor(max_workers=16) as executor:
                    owners = list(
                        executor.map(
                            lambda _index: stream_pool.acquire_camera_stream(
                                7,
                                (
                                    "rtsp://camera-7/live"
                                    if _index % 2 == 0
                                    else "rtsp://camera-7/updated"
                                ),
                            ),
                            range(16),
                        )
                    )
            self.assertEqual(len(created), 1)
            self.assertTrue(all(owner is owners[0] for owner in owners))
        finally:
            with stream_pool._streams_lock:
                stream_pool._streams.clear()

    def test_default_retention_and_single_capture_owner_are_preserved(self):
        self.assertEqual(stream_pool.STREAM_IDLE_RETENTION_SECONDS, 15.0)
        self.assertEqual(inspect.getsource(stream_pool).count("cv2.VideoCapture("), 1)
        self.assertNotIn("VideoCapture", inspect.getsource(mosaic))
