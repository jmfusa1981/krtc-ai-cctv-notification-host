import ctypes
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from django.conf import settings

from .mediamtx import camera_path_name


RUNNING = "running"
STARTING = "starting"
STALE = "stale"
FAILED = "failed"
STOPPED = "stopped"
_VALID_STATES = {RUNNING, STARTING, STALE, FAILED, STOPPED}


@dataclass(frozen=True)
class ProcessSnapshot:
    """保存程序身分證據，命令列僅供比對且不輸出至診斷結果。"""

    alive: bool
    name: str = ""
    started_at: Optional[datetime] = None
    command_line: Optional[str] = None


def bridge_status_directory():
    """回傳 bridge runtime 狀態目錄。"""

    return Path(
        getattr(
            settings,
            "KRTC_MEDIAMTX_BRIDGE_STATUS_DIR",
            Path(settings.BASE_DIR) / "runtime" / "mediamtx" / "bridges",
        )
    )


def _parse_datetime(value):
    """將 runtime ISO 時間正規化為 UTC；無效資料不推測。"""

    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _windows_process_snapshot(process_id):
    """以低權限 Win32 API 讀取執行檔與建立時間，避免依賴 PID 存在性。"""

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    process_handle = kernel32.OpenProcess(0x1000, False, process_id)
    if not process_handle:
        return ProcessSnapshot(False)

    executable_buffer = ctypes.create_unicode_buffer(32768)
    executable_size = ctypes.c_ulong(len(executable_buffer))
    creation = FileTime()
    exit_time = FileTime()
    kernel_time = FileTime()
    user_time = FileTime()
    try:
        executable_ok = kernel32.QueryFullProcessImageNameW(
            process_handle,
            0,
            executable_buffer,
            ctypes.byref(executable_size),
        )
        time_ok = kernel32.GetProcessTimes(
            process_handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
    finally:
        kernel32.CloseHandle(process_handle)

    process_name = (
        Path(executable_buffer.value).name.lower() if executable_ok else ""
    )
    started_at = None
    if time_ok:
        windows_ticks = (creation.high << 32) | creation.low
        unix_seconds = (windows_ticks / 10_000_000) - 11_644_473_600
        started_at = datetime.fromtimestamp(unix_seconds, timezone.utc)
    return ProcessSnapshot(True, process_name, started_at)


def _posix_process_snapshot(process_id):
    """在 POSIX 測試／部署環境讀取 procfs，缺少 procfs 時採保守 stale。"""

    process_root = Path("/proc") / str(process_id)
    if not process_root.exists():
        return ProcessSnapshot(False)
    try:
        process_name = Path(os.readlink(process_root / "exe")).name.lower()
    except OSError:
        process_name = ""
    try:
        command_line = (process_root / "cmdline").read_bytes().replace(
            b"\x00", b" "
        ).decode("utf-8", errors="replace")
    except OSError:
        command_line = None
    return ProcessSnapshot(True, process_name, None, command_line)


def inspect_process(process_id):
    """取得單一 PID 的程序快照；權限不足時不把未知程序誤認為 bridge。"""

    if process_id <= 0:
        return ProcessSnapshot(False)
    if os.name == "nt":
        return _windows_process_snapshot(process_id)
    return _posix_process_snapshot(process_id)


def reconcile_bridge_record(payload, process_snapshot=None, status_file=""):
    """以 OS reality 對帳一筆 runtime JSON，產生不含憑證的有效狀態。"""

    camera_code = str(payload.get("CameraCode", "")).strip().upper()
    source_codec = str(payload.get("SourceCodec", "")).strip().upper()
    bridge_mode = str(payload.get("BridgeMode", "")).strip().lower()
    declared_state = str(
        payload.get("DeclaredState") or payload.get("State") or ""
    ).lower()
    process_id = int(payload.get("ProcessId") or 0)
    process_started_at = str(payload.get("ProcessStartedAt", ""))
    publish_path = str(payload.get("PublishPath", "")).strip().lower()
    canonical_path = camera_path_name(camera_code)
    snapshot = process_snapshot or inspect_process(process_id)

    expected_started_at = _parse_datetime(process_started_at)
    process_start_match = None
    if snapshot.alive and expected_started_at and snapshot.started_at:
        process_start_match = abs(
            (snapshot.started_at - expected_started_at).total_seconds()
        ) <= 2
    elif snapshot.alive:
        process_start_match = os.name != "nt" and bool(expected_started_at)

    process_name_match = snapshot.name.lower() in {"ffmpeg", "ffmpeg.exe"}
    command_line_match = None
    if snapshot.command_line is not None and publish_path:
        expected_destination = f"rtsp://127.0.0.1:8554/{publish_path}"
        command_line_match = expected_destination in snapshot.command_line

    last_error = str(payload.get("LastError", ""))[:200]
    if declared_state == RUNNING:
        if not snapshot.alive:
            effective_state = STALE
            last_error = "stale_process_missing"
        elif not process_name_match:
            effective_state = STALE
            last_error = "stale_process_not_ffmpeg"
        elif process_start_match is not True:
            effective_state = STALE
            last_error = "stale_process_start_mismatch"
        elif command_line_match is False:
            effective_state = STALE
            last_error = "stale_publish_path_mismatch"
        else:
            effective_state = RUNNING
    elif declared_state == STARTING:
        effective_state = STARTING if snapshot.alive else STALE
        if effective_state == STALE:
            last_error = "stale_starting_process_missing"
    elif declared_state == FAILED or payload.get("ExitCode") not in (None, 0):
        effective_state = FAILED
    elif declared_state in {STALE, STOPPED}:
        effective_state = declared_state
    else:
        effective_state = STOPPED

    return {
        "camera_code": camera_code,
        "canonical_path": canonical_path,
        "declared_state": declared_state or STOPPED,
        "effective_state": effective_state,
        "state": effective_state,
        "process_id": process_id,
        "process_alive": snapshot.alive,
        "process_name": snapshot.name,
        "process_name_match": process_name_match,
        "process_start_match": process_start_match,
        "command_line_match": command_line_match,
        "process_started_at": process_started_at,
        "source_codec": source_codec,
        "bridge_mode": bridge_mode,
        "publish_path": publish_path,
        "is_canonical_path": bool(canonical_path and publish_path == canonical_path),
        "exit_code": payload.get("ExitCode"),
        "last_error": last_error,
        "profile": str(payload.get("Profile", "")),
        "output_width": int(payload.get("OutputWidth") or 0),
        "output_height": int(payload.get("OutputHeight") or 0),
        "output_fps": int(payload.get("OutputFps") or payload.get("TranscodeFps") or 0),
        "status_file": status_file,
    }


def load_bridge_statuses(camera_codes=None):
    """掃描所有 camera bridge 記錄並逐筆驗證，不以 JSON running 作唯一 truth。"""

    allowed_codes = (
        {str(code).strip().upper() for code in camera_codes}
        if camera_codes is not None
        else None
    )
    statuses = []
    status_directory = bridge_status_directory()
    if not status_directory.is_dir():
        return statuses
    for status_path in sorted(status_directory.glob("*.json")):
        try:
            payload = json.loads(status_path.read_text(encoding="ascii"))
            status = reconcile_bridge_record(payload, status_file=status_path.name)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if (
            not status["camera_code"]
            or not status["canonical_path"]
            or status["source_codec"] not in {"H264", "H265"}
            or status["bridge_mode"] not in {"copy", "transcode"}
            or status["declared_state"] not in _VALID_STATES
            or (
                allowed_codes is not None
                and status["camera_code"] not in allowed_codes
            )
        ):
            continue
        statuses.append(status)
    return statuses


def select_effective_bridge_statuses(bridge_statuses, transition, camera_codes):
    """逐 Camera 選擇有效 owner；原生 H264 canonical copy 永遠優先於歷史 A/B。"""

    selected = []
    transition_cameras = transition.get("cameras", {})
    for camera_code in sorted({str(code).upper() for code in camera_codes}):
        candidates = [
            item for item in bridge_statuses if item.get("camera_code") == camera_code
        ]
        if not candidates:
            continue
        active_path = transition_cameras.get(camera_code, {}).get("active_path")

        def priority(item):
            running = item.get("effective_state", item.get("state")) == RUNNING
            is_canonical_path = item.get("is_canonical_path")
            if is_canonical_path is None:
                is_canonical_path = item.get("publish_path") == camera_path_name(
                    camera_code
                )
            canonical_h264 = (
                is_canonical_path
                and item.get("source_codec") == "H264"
                and item.get("bridge_mode") == "copy"
            )
            return (
                1 if running and canonical_h264 else 0,
                1 if running and item.get("publish_path") == active_path else 0,
                1 if running else 0,
                1 if canonical_h264 else 0,
                1 if item.get("publish_path") == active_path else 0,
                item.get("process_started_at", ""),
            )

        selected.append(max(candidates, key=priority))
    return selected


def effective_camera_path(camera_code, bridge_statuses, transition):
    """回傳可播放 active path；無有效 alternate owner 時安全回到 canonical。"""

    canonical_path = camera_path_name(camera_code)
    selected = select_effective_bridge_statuses(
        bridge_statuses,
        transition,
        [camera_code],
    )
    if not selected:
        return canonical_path
    bridge = selected[0]
    if bridge.get("effective_state", bridge.get("state")) != RUNNING:
        return canonical_path
    return bridge.get("publish_path") or canonical_path
