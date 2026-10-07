from __future__ import annotations

import hmac
import json
import logging
import time
from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import RLock
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core.management.base import CommandError


logger = logging.getLogger(__name__)

FAKE_NVR_CAMERAS = (
    {"CameraCode": "CAM-001", "IP": "192.168.6.93", "Channel": 1},
    {"CameraCode": "CAM-002", "IP": "192.168.6.90", "Channel": 2},
    {"CameraCode": "CAM-003", "IP": "192.168.6.94", "Channel": 3},
    {"CameraCode": "CAM-004", "IP": "192.168.6.92", "Channel": 4},
)

# 由 ffmpeg 產生的 16x16、0.2 秒黑畫面 H.264 MP4，僅 1545 bytes。
# 內嵌 fixture 讓 Lab 與 CI 不需要網路，也不強制要求 ffmpeg。
_FAKE_MP4_BASE64 = (
    "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAMVbW9vdgAAAGxtdmhk"
    "AAAAAAAAAAAAAAAAAAAD6AAAAMgAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAA"
    "AAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAgAAAj90cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAAMgAAAAA"
    "AAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAA"
    "ABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAADIAAAAAAABAAAAAAG3"
    "bWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAAoAAAACABVxAAAAAAALWhkbHIAAAAA"
    "AAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABYm1pbmYAAAAUdm1o"
    "ZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAA"
    "AQAAASJzdGJsAAAAvnN0c2QAAAAAAAAAAQAAAK5hdmMxAAAAAAAAAAEAAAAAAAAA"
    "AAAAAAAAAAAAABAAEABIAAAASAAAAAAAAAABFUxhdmM2Mi4yOC4xMDAgbGlieDI2"
    "NAAAAAAAAAAAAAAAGP//AAAANGF2Y0MBZAAK/+EAF2dkAAqs2V7ARAAAAwAEAAAD"
    "ACg8SJZYAQAGaOvjyyLA/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAA"
    "AG6gAAAAAAAAABhzdHRzAAAAAAAAAAEAAAABAAAIAAAAABxzdHNjAAAAAAAAAAEA"
    "AAABAAAAAQAAAAEAAAAUc3RzegAAAAAAAALEAAAAAQAAABRzdGNvAAAAAAAAAAEA"
    "AANFAAAAYnVkdGEAAABabWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwA"
    "AAAAAAAAAAAAAAAtaWxzdAAAACWpdG9vAAAAHWRhdGEAAAABAAAAAExhdmY2Mi4x"
    "Mi4xMDAAAAAIZnJlZQAAAsxtZGF0AAACrQYF//+p3EXpvebZSLeWLNgg2SPu73gy"
    "NjQgLSBjb3JlIDE2NSByMzIyMyAwNDgwY2IwIC0gSC4yNjQvTVBFRy00IEFWQyBj"
    "b2RlYyAtIENvcHlsZWZ0IDIwMDMtMjAyNSAtIGh0dHA6Ly93d3cudmlkZW9sYW4u"
    "b3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTMgZGVibG9jaz0x"
    "OjA6MCBhbmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lf"
    "cmQ9MS4wMDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0x"
    "IHRyZWxsaXM9MSA4eDhkY3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0X3Bz"
    "a2lwPTEgY2hyb21hX3FwX29mZnNldD0tMiB0aHJlYWRzPTEgbG9va2FoZWFkX3Ro"
    "cmVhZHM9MSBzbGljZWRfdGhyZWFkcz0wIG5yPTAgZGVjaW1hdGU9MSBpbnRlcmxh"
    "Y2VkPTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0cmFpbmVkX2ludHJhPTAgYmZyYW1l"
    "cz0zIGJfcHlyYW1pZD0yIGJfYWRhcHQ9MSBiX2JpYXM9MCBkaXJlY3Q9MSB3ZWln"
    "aHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5aW50PTI1MCBrZXlpbnRfbWlu"
    "PTUgc2NlbmVjdXQ9NDAgaW50cmFfcmVmcmVzaD0wIHJjX2xvb2thaGVhZD00MCBy"
    "Yz1jcmYgbWJ0cmVlPTEgY3JmPTIzLjAgcWNvbXA9MC42MCBxcG1pbj0wIHFwbWF4"
    "PTY5IHFwc3RlcD00IGlwX3JhdGlvPTEuNDAgYXE9MToxLjAwAIAAAAAPZYiEAD//"
    "/vdonwKbXmG5"
)


def fake_mp4_bytes() -> bytes:
    """回傳可重複使用的小型有效 MP4 fixture。"""

    return b64decode(_FAKE_MP4_BASE64)


def ensure_fake_nvr_allowed() -> None:
    """正式環境無條件拒絕啟動 Fake NVR。"""

    if not settings.DEBUG or getattr(settings, "KRTC_PRODUCTION", False):
        raise CommandError("Fake NVR is available only when DEBUG=True outside production.")


@dataclass(frozen=True)
class FakeExportJob:
    export_id: str
    channel: int
    start_time: str
    end_time: str
    video_format: str
    created_at: float


class FakeNvrState:
    """以鎖保護每筆獨立匯出工作，供 ThreadingHTTPServer 併發存取。"""

    def __init__(self, *, delay_seconds: float = 5.0, clock=time.monotonic):
        self.delay_seconds = max(0.0, float(delay_seconds))
        self.clock = clock
        self._lock = RLock()
        self._next_export_id = 1001
        self._jobs: dict[str, FakeExportJob] = {}

    @property
    def export_count(self) -> int:
        with self._lock:
            return len(self._jobs)

    def create_export(
        self,
        *,
        channel: int,
        start_time: str,
        end_time: str,
        video_format: str,
    ) -> FakeExportJob:
        valid_channels = {camera["Channel"] for camera in FAKE_NVR_CAMERAS}
        if channel not in valid_channels:
            raise ValueError("Invalid channel.")
        try:
            start_value = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%S")
            end_value = datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%S")
        except ValueError as exc:
            raise ValueError("Invalid start_time or end_time.") from exc
        if end_value <= start_value:
            raise ValueError("end_time must be later than start_time.")
        if video_format.upper() != "MP4":
            raise ValueError("Only MP4 is supported.")

        with self._lock:
            export_id = str(self._next_export_id)
            self._next_export_id += 1
            job = FakeExportJob(
                export_id=export_id,
                channel=channel,
                start_time=start_time,
                end_time=end_time,
                video_format="MP4",
                created_at=self.clock(),
            )
            self._jobs[export_id] = job
            return job

    def job_status(self, export_id: str) -> dict[str, int]:
        with self._lock:
            job = self._jobs.get(str(export_id))
            if job is None:
                return {"Status": -1, "FFmpeg": 0, "Rate": 0}
            elapsed = max(0.0, self.clock() - job.created_at)
            if elapsed >= self.delay_seconds:
                return {"Status": 1, "FFmpeg": 0, "Rate": 100}
            rate = int(min(99, (elapsed / max(self.delay_seconds, 0.001)) * 100))
            return {"Status": 0, "FFmpeg": 1, "Rate": rate}

    def is_ready(self, export_id: str) -> bool:
        return self.job_status(export_id)["Status"] == 1


class FakeNvrHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address,
        *,
        state: FakeNvrState,
        username: str,
        password: str,
        mp4_content: bytes | None = None,
    ):
        self.state = state
        self.expected_authorization = "Basic " + b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        self.mp4_content = mp4_content or fake_mp4_bytes()
        super().__init__(server_address, FakeNvrRequestHandler)


class FakeNvrRequestHandler(BaseHTTPRequestHandler):
    server: FakeNvrHttpServer

    def do_GET(self):
        if not self._authenticated():
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="Fake NVR Lab"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if parsed.path == "/cam_list.cgi":
            self._send_json(
                HTTPStatus.OK,
                {"Status": 1, "Cameras": list(FAKE_NVR_CAMERAS)},
            )
            return
        if parsed.path != "/export.cgi":
            self._send_json(HTTPStatus.NOT_FOUND, {"Message": "Not found."})
            return
        self._handle_export(query)

    def _authenticated(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, self.server.expected_authorization)

    def _handle_export(self, query: dict[str, list[str]]) -> None:
        export_id = self._single(query, "ID")
        if export_id:
            if self._single(query, "action") == "download":
                self._handle_download(export_id)
                return
            self._send_json(HTTPStatus.OK, self.server.state.job_status(export_id))
            return

        try:
            channel = int(self._single(query, "channel") or "")
            job = self.server.state.create_export(
                channel=channel,
                start_time=self._single(query, "start_time"),
                end_time=self._single(query, "end_time"),
                video_format=self._single(query, "format"),
            )
        except (TypeError, ValueError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"Message": str(exc)})
            return
        self._send_json(HTTPStatus.OK, {"ID": int(job.export_id)})

    def _handle_download(self, export_id: str) -> None:
        status = self.server.state.job_status(export_id)
        if status["Status"] == -1:
            self._send_json(HTTPStatus.NOT_FOUND, {"Message": "Export ID not found."})
            return
        if not self.server.state.is_ready(export_id):
            self._send_json(
                HTTPStatus.CONFLICT,
                {"Message": "not exist or not finish."},
            )
            return

        content = self.server.mp4_content
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(content)))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="fake_export_{export_id}.mp4"',
        )
        self.end_headers()
        self.wfile.write(content)

    @staticmethod
    def _single(query: dict[str, list[str]], name: str) -> str:
        values = query.get(name, [])
        return values[0] if len(values) == 1 else ""

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        # 不記錄 request headers、Authorization 或任何認證內容。
        logger.debug("Fake NVR request handled path=%s", urlsplit(self.path).path)
