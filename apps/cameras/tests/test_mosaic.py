import inspect
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.cameras import mosaic
from apps.cameras.models import Camera


class FakeCameraStream:
    """提供可預測且不建立RTSP的SharedCameraStream測試替身。"""

    def __init__(self, frame=None, stopped=False, connection_state="connecting"):
        self.frame = frame
        self.stopped = stopped
        self.connection_state = connection_state
        self.wait_timeouts = []
        self.unsubscribe_count = 0
        self._published = False

    def wait_for_frame(self, last_version, timeout=2.0):
        self.wait_timeouts.append(timeout)
        if self.frame is not None and not self._published:
            self._published = True
            return last_version + 1, self.frame.copy()
        return last_version, None

    def unsubscribe(self):
        self.unsubscribe_count += 1


class MosaicCompositionTests(SimpleTestCase):
    def test_profiles_are_server_controlled(self):
        grid9 = mosaic.MOSAIC_PROFILES["grid9"]
        grid16 = mosaic.MOSAIC_PROFILES["grid16"]

        self.assertEqual((grid9.rows, grid9.columns), (3, 3))
        self.assertEqual((grid9.canvas_width, grid9.canvas_height), (1600, 900))
        self.assertEqual(grid9.fps, 8)
        self.assertEqual((grid16.rows, grid16.columns), (4, 4))
        self.assertEqual((grid16.canvas_width, grid16.canvas_height), (1600, 900))
        self.assertEqual(grid16.fps, 5)

    def test_frame_resize_preserves_canvas_dimensions(self):
        frame = np.full((720, 1280, 3), 180, dtype=np.uint8)
        tile = mosaic.fit_frame_to_tile(frame, 400, 225)
        self.assertEqual(tile.shape, (225, 400, 3))
        self.assertGreater(int(tile.mean()), 0)

    def test_cover_resize_fills_destination_without_distortion(self):
        frame = np.full((100, 300, 3), 180, dtype=np.uint8)

        with patch("apps.cameras.mosaic.cv2.resize") as resize:
            resize.return_value = np.full((100, 300, 3), 180, dtype=np.uint8)
            tile = mosaic.fit_frame_to_tile(frame, 100, 100)

        self.assertEqual(resize.call_args.args[1], (300, 100))
        self.assertEqual(tile.shape, (100, 100, 3))
        self.assertTrue(np.all(tile == 180))

    def test_cover_resize_center_crops_wide_source(self):
        frame = np.zeros((100, 300, 3), dtype=np.uint8)
        frame[:, :100] = (255, 0, 0)
        frame[:, 100:200] = (0, 255, 0)
        frame[:, 200:] = (0, 0, 255)

        tile = mosaic.fit_frame_to_tile(frame, 100, 100)

        self.assertEqual(tile.shape, (100, 100, 3))
        self.assertGreater(float(tile[:, :, 1].mean()), 250.0)
        self.assertLess(float(tile[:, :, 0].mean()), 1.0)
        self.assertLess(float(tile[:, :, 2].mean()), 1.0)

    def test_cover_resize_center_crops_tall_source(self):
        frame = np.zeros((300, 100, 3), dtype=np.uint8)
        frame[:100, :] = (255, 0, 0)
        frame[100:200, :] = (0, 255, 0)
        frame[200:, :] = (0, 0, 255)

        tile = mosaic.fit_frame_to_tile(frame, 100, 100)

        self.assertEqual(tile.shape, (100, 100, 3))
        self.assertGreater(float(tile[:, :, 1].mean()), 250.0)
        self.assertLess(float(tile[:, :, 0].mean()), 1.0)
        self.assertLess(float(tile[:, :, 2].mean()), 1.0)

    def test_placeholder_has_requested_dimensions(self):
        tile = mosaic.placeholder_tile(320, 180, "CAM-007", "NO SIGNAL")
        self.assertEqual(tile.shape, (180, 320, 3))
        self.assertGreater(int(tile.mean()), 0)

    def test_mosaic_module_never_references_video_capture(self):
        self.assertNotIn("VideoCapture", inspect.getsource(mosaic))

    def test_source_repr_does_not_expose_rtsp_credentials(self):
        source = mosaic.CameraMosaicSource(
            1,
            "CAM-001",
            "rtsp://operator:secret@example/live",
        )

        self.assertNotIn("secret", repr(source))
        self.assertNotIn("rtsp://", repr(source))

    def test_invalid_source_sets_are_rejected_before_registry_acquire(self):
        duplicate_sources = (
            mosaic.CameraMosaicSource(1, "CAM-001", "rtsp://example/cam1"),
            mosaic.CameraMosaicSource(1, "CAM-001", "rtsp://example/cam1"),
        )
        too_many_sources = tuple(
            mosaic.CameraMosaicSource(index, f"CAM-{index:03d}", "")
            for index in range(1, 11)
        )

        with self.assertRaises(ValueError):
            mosaic.acquire_mosaic_stream("grid9", duplicate_sources)
        with self.assertRaises(ValueError):
            mosaic.acquire_mosaic_stream("grid9", too_many_sources)
        with self.assertRaises(ValueError):
            mosaic.acquire_mosaic_stream("grid4", ())


class SharedMosaicLifecycleTests(SimpleTestCase):
    @staticmethod
    def tiny_profile(name="test-grid"):
        return mosaic.MosaicProfile(
            name=name,
            rows=1,
            columns=1,
            canvas_width=32,
            canvas_height=24,
            fps=10,
            jpeg_quality=60,
            stale_after_seconds=1.0,
        )

    def test_dead_camera_never_blocks_mosaic_and_cleanup_is_immediate(self):
        live_frame = np.full((90, 160, 3), 200, dtype=np.uint8)
        fake_streams = {
            1: FakeCameraStream(live_frame),
            2: FakeCameraStream(stopped=True),
        }
        acquire_calls = []

        def acquire(camera_id, _rtsp_url):
            acquire_calls.append(camera_id)
            return fake_streams[camera_id]

        sources = (
            mosaic.CameraMosaicSource(1, "CAM-001", "rtsp://example/cam1"),
            mosaic.CameraMosaicSource(2, "CAM-002", "rtsp://example/cam2"),
        )
        stream = mosaic.SharedMosaicStream(
            mosaic.MOSAIC_PROFILES["grid9"],
            sources,
            stream_acquirer=acquire,
        )

        with patch("apps.cameras.mosaic.cv2.VideoCapture") as video_capture:
            self.assertTrue(stream.subscribe())
            version, jpeg_bytes = stream.wait_for_jpeg(0, timeout=2.0)
            stream.unsubscribe()
            stream.join(timeout=2.0)

        snapshot = stream.snapshot()
        self.assertGreater(version, 0)
        self.assertTrue(jpeg_bytes.startswith(b"\xff\xd8"))
        self.assertEqual(acquire_calls, [1, 2])
        self.assertEqual(fake_streams[1].wait_timeouts[0], 0.0)
        self.assertEqual(fake_streams[2].wait_timeouts[0], 0.0)
        self.assertEqual(fake_streams[1].unsubscribe_count, 1)
        self.assertEqual(fake_streams[2].unsubscribe_count, 1)
        self.assertEqual(snapshot["subscriber_count"], 0)
        self.assertTrue(snapshot["stopped"])
        self.assertEqual(snapshot["tile_states"][0], "frame")
        self.assertEqual(snapshot["tile_states"][1], "no_signal")
        video_capture.assert_not_called()

    def test_stale_camera_uses_placeholder_without_waiting(self):
        source = mosaic.CameraMosaicSource(
            3,
            "CAM-003",
            "rtsp://example/cam3",
        )
        fake_stream = FakeCameraStream()
        stream = mosaic.SharedMosaicStream(
            mosaic.MOSAIC_PROFILES["grid9"],
            (source,),
            stream_acquirer=lambda _camera_id, _url: fake_stream,
        )
        old_tile = np.full((300, 534, 3), 255, dtype=np.uint8)
        tile_cache = {
            3: {
                "version": 1,
                "tile": old_tile,
                "received_at": 10.0,
            }
        }

        _canvas, tile_states = stream._compose(
            (fake_stream,),
            tile_cache,
            now=17.0,
        )

        self.assertEqual(fake_stream.wait_timeouts, [0.0])
        self.assertEqual(tile_states[0], "no_signal")

    def test_failed_camera_uses_explicit_no_signal_state(self):
        source = mosaic.CameraMosaicSource(
            4,
            "CAM-004",
            "rtsp://example/cam4",
        )
        fake_stream = FakeCameraStream(connection_state="failed")
        stream = mosaic.SharedMosaicStream(
            mosaic.MOSAIC_PROFILES["grid16"],
            (source,),
            stream_acquirer=lambda _camera_id, _url: fake_stream,
        )

        _canvas, tile_states = stream._compose(
            (fake_stream,),
            {},
            now=1.0,
        )

        self.assertEqual(tile_states[0], "no_signal")

    def test_concurrent_browsers_share_one_canonical_compositor(self):
        fake_stream = FakeCameraStream(np.zeros((45, 80, 3), dtype=np.uint8))
        factory_count = 0
        acquire_count = 0
        factory_lock = threading.Lock()

        def acquire_fake_stream(_camera_id, _url):
            nonlocal acquire_count
            with factory_lock:
                acquire_count += 1
            return fake_stream

        def factory(profile, sources, on_stopped):
            nonlocal factory_count
            with factory_lock:
                factory_count += 1
            return mosaic.SharedMosaicStream(
                profile,
                sources,
                stream_acquirer=acquire_fake_stream,
                on_stopped=on_stopped,
            )

        registry = mosaic.MosaicRegistry(stream_factory=factory)
        sources = (
            mosaic.CameraMosaicSource(7, "CAM-007", "rtsp://example/cam7"),
        )
        barrier = threading.Barrier(8)

        def acquire_same_layout():
            barrier.wait()
            return registry.acquire(mosaic.MOSAIC_PROFILES["grid9"], sources)

        with ThreadPoolExecutor(max_workers=8) as executor:
            streams = list(executor.map(lambda _index: acquire_same_layout(), range(8)))

        self.assertTrue(all(stream is streams[0] for stream in streams))
        self.assertEqual(factory_count, 1)
        self.assertEqual(acquire_count, 1)
        self.assertEqual(streams[0].snapshot()["subscriber_count"], 8)

        for stream in streams:
            stream.unsubscribe()
        streams[0].join(timeout=2.0)

        self.assertEqual(fake_stream.unsubscribe_count, 1)
        self.assertTrue(streams[0].snapshot()["stopped"])
        self.assertEqual(registry.snapshot(), {})

    def test_camera_order_changes_canonical_layout_key(self):
        profile = mosaic.MosaicProfile("grid-test", 1, 2, 64, 24, 5, 60, 1.0)
        first = mosaic.CameraMosaicSource(1, "CAM-001", "rtsp://cam/1")
        second = mosaic.CameraMosaicSource(2, "CAM-002", "rtsp://cam/2")
        forward = mosaic.SharedMosaicStream(profile, (first, second))
        reverse = mosaic.SharedMosaicStream(profile, (second, first))

        self.assertNotEqual(forward.layout_key, reverse.layout_key)
        self.assertEqual(forward.layout_key[1], (1, 2))
        self.assertEqual(reverse.layout_key[1], (2, 1))

    def test_failed_camera_state_moves_with_reordered_source(self):
        healthy_frame = np.full((12, 16, 3), 200, dtype=np.uint8)
        healthy = FakeCameraStream(healthy_frame)
        failed = FakeCameraStream(connection_state="failed")
        first = mosaic.CameraMosaicSource(1, "CAM-001", "rtsp://cam/1")
        second = mosaic.CameraMosaicSource(2, "CAM-002", "rtsp://cam/2")
        profile = mosaic.MosaicProfile("grid-test", 1, 2, 64, 24, 5, 60, 1.0)
        stream = mosaic.SharedMosaicStream(profile, (first, second))

        _canvas, forward_states = stream._compose((failed, healthy), {}, now=1.0)
        reverse_healthy = FakeCameraStream(healthy_frame)
        reverse_stream = mosaic.SharedMosaicStream(profile, (second, first))
        _canvas, reverse_states = reverse_stream._compose(
            (reverse_healthy, failed),
            {},
            now=1.0,
        )

        self.assertEqual(forward_states, {0: "no_signal", 1: "frame"})
        self.assertEqual(reverse_states, {0: "frame", 1: "no_signal"})

    def test_repeated_order_changes_cleanup_old_compositors(self):
        profile = mosaic.MosaicProfile("grid-test", 1, 2, 64, 24, 5, 60, 1.0)
        registry = mosaic.MosaicRegistry(acquire_timeout=0.5)
        first = mosaic.CameraMosaicSource(1, "CAM-001", "")
        second = mosaic.CameraMosaicSource(2, "CAM-002", "")

        for index in range(20):
            sources = (first, second) if index % 2 == 0 else (second, first)
            stream = registry.acquire(profile, sources, session_key="m2-session")
            registry.release(stream, session_key="m2-session")
            stream.join(timeout=1.0)

        self.assertEqual(registry.snapshot(), {})

    def test_thread_start_failure_is_removed_and_retry_succeeds(self):
        created_streams = []

        def factory(profile, sources, on_stopped):
            stream = mosaic.SharedMosaicStream(
                profile,
                sources,
                stream_acquirer=lambda _camera_id, _url: FakeCameraStream(),
                on_stopped=on_stopped,
            )
            created_streams.append(stream)
            return stream

        registry = mosaic.MosaicRegistry(stream_factory=factory)
        profile = self.tiny_profile()

        with patch(
            "apps.cameras.mosaic.threading.Thread.start",
            side_effect=RuntimeError("start failed"),
        ):
            with self.assertRaises(RuntimeError):
                registry.acquire(profile, ())

        self.assertTrue(created_streams[0].snapshot()["stopped"])
        self.assertEqual(created_streams[0].snapshot()["subscriber_count"], 0)
        self.assertEqual(registry.snapshot(), {})

        retry_stream = registry.acquire(profile, ())
        self.assertIsNot(retry_stream, created_streams[0])
        retry_stream.unsubscribe()
        retry_stream.join(timeout=1.0)
        self.assertTrue(retry_stream.snapshot()["stopped"])

    def test_bootstrap_failure_marks_stopped_and_removes_registry_entry(self):
        removed = Mock()
        stream = mosaic.SharedMosaicStream(
            self.tiny_profile(),
            (),
            on_stopped=removed,
        )

        with patch("apps.cameras.mosaic.np.zeros", side_effect=MemoryError):
            with self.assertRaises(MemoryError):
                stream._run()

        self.assertTrue(stream.snapshot()["stopped"])
        removed.assert_called_once_with(stream.layout_key, stream)

    def test_compositor_exception_unsubscribes_all_acquired_cameras(self):
        fake_camera = FakeCameraStream()
        source = mosaic.CameraMosaicSource(1, "CAM-001", "rtsp://example/cam1")
        removed = Mock()
        stream = mosaic.SharedMosaicStream(
            self.tiny_profile(),
            (source,),
            stream_acquirer=lambda _camera_id, _url: fake_camera,
            on_stopped=removed,
        )

        with patch.object(stream, "_compose", side_effect=RuntimeError("compose")):
            with self.assertRaises(RuntimeError):
                stream._run()

        self.assertEqual(fake_camera.unsubscribe_count, 1)
        self.assertTrue(stream.snapshot()["stopped"])
        removed.assert_called_once_with(stream.layout_key, stream)

    def test_encoding_exception_unsubscribes_and_stops_compositor(self):
        fake_camera = FakeCameraStream()
        source = mosaic.CameraMosaicSource(1, "CAM-001", "rtsp://example/cam1")
        removed = Mock()
        stream = mosaic.SharedMosaicStream(
            self.tiny_profile(),
            (source,),
            stream_acquirer=lambda _camera_id, _url: fake_camera,
            on_stopped=removed,
        )

        with patch("apps.cameras.mosaic.cv2.imencode", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                stream._run()

        self.assertEqual(fake_camera.unsubscribe_count, 1)
        self.assertTrue(stream.snapshot()["stopped"])
        removed.assert_called_once_with(stream.layout_key, stream)

    def test_same_key_reacquire_waits_for_old_cleanup_without_overlap(self):
        cleanup_started = threading.Event()
        allow_cleanup = threading.Event()
        source_acquired = threading.Event()
        factory_count = 0

        class BlockingCleanupCamera(FakeCameraStream):
            def unsubscribe(self):
                cleanup_started.set()
                allow_cleanup.wait(timeout=1.0)
                super().unsubscribe()

        def factory(profile, sources, on_stopped):
            nonlocal factory_count
            factory_count += 1
            camera = BlockingCleanupCamera() if factory_count == 1 else FakeCameraStream()

            def acquire(_camera_id, _url):
                source_acquired.set()
                return camera

            return mosaic.SharedMosaicStream(
                profile,
                sources,
                stream_acquirer=acquire,
                on_stopped=on_stopped,
            )

        registry = mosaic.MosaicRegistry(stream_factory=factory, acquire_timeout=1.0)
        profile = self.tiny_profile()
        sources = (mosaic.CameraMosaicSource(1, "CAM-001", "rtsp://cam/1"),)
        old_stream = registry.acquire(profile, sources)
        self.assertTrue(source_acquired.wait(timeout=1.0))
        old_stream.unsubscribe()
        self.assertTrue(cleanup_started.wait(timeout=1.0))

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(registry.acquire, profile, sources)
            time.sleep(0.05)
            self.assertFalse(future.done())
            self.assertEqual(factory_count, 1)
            allow_cleanup.set()
            new_stream = future.result(timeout=1.0)

        self.assertEqual(factory_count, 2)
        self.assertIsNot(new_stream, old_stream)
        new_stream.unsubscribe()
        new_stream.join(timeout=1.0)

    def test_registry_global_and_session_caps_are_bounded(self):
        registry = mosaic.MosaicRegistry(
            max_active_layouts=1,
            max_session_layouts=1,
            acquire_timeout=0.02,
        )
        first_profile = self.tiny_profile("first")
        second_profile = self.tiny_profile("second")
        first_stream = registry.acquire(first_profile, (), session_key="session-a")

        with self.assertRaises(mosaic.MosaicSessionCapacityError):
            registry.acquire(second_profile, (), session_key="session-a")
        with self.assertRaises(mosaic.MosaicCapacityError):
            registry.acquire(second_profile, (), session_key="session-b")

        same_stream = registry.acquire(first_profile, (), session_key="session-a")
        self.assertIs(same_stream, first_stream)
        registry.release(same_stream, session_key="session-a")
        registry.release(first_stream, session_key="session-a")
        first_stream.join(timeout=1.0)

        replacement = registry.acquire(second_profile, (), session_key="session-a")
        registry.release(replacement, session_key="session-a")
        replacement.join(timeout=1.0)

    def test_multipart_generator_unsubscribes_on_close(self):
        from apps.cameras.views import generate_mosaic_mjpeg_frames

        fake_mosaic = Mock()
        fake_mosaic.wait_for_jpeg.return_value = (1, b"jpeg")
        with patch(
            "apps.cameras.views.acquire_mosaic_stream",
            return_value=fake_mosaic,
        ) as acquire, patch("apps.cameras.views.release_mosaic_stream") as release:
            generator = generate_mosaic_mjpeg_frames("grid9", ())
            chunk = next(generator)
            generator.close()

        acquire.assert_called_once_with("grid9", (), session_key=None)
        self.assertIn(b"Content-Type: image/jpeg", chunk)
        release.assert_called_once_with(fake_mosaic, session_key=None)

    def test_unstarted_response_iterator_still_releases_subscriber(self):
        from apps.cameras.views import generate_mosaic_mjpeg_frames

        fake_mosaic = Mock()
        with patch(
            "apps.cameras.views.acquire_mosaic_stream",
            return_value=fake_mosaic,
        ) as acquire, patch("apps.cameras.views.release_mosaic_stream") as release:
            generator = generate_mosaic_mjpeg_frames("grid16", ())
            generator.close()

        acquire.assert_called_once_with("grid16", (), session_key=None)
        release.assert_called_once_with(fake_mosaic, session_key=None)


class MosaicEndpointSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mosaic-user", password="test-pass")
        for index in range(1, 17):
            Camera.objects.create(
                camera_code=f"CAM-{index:03d}",
                name=f"Camera {index}",
                area="Lab",
                rtsp_url=f"rtsp://camera-{index}/live",
                username="operator",
                password="secret",
                is_active=True,
            )

    def test_anonymous_mosaic_is_redirected_to_login(self):
        response = self.client.get(
            reverse("cameras:camera_mosaic_stream"),
            {"layout": "grid9", "group": "0"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response.url)

    @patch("apps.cameras.views.acquire_mosaic_stream")
    def test_authenticated_request_uses_server_derived_group(self, acquire):
        fake_mosaic = Mock()
        fake_mosaic.wait_for_jpeg.return_value = (1, b"jpeg")
        acquire.return_value = fake_mosaic
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("cameras:camera_mosaic_stream"),
            {"layout": "grid9", "group": "0", "ts": "123"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "multipart/x-mixed-replace; boundary=frame",
        )
        first_chunk = next(iter(response.streaming_content))
        layout, sources = acquire.call_args.args
        self.assertEqual(layout, "grid9")
        self.assertEqual([source.camera_id for source in sources], list(range(1, 10)))
        self.assertTrue(all("operator:secret@" in source.rtsp_url for source in sources))
        self.assertNotIn("secret", repr(dict(response.items())))
        self.assertIn(b"Content-Type: image/jpeg", first_chunk)
        response.close()
        fake_mosaic.unsubscribe.assert_called_once_with()

    def test_client_cannot_supply_ids_or_output_controls(self):
        self.client.force_login(self.user)
        endpoint = reverse("cameras:camera_mosaic_stream")

        for forbidden in ("camera_ids", "rtsp_url", "fps", "quality", "width"):
            with self.subTest(parameter=forbidden):
                response = self.client.get(
                    endpoint,
                    {"layout": "grid9", "group": "0", forbidden: "1"},
                )
                self.assertEqual(response.status_code, 400)

    @patch("apps.cameras.views.acquire_mosaic_stream")
    def test_grid9_accepts_validated_ordered_camera_ids(self, acquire):
        fake_mosaic = Mock()
        fake_mosaic.wait_for_jpeg.return_value = (1, b"jpeg")
        acquire.return_value = fake_mosaic
        self.client.force_login(self.user)
        ordered_ids = list(range(9, 0, -1))

        response = self.client.get(
            reverse("cameras:camera_mosaic_stream"),
            {
                "layout": "grid9",
                "group": "0",
                "camera_ids": ",".join(str(value) for value in ordered_ids),
            },
        )

        self.assertEqual(response.status_code, 200)
        _layout, sources = acquire.call_args.args
        self.assertEqual([source.camera_id for source in sources], ordered_ids)
        response.close()

    @patch("apps.cameras.views.acquire_mosaic_stream")
    def test_grid16_accepts_validated_ordered_camera_ids(self, acquire):
        fake_mosaic = Mock()
        fake_mosaic.wait_for_jpeg.return_value = (1, b"jpeg")
        acquire.return_value = fake_mosaic
        self.client.force_login(self.user)
        ordered_ids = list(range(16, 0, -1))

        response = self.client.get(
            reverse("cameras:camera_mosaic_stream"),
            {
                "layout": "grid16",
                "group": "0",
                "camera_ids": ",".join(str(value) for value in ordered_ids),
            },
        )

        self.assertEqual(response.status_code, 200)
        _layout, sources = acquire.call_args.args
        self.assertEqual([source.camera_id for source in sources], ordered_ids)
        response.close()

    @patch("apps.cameras.views.acquire_mosaic_stream")
    def test_invalid_ordered_camera_ids_are_rejected(self, acquire):
        self.client.force_login(self.user)
        endpoint = reverse("cameras:camera_mosaic_stream")
        invalid_orders = (
            ("1,2,3,4,5,6,7,8", "Invalid mosaic camera count."),
            ("1,2,3,4,5,6,7,8,8", "Duplicate mosaic camera."),
            ("1,2,3,4,5,6,7,8,999", "Invalid mosaic camera order."),
            ("1,2,3,4,5,6,7,8,rtsp://host/live", "Invalid mosaic camera order."),
        )

        for camera_ids, message in invalid_orders:
            with self.subTest(camera_ids=camera_ids):
                response = self.client.get(
                    endpoint,
                    {"layout": "grid9", "group": "0", "camera_ids": camera_ids},
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["message"], message)

        acquire.assert_not_called()

    def test_invalid_layout_group_and_duplicate_parameters_are_rejected(self):
        self.client.force_login(self.user)
        endpoint = reverse("cameras:camera_mosaic_stream")

        self.assertEqual(
            self.client.get(endpoint, {"layout": "grid4", "group": "0"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(endpoint, {"layout": "grid9", "group": "-1"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(endpoint + "?layout=grid9&layout=grid16&group=0").status_code,
            400,
        )
        self.assertEqual(
            self.client.get(endpoint, {"layout": "grid9", "group": "2"}).status_code,
            404,
        )

    def test_capacity_errors_use_fixed_credential_free_responses(self):
        self.client.force_login(self.user)
        endpoint = reverse("cameras:camera_mosaic_stream")
        cases = (
            (mosaic.MosaicSessionCapacityError, 429, "Mosaic session capacity exceeded."),
            (mosaic.MosaicLayoutBusyError, 503, "Mosaic layout is restarting."),
            (mosaic.MosaicCapacityError, 503, "Mosaic capacity unavailable."),
        )

        for error_type, status_code, message in cases:
            with self.subTest(error=error_type.__name__), patch(
                "apps.cameras.views.acquire_mosaic_stream",
                side_effect=error_type("rtsp://operator:secret@example/live"),
            ):
                response = self.client.get(
                    endpoint,
                    {"layout": "grid9", "group": "0"},
                )

            self.assertEqual(response.status_code, status_code)
            self.assertEqual(response.json()["message"], message)
            self.assertNotIn("secret", response.content.decode("utf-8"))


class MosaicFrontendContractTests(SimpleTestCase):
    def test_grid9_and_grid16_use_mosaic_while_grid1_and_grid4_remain(self):
        script = (Path(settings.BASE_DIR) / "static/js/monitor.js").read_text(
            encoding="utf-8"
        )
        template = (
            Path(settings.BASE_DIR) / "templates/dashboard/monitor.html"
        ).read_text(encoding="utf-8")

        self.assertIn("currentGridSize === 9 || currentGridSize === 16", script)
        self.assertIn("releaseAllCameraStreams();", script)
        self.assertIn("activateMosaicStream();", script)
        self.assertIn("syncVisibleCameraStreams();", script)
        self.assertIn('return "single";', script)
        self.assertIn('return "grid4";', script)
        self.assertIn("if (isMosaicMode())", script)
        self.assertIn("camera_mosaic_stream", template)
        self.assertIn("data-camera-stream", template)
        self.assertIn("data-stream-url", template)

    def test_m2_uses_sidebar_sources_and_visual_drop_slots(self):
        script = (Path(settings.BASE_DIR) / "static/js/monitor.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (
            Path(settings.BASE_DIR) / "static/css/monitor.css"
        ).read_text(encoding="utf-8")
        template = (
            Path(settings.BASE_DIR) / "templates/dashboard/monitor.html"
        ).read_text(encoding="utf-8")

        self.assertIn("monitorMosaicInteractionGrid", script)
        self.assertIn("function moveCameraToSlot", script)
        self.assertIn("function moveSidebarCameraToMosaicSlot", script)
        self.assertIn("moveCameraToSlot(cameraId, selectedSlot)", script)
        self.assertIn("moveCameraToSlot(cameraId, targetSlot)", script)
        self.assertIn('getData("text/plain")', script)
        self.assertNotIn("text/x-krtc-mosaic-slot", script)
        self.assertNotIn("tile.draggable", script)
        self.assertIn("slotIndex < currentGridSize", script)
        self.assertIn("clearMosaicDragState();", script)
        self.assertIn('parameters.set("camera_ids", cameraIds.join(","))', script)
        self.assertIn("function getMosaicCameraDetails", script)
        self.assertIn("monitor-camera-info monitor-mosaic-camera-info", script)
        self.assertIn('cameraCard.querySelector(".monitor-camera-name h3")', script)
        self.assertIn('cameraCard.querySelector("[data-status-badge]")', script)
        self.assertIn("repeat(3, minmax(0, 1fr))", stylesheet)
        self.assertIn("repeat(4, minmax(0, 1fr))", stylesheet)
        self.assertIn(".monitor-mosaic-tile-overlay.is-drag-over", stylesheet)
        self.assertIn(".monitor-mosaic-tile-overlay:hover", stylesheet)
        self.assertIn(".monitor-mosaic-camera-info", stylesheet)
        self.assertIn('class="camera-tree-item"', template)
        self.assertIn('draggable="true"', template)
        self.assertIn("monitor-mosaic-interaction-grid", template)
        self.assertEqual(template.count('id="monitorMosaicStream"'), 1)

    def test_mosaic_cleanup_and_no_health_polling_contract(self):
        script = (Path(settings.BASE_DIR) / "static/js/monitor.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("releaseMosaicStream();", script)
        self.assertIn('window.addEventListener("pagehide", cleanupMonitorPage', script)
        self.assertIn("function checkVisibleCameraHealth()", script)
        self.assertIn("拖曳攝影機至 Mosaic 目標格位", script)

    def test_event_alert_targets_current_mosaic_assignment(self):
        script = (Path(settings.BASE_DIR) / "static/js/monitor.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (
            Path(settings.BASE_DIR) / "static/css/monitor.css"
        ).read_text(encoding="utf-8")
        template = (
            Path(settings.BASE_DIR) / "templates/dashboard/monitor.html"
        ).read_text(encoding="utf-8")

        self.assertIn("function cameraMatchesEvent", script)
        self.assertIn("monitorMosaicInteractionGrid.querySelectorAll", script)
        self.assertIn('tile.dataset.cameraId = cameraId', script)
        self.assertIn('tile.dataset.cameraCode = cameraDetails', script)
        self.assertIn('mosaicTile.classList.add("has-event-alert")', script)
        self.assertIn('tile.classList.remove("has-event-alert")', script)
        self.assertIn("EVENT_HIGHLIGHT_DURATION_MS = 8000", script)
        self.assertIn("eventHighlightTimer = window.setTimeout", script)
        self.assertIn(".monitor-mosaic-tile-overlay.has-event-alert", stylesheet)
        self.assertEqual(template.count('id="monitorMosaicStream"'), 1)
