import threading
import time

import cv2


STREAM_IDLE_RETENTION_SECONDS = 15.0
RTSP_STARTUP_CONCURRENCY = 3
RTSP_OPEN_TIMEOUT_MSEC = 5000
RTSP_READ_TIMEOUT_MSEC = 3000
RTSP_RECONNECT_INITIAL_SECONDS = 0.5
RTSP_RECONNECT_MAX_SECONDS = 5.0


_rtsp_startup_slots = threading.BoundedSemaphore(RTSP_STARTUP_CONCURRENCY)


class SharedCameraStream:
    """Keep one RTSP capture alive briefly after the last MJPEG client leaves."""

    def __init__(
        self,
        camera_id,
        rtsp_url,
        idle_retention_seconds=STREAM_IDLE_RETENTION_SECONDS,
        *,
        startup_slots=None,
        open_timeout_msec=RTSP_OPEN_TIMEOUT_MSEC,
        read_timeout_msec=RTSP_READ_TIMEOUT_MSEC,
        reconnect_initial_seconds=RTSP_RECONNECT_INITIAL_SECONDS,
        reconnect_max_seconds=RTSP_RECONNECT_MAX_SECONDS,
    ):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.idle_retention_seconds = float(idle_retention_seconds)
        self.open_timeout_msec = max(1, int(open_timeout_msec))
        self.read_timeout_msec = max(1, int(read_timeout_msec))
        self.reconnect_initial_seconds = max(
            0.01,
            float(reconnect_initial_seconds),
        )
        self.reconnect_max_seconds = max(
            self.reconnect_initial_seconds,
            float(reconnect_max_seconds),
        )
        self._startup_slots = startup_slots or _rtsp_startup_slots
        self._condition = threading.Condition()
        self._subscribers = 0
        self._last_frame = None
        self._frame_version = 0
        self._idle_since = None
        self._stopped = False
        self._connection_state = "connecting"
        self._thread = threading.Thread(
            target=self._run,
            name=f"krtc-camera-stream-{camera_id}",
            daemon=True,
        )
        self._thread.start()

    @property
    def stopped(self):
        with self._condition:
            return self._stopped

    @property
    def connection_state(self):
        """回傳不含URL或credential的Camera連線狀態。"""
        with self._condition:
            return self._connection_state

    def subscribe(self):
        with self._condition:
            if self._stopped:
                return False
            self._subscribers += 1
            self._idle_since = None
            self._condition.notify_all()
            return True

    def unsubscribe(self):
        with self._condition:
            if self._subscribers > 0:
                self._subscribers -= 1
            if self._subscribers == 0:
                self._idle_since = time.monotonic()
            self._condition.notify_all()

    def wait_for_frame(self, last_version, timeout=2.0):
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._stopped and self._frame_version <= last_version:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)

            if self._frame_version > last_version and self._last_frame is not None:
                return self._frame_version, self._last_frame.copy()
            return last_version, None

    def _mark_stopped(self):
        with self._condition:
            self._stopped = True
            self._connection_state = "stopped"
            self._condition.notify_all()

    def _set_connection_state(self, state):
        with self._condition:
            self._connection_state = state
            self._condition.notify_all()

    def _should_stop_for_idle(self):
        with self._condition:
            if self._subscribers > 0 or self._idle_since is None:
                return False
            return (time.monotonic() - self._idle_since) >= self.idle_retention_seconds

    def _publish(self, frame):
        with self._condition:
            self._last_frame = frame
            self._frame_version += 1
            self._connection_state = "frame"
            self._condition.notify_all()

    def _wait_for_retry(self, delay_seconds):
        """以可被subscribe/unsubscribe喚醒的方式等待下一次重連。"""
        deadline = time.monotonic() + max(0.0, float(delay_seconds))
        with self._condition:
            while True:
                now = time.monotonic()
                if self._subscribers == 0 and self._idle_since is not None:
                    idle_remaining = (
                        self.idle_retention_seconds - (now - self._idle_since)
                    )
                    if idle_remaining <= 0:
                        return False
                else:
                    idle_remaining = None

                retry_remaining = deadline - now
                if retry_remaining <= 0:
                    return True
                wait_seconds = retry_remaining
                if idle_remaining is not None:
                    wait_seconds = min(wait_seconds, idle_remaining)
                self._condition.wait(wait_seconds)

    def _acquire_startup_slot(self):
        """可中止地等待OPEN slot，slot不限制已建立的RTSP總數。"""
        while not self._startup_slots.acquire(timeout=0.1):
            if self._should_stop_for_idle():
                return False
        return True

    def _open_capture(self):
        """僅在VideoCapture OPEN期間持有全域startup slot。"""
        if not self._acquire_startup_slot():
            return None
        cap = None
        try:
            if self._should_stop_for_idle():
                return None
            cap = cv2.VideoCapture(
                self.rtsp_url,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    self.open_timeout_msec,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    self.read_timeout_msec,
                ],
            )
            if not cap.isOpened():
                cap.release()
                return None
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            self._set_connection_state("connected")
            return cap
        except Exception:
            if cap is not None:
                cap.release()
            return None
        finally:
            self._startup_slots.release()

    def _run(self):
        cap = None
        reconnect_delay = self.reconnect_initial_seconds
        try:
            while True:
                if self._should_stop_for_idle():
                    return

                if cap is None or not cap.isOpened():
                    if cap is not None:
                        cap.release()
                    cap = self._open_capture()
                    if cap is None:
                        self._set_connection_state("failed")
                        if not self._wait_for_retry(reconnect_delay):
                            return
                        reconnect_delay = min(
                            self.reconnect_max_seconds,
                            max(
                                self.reconnect_initial_seconds,
                                reconnect_delay * 2,
                            ),
                        )
                        continue
                    reconnect_delay = self.reconnect_initial_seconds

                try:
                    success, frame = cap.read()
                except Exception:
                    success, frame = False, None
                if not success:
                    cap.release()
                    cap = None
                    self._set_connection_state("failed")
                    if not self._wait_for_retry(reconnect_delay):
                        return
                    reconnect_delay = min(
                        self.reconnect_max_seconds,
                        max(
                            self.reconnect_initial_seconds,
                            reconnect_delay * 2,
                        ),
                    )
                    continue

                reconnect_delay = self.reconnect_initial_seconds
                self._publish(frame)
        finally:
            if cap is not None:
                cap.release()
            self._mark_stopped()
            _remove_stream_if_current(self.camera_id, self)


_streams = {}
_streams_lock = threading.Lock()


def _remove_stream_if_current(camera_id, stream):
    with _streams_lock:
        if _streams.get(camera_id) is stream:
            _streams.pop(camera_id, None)


def acquire_camera_stream(camera_id, rtsp_url):
    """Return a subscribed shared stream, reusing it during the 15-second grace window."""
    while True:
        with _streams_lock:
            stream = _streams.get(camera_id)
            # camera_id是唯一owner key；URL變更必須等既有owner完整停止後
            # 才建立新capture，避免同一Camera短暫出現雙重RTSP連線。
            if stream is None or stream.stopped:
                stream = SharedCameraStream(camera_id, rtsp_url)
                _streams[camera_id] = stream

        if stream.subscribe():
            return stream

        _remove_stream_if_current(camera_id, stream)


def active_stream_snapshot():
    """Small diagnostic helper used by regression tests; no credentials are exposed."""
    with _streams_lock:
        return {
            camera_id: {
                "stopped": stream.stopped,
                "connection_state": stream.connection_state,
                "idle_retention_seconds": stream.idle_retention_seconds,
            }
            for camera_id, stream in _streams.items()
        }
