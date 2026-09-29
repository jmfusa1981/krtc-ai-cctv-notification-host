from dataclasses import dataclass, field
import threading
import time

import cv2
import numpy as np

from .stream_pool import acquire_camera_stream


MOSAIC_MAX_ACTIVE_LAYOUTS = 8
MOSAIC_MAX_SESSION_LAYOUTS = 1
MOSAIC_ACQUIRE_TIMEOUT_SECONDS = 2.0


class MosaicCapacityError(RuntimeError):
    """表示Mosaic資源已達伺服器固定上限。"""


class MosaicLayoutBusyError(RuntimeError):
    """表示相同canonical layout仍在完成上一輪cleanup。"""


class MosaicSessionCapacityError(RuntimeError):
    """表示同一登入session仍持有其他Mosaic layout。"""


@dataclass(frozen=True)
class MosaicProfile:
    """定義由伺服器控制的 Mosaic 輸出限制。"""

    name: str
    rows: int
    columns: int
    canvas_width: int
    canvas_height: int
    fps: int
    jpeg_quality: int
    stale_after_seconds: float

    @property
    def camera_limit(self):
        return self.rows * self.columns


@dataclass(frozen=True)
class CameraMosaicSource:
    """保存已由 Django 驗證的 Camera 資料，不對瀏覽器公開 RTSP。"""

    camera_id: int
    camera_code: str
    rtsp_url: str = field(repr=False, compare=False)


MOSAIC_PROFILES = {
    "grid9": MosaicProfile(
        name="grid9",
        rows=3,
        columns=3,
        canvas_width=1600,
        canvas_height=900,
        fps=8,
        jpeg_quality=70,
        stale_after_seconds=6.0,
    ),
    "grid16": MosaicProfile(
        name="grid16",
        rows=4,
        columns=4,
        canvas_width=1600,
        canvas_height=900,
        fps=5,
        jpeg_quality=65,
        stale_after_seconds=6.0,
    ),
}


def _tile_bounds(total_size, partitions):
    """以整數邊界完整分配畫布像素，避免最後一列或欄遺失。"""
    return [
        (index * total_size + partitions - 1) // partitions
        for index in range(partitions + 1)
    ]


def fit_frame_to_tile(frame, width, height):
    """保持來源比例放大至填滿格位，再置中裁掉超出範圍。"""
    tile = np.zeros((height, width, 3), dtype=np.uint8)
    if frame is None or not hasattr(frame, "shape") or len(frame.shape) < 2:
        return tile

    frame_height, frame_width = frame.shape[:2]
    if frame_height <= 0 or frame_width <= 0:
        return tile

    scale = max(width / float(frame_width), height / float(frame_height))
    resized_width = max(width, int(np.ceil(frame_width * scale)))
    resized_height = max(height, int(np.ceil(frame_height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(
        frame,
        (resized_width, resized_height),
        interpolation=interpolation,
    )
    x_start = max(0, (resized_width - width) // 2)
    y_start = max(0, (resized_height - height) // 2)
    return resized[y_start:y_start + height, x_start:x_start + width].copy()


def placeholder_tile(width, height, title, state):
    """建立不含 URL 或 credential 的本地 placeholder tile。"""
    colors = {
        "CONNECTING": (35, 74, 110),
        "NO SIGNAL": (45, 38, 110),
        "EMPTY": (35, 41, 52),
    }
    tile = np.zeros((height, width, 3), dtype=np.uint8)
    tile[:] = colors.get(state, colors["NO SIGNAL"])
    safe_title = str(title or "CAMERA")[:32]
    font_scale = max(0.45, min(width, height) / 420.0)
    thickness = max(1, round(font_scale * 2))
    cv2.putText(
        tile,
        safe_title,
        (max(12, width // 18), max(30, height // 2 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (235, 241, 248),
        thickness,
        cv2.LINE_AA,
    )
    cv2.putText(
        tile,
        state,
        (max(12, width // 18), min(height - 18, height // 2 + 28)),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale * 0.72,
        (180, 196, 220),
        max(1, thickness - 1),
        cv2.LINE_AA,
    )
    return tile


class SharedMosaicStream:
    """讓相同 canonical layout 的瀏覽器共用一個 compositor 與 JPEG encoder。"""

    def __init__(
        self,
        profile,
        sources,
        *,
        stream_acquirer=acquire_camera_stream,
        on_stopped=None,
    ):
        self.profile = profile
        self.sources = tuple(sources)
        self.layout_key = (
            profile.name,
            tuple(source.camera_id for source in self.sources),
        )
        self._stream_acquirer = stream_acquirer
        self._on_stopped = on_stopped
        self._condition = threading.Condition()
        self._subscribers = 0
        self._latest_jpeg = None
        self._jpeg_version = 0
        self._compose_count = 0
        self._encode_failures = 0
        self._dropped_ticks = 0
        self._tile_states = {}
        self._stop_requested = False
        self._stopped = False
        self._thread = None

    @property
    def stopping_or_stopped(self):
        with self._condition:
            return self._stop_requested or self._stopped

    def subscribe(self):
        """新增 browser subscriber；第一位訂閱者才啟動 compositor。"""
        startup_error = None
        with self._condition:
            if self._stop_requested or self._stopped:
                return False
            self._subscribers += 1
            if self._thread is None:
                thread = threading.Thread(
                    target=self._run,
                    name="krtc-mosaic-" + self.profile.name,
                    daemon=True,
                )
                self._thread = thread
                try:
                    # 在同一把condition lock內完成啟動，避免其他subscriber
                    # 在thread尚未成功啟動前取得不可用的stream。
                    thread.start()
                except BaseException as exc:
                    self._subscribers -= 1
                    self._stop_requested = True
                    self._stopped = True
                    self._condition.notify_all()
                    startup_error = exc

        if startup_error is not None:
            if self._on_stopped is not None:
                self._on_stopped(self.layout_key, self)
            raise startup_error
        return True

    def unsubscribe(self):
        """最後一位訂閱者離開時立即停止，不疊加另一個15秒 retention。"""
        with self._condition:
            if self._subscribers == 0:
                return
            self._subscribers -= 1
            if self._subscribers == 0:
                self._stop_requested = True
            self._condition.notify_all()

    def wait_for_jpeg(self, last_version, timeout=2.0):
        """等待已共享的JPEG；Waitress worker不執行composition或encode。"""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while not self._stopped and self._jpeg_version <= last_version:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)

            if self._jpeg_version > last_version and self._latest_jpeg is not None:
                return self._jpeg_version, self._latest_jpeg
            return last_version, None

    def join(self, timeout=None):
        """僅供測試及受控cleanup等待daemon compositor結束。"""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def snapshot(self):
        """回傳不含RTSP資訊的process-local診斷狀態。"""
        with self._condition:
            return {
                "layout": self.profile.name,
                "camera_ids": list(self.layout_key[1]),
                "subscriber_count": self._subscribers,
                "jpeg_version": self._jpeg_version,
                "compose_count": self._compose_count,
                "encode_failures": self._encode_failures,
                "dropped_ticks": self._dropped_ticks,
                "tile_states": dict(self._tile_states),
                "stopped": self._stopped,
                "stop_requested": self._stop_requested,
            }

    def _should_stop(self):
        with self._condition:
            return self._stop_requested

    def _wait_until(self, deadline):
        with self._condition:
            while not self._stop_requested:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return True
                self._condition.wait(remaining)
            return False

    def _acquire_sources(self, acquired):
        """逐一取得Camera owner，讓外層finally永遠看得到部分成功清單。"""
        for source in self.sources:
            if self._should_stop():
                break
            if not source.rtsp_url:
                acquired.append(None)
                continue
            try:
                acquired.append(
                    self._stream_acquirer(source.camera_id, source.rtsp_url)
                )
            except Exception:
                acquired.append(None)

    def _compose(self, acquired_streams, tile_cache, now, canvas=None):
        profile = self.profile
        if canvas is None:
            canvas = np.zeros(
                (profile.canvas_height, profile.canvas_width, 3),
                dtype=np.uint8,
            )
        else:
            canvas.fill(0)
        x_bounds = _tile_bounds(profile.canvas_width, profile.columns)
        y_bounds = _tile_bounds(profile.canvas_height, profile.rows)
        tile_states = {}

        for slot_index in range(profile.camera_limit):
            row, column = divmod(slot_index, profile.columns)
            x_start, x_end = x_bounds[column], x_bounds[column + 1]
            y_start, y_end = y_bounds[row], y_bounds[row + 1]
            tile_width = x_end - x_start
            tile_height = y_end - y_start

            if slot_index >= len(self.sources):
                tile = placeholder_tile(
                    tile_width,
                    tile_height,
                    f"SLOT {slot_index + 1:02d}",
                    "EMPTY",
                )
                state = "empty"
            else:
                source = self.sources[slot_index]
                stream = acquired_streams[slot_index]
                cache = tile_cache.setdefault(
                    source.camera_id,
                    {"version": 0, "tile": None, "received_at": None},
                )
                frame = None
                if stream is not None:
                    try:
                        version, frame = stream.wait_for_frame(
                            cache["version"],
                            timeout=0.0,
                        )
                    except Exception:
                        version = cache["version"]
                    if frame is not None:
                        try:
                            resized_tile = fit_frame_to_tile(
                                frame,
                                tile_width,
                                tile_height,
                            )
                        except Exception:
                            resized_tile = None
                        if resized_tile is not None:
                            cache["version"] = version
                            cache["tile"] = resized_tile
                            cache["received_at"] = now

                age = (
                    now - cache["received_at"]
                    if cache["received_at"] is not None
                    else None
                )
                if cache["tile"] is not None and age <= profile.stale_after_seconds:
                    tile = cache["tile"]
                    state = "frame"
                else:
                    stopped = bool(
                        stream is None
                        or getattr(stream, "stopped", False)
                        or getattr(stream, "connection_state", "") == "failed"
                    )
                    label = "NO SIGNAL" if stopped or age is not None else "CONNECTING"
                    tile = placeholder_tile(
                        tile_width,
                        tile_height,
                        source.camera_code,
                        label,
                    )
                    state = "no_signal" if label == "NO SIGNAL" else "connecting"

            canvas[y_start:y_end, x_start:x_end] = tile
            tile_states[slot_index] = state

        return canvas, tile_states

    def _publish(self, jpeg_bytes, tile_states):
        with self._condition:
            self._latest_jpeg = jpeg_bytes
            self._jpeg_version += 1
            self._compose_count += 1
            self._tile_states = tile_states
            self._condition.notify_all()

    def _run(self):
        acquired_streams = []
        try:
            # 所有可能失敗的bootstrap均置於finally保護範圍內。
            tile_cache = {}
            canvas = np.zeros(
                (self.profile.canvas_height, self.profile.canvas_width, 3),
                dtype=np.uint8,
            )
            frame_interval = 1.0 / self.profile.fps
            next_frame_at = time.monotonic()
            self._acquire_sources(acquired_streams)
            while not self._should_stop():
                if not self._wait_until(next_frame_at):
                    return

                tick_started = time.monotonic()
                canvas, tile_states = self._compose(
                    acquired_streams,
                    tile_cache,
                    tick_started,
                    canvas,
                )
                encode_success, buffer = cv2.imencode(
                    ".jpg",
                    canvas,
                    [cv2.IMWRITE_JPEG_QUALITY, self.profile.jpeg_quality],
                )
                if not encode_success:
                    with self._condition:
                        self._encode_failures += 1
                    raise RuntimeError("Mosaic JPEG encoding failed")
                self._publish(buffer.tobytes(), tile_states)

                next_frame_at += frame_interval
                now = time.monotonic()
                if next_frame_at < now:
                    missed = int((now - next_frame_at) / frame_interval) + 1
                    with self._condition:
                        self._dropped_ticks += missed
                    next_frame_at += missed * frame_interval
        finally:
            for stream in acquired_streams:
                if stream is not None:
                    try:
                        stream.unsubscribe()
                    except Exception:
                        pass
            with self._condition:
                self._stopped = True
                self._condition.notify_all()
            if self._on_stopped is not None:
                self._on_stopped(self.layout_key, self)


class MosaicRegistry:
    """原子管理canonical layout，避免相同layout建立多個encoder。"""

    def __init__(
        self,
        stream_factory=SharedMosaicStream,
        *,
        max_active_layouts=MOSAIC_MAX_ACTIVE_LAYOUTS,
        max_session_layouts=MOSAIC_MAX_SESSION_LAYOUTS,
        acquire_timeout=MOSAIC_ACQUIRE_TIMEOUT_SECONDS,
    ):
        self._stream_factory = stream_factory
        self._max_active_layouts = int(max_active_layouts)
        self._max_session_layouts = int(max_session_layouts)
        self._acquire_timeout = float(acquire_timeout)
        self._streams = {}
        self._session_layouts = {}
        self._condition = threading.Condition()

    def _remove_if_current(self, layout_key, stream):
        with self._condition:
            if self._streams.get(layout_key) is stream:
                self._streams.pop(layout_key, None)
            self._condition.notify_all()

    def _reserve_session(self, session_key, layout_key):
        if session_key is None:
            return
        layouts = self._session_layouts.setdefault(session_key, {})
        layouts[layout_key] = layouts.get(layout_key, 0) + 1

    def _release_session(self, session_key, layout_key):
        if session_key is None:
            return
        layouts = self._session_layouts.get(session_key)
        if not layouts or layout_key not in layouts:
            return
        layouts[layout_key] -= 1
        if layouts[layout_key] <= 0:
            layouts.pop(layout_key, None)
        if not layouts:
            self._session_layouts.pop(session_key, None)

    def _wait_for_capacity(self, deadline, error_type):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise error_type()
        self._condition.wait(remaining)

    def acquire(self, profile, sources, session_key=None):
        layout_key = (
            profile.name,
            tuple(source.camera_id for source in sources),
        )
        deadline = time.monotonic() + max(0.0, self._acquire_timeout)
        while True:
            with self._condition:
                session_layouts = self._session_layouts.get(session_key, {})
                if (
                    session_key is not None
                    and layout_key not in session_layouts
                    and len(session_layouts) >= self._max_session_layouts
                ):
                    self._wait_for_capacity(deadline, MosaicSessionCapacityError)
                    continue

                stream = self._streams.get(layout_key)
                if stream is not None and stream.stopping_or_stopped:
                    if stream.snapshot()["stopped"]:
                        self._streams.pop(layout_key, None)
                        stream = None
                    else:
                        # Condition.wait會釋放registry lock；不得在此join compositor。
                        self._wait_for_capacity(deadline, MosaicLayoutBusyError)
                        continue

                if stream is None:
                    if len(self._streams) >= self._max_active_layouts:
                        self._wait_for_capacity(deadline, MosaicCapacityError)
                        continue
                    stream = self._stream_factory(
                        profile,
                        sources,
                        on_stopped=self._remove_if_current,
                    )
                    self._streams[layout_key] = stream
                self._reserve_session(session_key, layout_key)

            try:
                if stream.subscribe():
                    return stream
            except BaseException:
                with self._condition:
                    self._release_session(session_key, layout_key)
                    self._condition.notify_all()
                raise

            with self._condition:
                self._release_session(session_key, layout_key)
                self._condition.notify_all()

    def release(self, stream, session_key=None):
        """釋放一次Mosaic訂閱及其session配額。"""
        try:
            stream.unsubscribe()
        finally:
            with self._condition:
                self._release_session(session_key, stream.layout_key)
                self._condition.notify_all()

    def snapshot(self):
        with self._condition:
            streams = list(self._streams.items())
        return {layout_key: stream.snapshot() for layout_key, stream in streams}


_mosaic_registry = MosaicRegistry()


def acquire_mosaic_stream(profile_name, sources, session_key=None):
    """驗證server profile後，取得已訂閱的共享Mosaic stream。"""
    profile = MOSAIC_PROFILES.get(profile_name)
    if profile is None:
        raise ValueError("Unsupported mosaic profile")
    sources = tuple(sources)
    camera_ids = [source.camera_id for source in sources]
    if len(sources) > profile.camera_limit:
        raise ValueError("Mosaic camera limit exceeded")
    if len(camera_ids) != len(set(camera_ids)):
        raise ValueError("Duplicate mosaic camera")
    return _mosaic_registry.acquire(profile, sources, session_key=session_key)


def release_mosaic_stream(stream, session_key=None):
    """釋放全域registry中的一次Mosaic訂閱。"""
    _mosaic_registry.release(stream, session_key=session_key)


def active_mosaic_snapshot():
    """回傳credential-free registry狀態，供測試與後續telemetry使用。"""
    return _mosaic_registry.snapshot()
