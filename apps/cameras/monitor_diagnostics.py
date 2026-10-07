import csv
import ctypes
import io
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from django.conf import settings

from .mediamtx import (
    camera_path_name,
    phase1_camera_codes,
    player_url_for_path,
)
from .monitor_profiles import (
    get_active_monitor_profile,
    load_monitor_profile_config,
)
from .monitor_transitions import load_monitor_transition_state


def _read_json(url, timeout):
    """以短逾時讀取MediaMTX控制API，避免診斷阻塞服務。"""

    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _process_memory_bytes():
    """取得目前Django程序的常駐記憶體，平台不支援時回傳None。"""

    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process_handle = ctypes.windll.kernel32.GetCurrentProcess()
        success = ctypes.windll.psapi.GetProcessMemoryInfo(
            process_handle,
            ctypes.byref(counters),
            counters.cb,
        )
        return int(counters.WorkingSetSize) if success else None

    try:
        import resource

        maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(maximum_rss * 1024)
    except (ImportError, OSError):
        return None


def _ffmpeg_process_count():
    """只計算FFmpeg程序，不讀取或輸出可能含憑證的命令列。"""

    if os.name != "nt":
        return None
    completed = subprocess.run(
        [
            "tasklist.exe",
            "/FI",
            "IMAGENAME eq ffmpeg.exe",
            "/FO",
            "CSV",
            "/NH",
        ],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        return None
    rows = csv.reader(io.StringIO(completed.stdout))
    return sum(
        1
        for row in rows
        if row and row[0].strip().lower() == "ffmpeg.exe"
    )


def _process_is_running(process_id):
    """不讀取命令列，只確認狀態快照中的程序是否仍存在。"""

    if process_id <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        process_handle = kernel32.OpenProcess(
            0x1000,
            False,
            process_id,
        )
        if not process_handle:
            return False
        kernel32.CloseHandle(process_handle)
        return True
    try:
        os.kill(process_id, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _process_started_at(process_id):
    """取得程序建立時間，以PID與時間共同避免PID重用誤判。"""

    if process_id <= 0 or os.name != "nt":
        return None

    class FileTime(ctypes.Structure):
        _fields_ = [
            ("low", ctypes.c_ulong),
            ("high", ctypes.c_ulong),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_ulong,
    ]
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    process_handle = kernel32.OpenProcess(0x1000, False, process_id)
    if not process_handle:
        return None
    creation = FileTime()
    exit_time = FileTime()
    kernel_time = FileTime()
    user_time = FileTime()
    try:
        success = kernel32.GetProcessTimes(
            process_handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
    finally:
        kernel32.CloseHandle(process_handle)
    if not success:
        return None
    windows_ticks = (creation.high << 32) | creation.low
    unix_seconds = (windows_ticks / 10_000_000) - 11_644_473_600
    return datetime.fromtimestamp(unix_seconds, timezone.utc)


def _process_identity_matches(process_id, expected_started_at):
    """確認PID存在且建立時間符合狀態快照。"""

    if not expected_started_at or not _process_is_running(process_id):
        return False
    if os.name != "nt":
        return True
    actual_started_at = _process_started_at(process_id)
    if actual_started_at is None:
        return False
    try:
        expected = datetime.fromisoformat(
            str(expected_started_at).replace("Z", "+00:00")
        )
    except ValueError:
        return False
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)
    return abs((actual_started_at - expected).total_seconds()) <= 2


def _load_bridge_statuses():
    """讀取bridge產生的安全狀態快照，忽略來源網址與憑證欄位。"""

    status_directory = Path(
        getattr(
            settings,
            "KRTC_MEDIAMTX_BRIDGE_STATUS_DIR",
            Path(settings.BASE_DIR) / "runtime" / "mediamtx" / "bridges",
        )
    )
    if not status_directory.is_dir():
        return []

    statuses = []
    for status_path in sorted(status_directory.glob("CAM-*.json")):
        try:
            payload = json.loads(status_path.read_text(encoding="ascii"))
            camera_code = str(payload.get("CameraCode", "")).upper()
            source_codec = str(payload.get("SourceCodec", "")).upper()
            bridge_mode = str(payload.get("BridgeMode", "")).lower()
            state = str(payload.get("State", "")).lower()
            process_id = int(payload.get("ProcessId") or 0)
            process_started_at = str(payload.get("ProcessStartedAt", ""))
            exit_code = payload.get("ExitCode")
            last_error = str(payload.get("LastError", ""))[:200]
            profile = str(payload.get("Profile", ""))
            output_width = int(payload.get("OutputWidth") or 0)
            output_height = int(payload.get("OutputHeight") or 0)
            output_fps = int(
                payload.get("OutputFps") or payload.get("TranscodeFps") or 0
            )
            publish_path = str(payload.get("PublishPath", "")).strip().lower()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if (
            camera_code not in phase1_camera_codes()
            or source_codec not in {"H264", "H265"}
            or bridge_mode not in {"copy", "transcode"}
            or state not in {"running", "stopped"}
        ):
            continue
        if state == "running" and not _process_identity_matches(
            process_id,
            process_started_at,
        ):
            state = "stopped"
            last_error = "stale_process_identity"
        statuses.append(
            {
                "camera_code": camera_code,
                "source_codec": source_codec,
                "bridge_mode": bridge_mode,
                "state": state,
                "process_id": process_id,
                "process_started_at": process_started_at,
                "exit_code": exit_code,
                "last_error": last_error,
                "profile": profile,
                "output_width": output_width,
                "output_height": output_height,
                "output_fps": output_fps,
                "publish_path": publish_path,
            }
        )
    return statuses


def _select_active_bridge_statuses(bridge_statuses, transition):
    """依A/B狀態只選目前active bridge，避免轉場雙程序被誤算為crash。"""

    selected = []
    for camera_code in sorted(phase1_camera_codes()):
        candidates = [
            item
            for item in bridge_statuses
            if item["camera_code"] == camera_code
        ]
        if not candidates:
            continue
        active_path = transition["cameras"].get(camera_code, {}).get(
            "active_path"
        )
        active_candidate = next(
            (
                item
                for item in candidates
                if item.get("publish_path") == active_path
            ),
            None,
        )
        selected.append(active_candidate or candidates[-1])
    return selected


def _with_diagnostic_output_semantics(
    bridge_status,
    requested_profile,
    requested_values,
):
    """分離要求profile與bridge實際輸出，避免copy路徑誤報縮放結果。"""

    item = dict(bridge_status)
    bridge_mode = item.get("bridge_mode", "unknown")
    if bridge_mode == "copy":
        actual_output = "source-copy"
    elif (
        bridge_mode == "transcode"
        and item.get("output_width", 0) > 0
        and item.get("output_height", 0) > 0
        and item.get("output_fps", 0) > 0
    ):
        actual_output = (
            f"{item['output_width']}x{item['output_height']}"
            f"@{item['output_fps']}"
        )
    else:
        actual_output = "unknown"
    item.update(
        {
            "requested_profile": requested_profile,
            "requested_width": int(requested_values["width"]),
            "requested_height": int(requested_values["height"]),
            "requested_fps": int(requested_values["fps"]),
            "actual_bridge_mode": bridge_mode,
            "actual_output": actual_output,
        }
    )
    return item


def collect_monitor_media_diagnostics():
    """彙整Monitor media mode、MediaMTX path/session與程序資源。"""

    media_mode = getattr(settings, "KRTC_MONITOR_MEDIA_MODE", "legacy")
    fallback_enabled = bool(
        getattr(settings, "KRTC_MONITOR_MOSAIC_FALLBACK", True)
    )
    all_bridge_statuses = _load_bridge_statuses()
    monitor_profile_config = load_monitor_profile_config()
    requested_profile = get_active_monitor_profile()
    active_profile_values = monitor_profile_config["profiles"][requested_profile]
    transition = load_monitor_transition_state()
    active_profile = transition.get("active_profile") or requested_profile
    if active_profile not in monitor_profile_config["profiles"]:
        active_profile = requested_profile
    bridge_statuses = _select_active_bridge_statuses(
        all_bridge_statuses,
        transition,
    )
    diagnostic_bridge_statuses = [
        _with_diagnostic_output_semantics(
            item,
            requested_profile,
            active_profile_values,
        )
        for item in bridge_statuses
    ]
    running_bridge_statuses = [
        item for item in bridge_statuses if item["state"] == "running"
    ]
    result = {
        "monitor_media_mode": media_mode,
        "active_profile": active_profile,
        "profile_transition_state": transition["profile_transition_state"],
        "profile_transition_from": transition["profile_transition_from"],
        "profile_transition_to": transition["profile_transition_to"],
        "profile_transition_started_at": transition[
            "profile_transition_started_at"
        ],
        "profile_transition_camera_count": transition[
            "profile_transition_camera_count"
        ],
        "mediamtx_enabled": bool(
            getattr(settings, "KRTC_MEDIAMTX_ENABLED", False)
        ),
        "fallback_enabled": fallback_enabled,
        "mediamtx_reachable": False,
        "path_count": 0,
        "ready_path_count": 0,
        "webrtc_session_count": 0,
        "active_reader_count": 0,
        "active_visible_camera_count": 0,
        "ffmpeg_bridge_process_count": _ffmpeg_process_count(),
        "transcoding_count": sum(
            1
            for item in running_bridge_statuses
            if item["bridge_mode"] == "transcode"
        ),
        "bridges": diagnostic_bridge_statuses,
        "django_process": {
            "pid": os.getpid(),
            "cpu_seconds": round(time.process_time(), 3),
            "memory_bytes": _process_memory_bytes(),
        },
        "paths": [],
        "error": "",
    }

    api_base_url = str(
        getattr(settings, "KRTC_MEDIAMTX_API_BASE_URL", "")
    ).rstrip("/")
    parsed_api_url = urlsplit(api_base_url)
    if (
        parsed_api_url.scheme not in {"http", "https"}
        or not parsed_api_url.netloc
        or parsed_api_url.username
        or parsed_api_url.password
    ):
        result["error"] = "invalid_mediamtx_api_url"
        return result

    timeout = float(
        getattr(settings, "KRTC_MEDIAMTX_API_TIMEOUT_SECONDS", 3)
    )
    try:
        paths_payload = _read_json(f"{api_base_url}/v3/paths/list", timeout)
        sessions_payload = _read_json(
            f"{api_base_url}/v3/webrtc/sessions/list",
            timeout,
        )
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        result["error"] = f"mediamtx_unreachable:{type(exc).__name__}"
        return result

    result["mediamtx_reachable"] = True
    path_items = paths_payload.get("items") or []
    session_items = sessions_payload.get("items") or []
    items_by_name = {
        str(item.get("name", "")): item
        for item in path_items
        if item.get("name")
    }
    visible_paths = set()
    bridge_by_camera = {
        item["camera_code"]: item
        for item in diagnostic_bridge_statuses
    }

    for camera_code in sorted(phase1_camera_codes()):
        path_name = camera_path_name(camera_code)
        item = items_by_name.get(path_name, {})
        readers = item.get("readers") or []
        reader_count = len(readers)
        ready = bool(item.get("online", item.get("ready", False)))
        bridge_status = bridge_by_camera.get(camera_code, {})
        transition_camera = transition["cameras"].get(camera_code, {})
        if any(reader.get("type") == "webRTCSession" for reader in readers):
            visible_paths.add(path_name)
        result["paths"].append(
            {
                "camera_code": camera_code,
                "path": path_name,
                "ready": ready,
                "reader_count": reader_count,
                "inbound_bytes": int(item.get("inboundBytes") or 0),
                "outbound_bytes": int(item.get("outboundBytes") or 0),
                "source_codec": bridge_status.get("source_codec", "unknown"),
                "bridge_mode": bridge_status.get("bridge_mode", "unknown"),
                "actual_bridge_mode": bridge_status.get(
                    "bridge_mode",
                    "unknown",
                ),
                "bridge_state": bridge_status.get("state", "unknown"),
                "profile": active_profile,
                "requested_width": int(active_profile_values["width"]),
                "requested_height": int(active_profile_values["height"]),
                "requested_fps": int(active_profile_values["fps"]),
                "actual_output": bridge_status.get(
                    "actual_output",
                    "unknown",
                ),
                "active_path": transition_camera.get(
                    "active_path",
                    path_name,
                ),
                "next_path": transition_camera.get("next_path"),
                "transition_state": transition_camera.get(
                    "transition_state",
                    "idle",
                ),
            }
        )

    result["path_count"] = len(path_items)
    result["ready_path_count"] = sum(
        1 for item in result["paths"] if item["ready"]
    )
    result["webrtc_session_count"] = int(
        sessions_payload.get("itemCount", len(session_items))
    )
    result["active_reader_count"] = sum(
        item["reader_count"] for item in result["paths"]
    )
    result["active_visible_camera_count"] = len(visible_paths)
    return result


def collect_mediamtx_path_readiness():
    """取得前端啟動所需的安全path ready快照。"""

    result = {
        "reachable": False,
        "paths": {},
        "path_details": {},
        "transition": load_monitor_transition_state(),
        "error": "",
    }
    api_base_url = str(
        getattr(settings, "KRTC_MEDIAMTX_API_BASE_URL", "")
    ).rstrip("/")
    parsed_api_url = urlsplit(api_base_url)
    if (
        parsed_api_url.scheme not in {"http", "https"}
        or not parsed_api_url.netloc
        or parsed_api_url.username
        or parsed_api_url.password
    ):
        result["error"] = "invalid_mediamtx_api_url"
        return result

    timeout = float(
        getattr(settings, "KRTC_MEDIAMTX_API_TIMEOUT_SECONDS", 3)
    )
    try:
        payload = _read_json(f"{api_base_url}/v3/paths/list", timeout)
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        result["error"] = f"mediamtx_unreachable:{type(exc).__name__}"
        return result

    items_by_name = {
        str(item.get("name", "")): item
        for item in payload.get("items") or []
        if item.get("name")
    }
    result["reachable"] = True
    for camera_code in sorted(phase1_camera_codes()):
        transition_camera = result["transition"]["cameras"].get(
            camera_code,
            {},
        )
        active_path = transition_camera.get(
            "active_path",
            camera_path_name(camera_code),
        )
        next_path = transition_camera.get("next_path")
        transition_camera["active_player_url"] = player_url_for_path(
            active_path
        )
        transition_camera["next_player_url"] = player_url_for_path(next_path)
        transition_camera["active_ready"] = bool(
            items_by_name.get(active_path, {}).get(
                "online",
                items_by_name.get(active_path, {}).get(
                    "ready",
                    False,
                ),
            )
        )
        transition_camera["next_ready"] = bool(
            next_path
            and items_by_name.get(next_path, {}).get(
                "online",
                items_by_name.get(next_path, {}).get("ready", False),
            )
        )
        transition_camera["next_reader_count"] = len(
            items_by_name.get(next_path, {}).get("readers") or []
        ) if next_path else 0
        result["paths"][camera_code] = transition_camera["active_ready"]
        active_readers = (
            items_by_name.get(active_path, {}).get("readers") or []
        )
        result["path_details"][camera_code] = {
            "camera": camera_code,
            "path": active_path,
            "ready": transition_camera["active_ready"],
            "reader_count": len(active_readers),
            "webrtc_reader_count": sum(
                1
                for reader in active_readers
                if reader.get("type") == "webRTCSession"
            ),
            "transition_state": transition_camera.get(
                "transition_state",
                "idle",
            ),
        }
    return result
