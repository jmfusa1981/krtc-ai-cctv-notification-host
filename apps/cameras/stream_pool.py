import threading
import time

import cv2


STREAM_IDLE_RETENTION_SECONDS = 15.0


class SharedCameraStream:
    """Keep one RTSP capture alive briefly after the last MJPEG client leaves."""

    def __init__(self, camera_id, rtsp_url, idle_retention_seconds=STREAM_IDLE_RETENTION_SECONDS):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.idle_retention_seconds = float(idle_retention_seconds)
        self._condition = threading.Condition()
        self._subscribers = 0
        self._last_frame = None
        self._frame_version = 0
        self._idle_since = None
        self._stopped = False
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
            self._condition.notify_all()

    def _run(self):
        cap = None
        try:
            while True:
                if self._should_stop_for_idle():
                    return

                if cap is None or not cap.isOpened():
                    if cap is not None:
                        cap.release()
                    cap = cv2.VideoCapture(self.rtsp_url)
                    try:
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    except Exception:
                        pass
                    if not cap.isOpened():
                        cap.release()
                        cap = None
                        time.sleep(0.5)
                        continue

                success, frame = cap.read()
                if not success:
                    cap.release()
                    cap = None
                    time.sleep(0.1)
                    continue

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
            if stream is None or stream.stopped or stream.rtsp_url != rtsp_url:
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
                "idle_retention_seconds": stream.idle_retention_seconds,
            }
            for camera_id, stream in _streams.items()
        }
