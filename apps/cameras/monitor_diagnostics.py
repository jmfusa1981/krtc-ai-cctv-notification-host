import csv
import ctypes
import io
import json
import os
import subprocess
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from django.conf import settings

from .bridge_runtime import (
    effective_camera_path,
    load_bridge_statuses,
    select_effective_bridge_statuses,
)
from .mediamtx import (
    camera_path_name,
    phase1_camera_codes,
    player_url_for_path,
)
from .media_availability import (
    STALE,
    camera_network_snapshot,
    evaluate_media_availability,
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


def _load_bridge_statuses(camera_codes=None):
    """讀取bridge產生的安全狀態快照，忽略來源網址與憑證欄位。"""

    return load_bridge_statuses(camera_codes or phase1_camera_codes())


def _select_active_bridge_statuses(
    bridge_statuses,
    transition,
    camera_codes=None,
):
    """依A/B狀態只選目前active bridge，避免轉場雙程序被誤算為crash。"""

    return select_effective_bridge_statuses(
        bridge_statuses,
        transition,
        camera_codes or phase1_camera_codes(),
    )


def _with_diagnostic_output_semantics(
    bridge_status,
    requested_profile,
    requested_values,
):
    """分離要求profile與bridge實際輸出，避免copy路徑誤報縮放結果。"""

    item = dict(bridge_status)
    item.setdefault("canonical_path", camera_path_name(item.get("camera_code")))
    item.setdefault("declared_state", item.get("state", "unknown"))
    item.setdefault("effective_state", item.get("state", "unknown"))
    item.setdefault("process_alive", item.get("state") == "running")
    item.setdefault("process_start_match", None)
    item.setdefault("process_name_match", None)
    item.setdefault("command_line_match", None)
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


def _unavailable_path_diagnostics(
    camera_codes,
    bridge_statuses,
    active_profile,
    profile_values,
    transition,
):
    """MediaMTX 無法連線時仍逐 Camera 回報完整且明確的 false 狀態。"""

    bridge_by_camera = {
        item["camera_code"]: item
        for item in bridge_statuses
    }
    paths = []
    for camera_code in sorted(camera_codes):
        canonical_path = camera_path_name(camera_code)
        bridge = bridge_by_camera.get(camera_code, {})
        transition_camera = transition["cameras"].get(camera_code, {})
        paths.append(
            {
                "camera_code": camera_code,
                "canonical_path": canonical_path,
                "path": canonical_path,
                "ready": False,
                "reader_count": 0,
                "webrtc_session_count": 0,
                "inbound_bytes": 0,
                "outbound_bytes": 0,
                "source_codec": bridge.get("source_codec", "unknown"),
                "bridge_mode": bridge.get("bridge_mode", "unknown"),
                "actual_bridge_mode": bridge.get("bridge_mode", "unknown"),
                "bridge_state": bridge.get("effective_state", "unknown"),
                "declared_state": bridge.get("declared_state", "unknown"),
                "effective_state": bridge.get("effective_state", "unknown"),
                "pid": bridge.get("process_id", 0),
                "process_alive": bridge.get("process_alive", False),
                "process_start_match": bridge.get("process_start_match"),
                "profile": active_profile,
                "requested_width": int(profile_values["width"]),
                "requested_height": int(profile_values["height"]),
                "requested_fps": int(profile_values["fps"]),
                "actual_output": bridge.get("actual_output", "unknown"),
                "active_path": transition_camera.get(
                    "active_path",
                    canonical_path,
                ),
                "next_path": transition_camera.get("next_path"),
                "transition_state": transition_camera.get(
                    "transition_state",
                    "idle",
                ),
            }
        )
    return paths


def _annotate_media_availability(
    paths,
    bridge_statuses,
    mediamtx_reachable,
    cameras,
):
    """將統一 media evaluator 結果附加至診斷逐 Camera 資料。"""

    camera_by_code = {
        str(camera.camera_code).upper(): camera
        for camera in (cameras or [])
    }
    bridge_by_camera = {
        item["camera_code"]: item
        for item in bridge_statuses
    }
    for item in paths:
        camera_code = item["camera_code"]
        camera = camera_by_code.get(camera_code)
        network = (
            camera_network_snapshot(camera)
            if camera is not None
            else {
                "network_reachable": None,
                "network_state": STALE,
            }
        )
        bridge = bridge_by_camera.get(camera_code, {})
        effective_state = bridge.get(
            "effective_state",
            bridge.get("state", item.get("effective_state", "unknown")),
        )
        effective_path = item.get("active_path") or item.get("path")
        metadata_available = bool(
            getattr(camera, "is_active", True)
            and player_url_for_path(effective_path)
        )
        item.update(
            evaluate_media_availability(
                camera_code=camera_code,
                canonical_path=item.get("canonical_path")
                or camera_path_name(camera_code),
                effective_path=effective_path,
                effective_bridge_state=effective_state,
                mediamtx_reachable=mediamtx_reachable,
                path_ready=item.get("ready", False),
                metadata_available=metadata_available,
                network_reachable=network["network_reachable"],
                network_state=network["network_state"],
            )
        )
    return paths


def collect_monitor_media_diagnostics(cameras=None):
    """彙整Monitor media mode、MediaMTX path/session與程序資源。"""

    media_mode = getattr(settings, "KRTC_MONITOR_MEDIA_MODE", "legacy")
    fallback_enabled = bool(
        getattr(settings, "KRTC_MONITOR_MOSAIC_FALLBACK", True)
    )
    camera_list = list(cameras or [])
    camera_codes = {
        str(camera.camera_code).upper()
        for camera in camera_list
        if getattr(camera, "is_active", False)
    } or phase1_camera_codes()
    all_bridge_statuses = _load_bridge_statuses(camera_codes)
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
        camera_codes,
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
        result["paths"] = _unavailable_path_diagnostics(
            camera_codes,
            diagnostic_bridge_statuses,
            active_profile,
            active_profile_values,
            transition,
        )
        _annotate_media_availability(
            result["paths"],
            diagnostic_bridge_statuses,
            False,
            camera_list,
        )
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
        result["paths"] = _unavailable_path_diagnostics(
            camera_codes,
            diagnostic_bridge_statuses,
            active_profile,
            active_profile_values,
            transition,
        )
        _annotate_media_availability(
            result["paths"],
            diagnostic_bridge_statuses,
            False,
            camera_list,
        )
        return result

    result["mediamtx_reachable"] = True
    path_items = paths_payload.get("items") or []
    session_items = sessions_payload.get("items") or []
    items_by_name = {
        str(item.get("name", "")): item
        for item in path_items
        if item.get("name")
    }
    session_count_by_path = {}
    for session in session_items:
        session_path = str(
            session.get("path")
            or session.get("pathName")
            or session.get("path_name")
            or ""
        )
        if session_path:
            session_count_by_path[session_path] = (
                session_count_by_path.get(session_path, 0) + 1
            )
    visible_paths = set()
    bridge_by_camera = {
        item["camera_code"]: item
        for item in diagnostic_bridge_statuses
    }

    for camera_code in sorted(camera_codes):
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
                "webrtc_session_count": session_count_by_path.get(
                    path_name,
                    sum(
                        1
                        for reader in readers
                        if reader.get("type") == "webRTCSession"
                    ),
                ),
                "inbound_bytes": int(item.get("inboundBytes") or 0),
                "outbound_bytes": int(item.get("outboundBytes") or 0),
                "source_codec": bridge_status.get("source_codec", "unknown"),
                "bridge_mode": bridge_status.get("bridge_mode", "unknown"),
                "actual_bridge_mode": bridge_status.get(
                    "bridge_mode",
                    "unknown",
                ),
                "bridge_state": bridge_status.get(
                    "effective_state",
                    bridge_status.get("state", "unknown"),
                ),
                "declared_state": bridge_status.get(
                    "declared_state",
                    bridge_status.get("state", "unknown"),
                ),
                "effective_state": bridge_status.get(
                    "effective_state",
                    bridge_status.get("state", "unknown"),
                ),
                "pid": bridge_status.get("process_id", 0),
                "process_alive": bridge_status.get("process_alive", False),
                "process_start_match": bridge_status.get(
                    "process_start_match"
                ),
                "canonical_path": path_name,
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
    _annotate_media_availability(
        result["paths"],
        diagnostic_bridge_statuses,
        True,
        camera_list,
    )
    return result


def collect_mediamtx_path_readiness(camera_codes=None, cameras=None):
    """取得前端啟動所需的安全path ready快照。"""

    camera_list = list(cameras or [])
    camera_by_code = {
        str(camera.camera_code).upper(): camera
        for camera in camera_list
    }
    requested_codes = {
        str(code).upper()
        for code in (camera_codes or camera_by_code or phase1_camera_codes())
        if str(code).strip()
    }
    camera_codes = requested_codes
    bridge_statuses = load_bridge_statuses(camera_codes)
    result = {
        "reachable": False,
        "paths": {},
        "path_details": {},
        "transition": load_monitor_transition_state(),
        "error": "",
    }
    effective_bridges = select_effective_bridge_statuses(
        bridge_statuses,
        result["transition"],
        camera_codes,
    )
    bridge_by_camera = {
        item["camera_code"]: item
        for item in effective_bridges
    }

    def add_path_detail(camera_code, items_by_name=None):
        """以同一 evaluator 建立 API 與 UI 共用的逐 Camera 狀態。"""

        canonical_path = camera_path_name(camera_code)
        active_path = effective_camera_path(
            camera_code,
            bridge_statuses,
            result["transition"],
        )
        bridge = bridge_by_camera.get(camera_code, {})
        effective_state = bridge.get(
            "effective_state",
            bridge.get("state", "unknown"),
        )
        path_item = (items_by_name or {}).get(active_path, {})
        path_ready = bool(
            path_item.get("online", path_item.get("ready", False))
        )
        camera = camera_by_code.get(camera_code)
        network = (
            camera_network_snapshot(camera)
            if camera is not None
            else {
                "network_reachable": None,
                "network_state": STALE,
            }
        )
        metadata_available = bool(
            getattr(camera, "is_active", True)
            and player_url_for_path(active_path)
        )
        availability = evaluate_media_availability(
            camera_code=camera_code,
            canonical_path=canonical_path,
            effective_path=active_path,
            effective_bridge_state=effective_state,
            mediamtx_reachable=result["reachable"],
            path_ready=path_ready,
            metadata_available=metadata_available,
            network_reachable=network["network_reachable"],
            network_state=network["network_state"],
        )
        transition_camera = result["transition"]["cameras"].get(
            camera_code,
            {},
        )
        transition_camera["active_path"] = active_path
        next_path = transition_camera.get("next_path")
        transition_camera["active_player_url"] = player_url_for_path(
            active_path
        )
        transition_camera["next_player_url"] = player_url_for_path(next_path)
        transition_camera["active_ready"] = path_ready
        transition_camera["next_ready"] = bool(
            next_path
            and (items_by_name or {}).get(next_path, {}).get(
                "online",
                (items_by_name or {}).get(next_path, {}).get("ready", False),
            )
        )
        transition_camera["next_reader_count"] = (
            len((items_by_name or {}).get(next_path, {}).get("readers") or [])
            if next_path
            else 0
        )
        result["paths"][camera_code] = path_ready
        active_readers = path_item.get("readers") or []
        result["path_details"][camera_code] = {
            **availability,
            "path": active_path,
            "ready": path_ready,
            "reader_count": len(active_readers),
            "webrtc_reader_count": sum(
                1
                for reader in active_readers
                if reader.get("type") == "webRTCSession"
            ),
            "inbound_bytes": int(path_item.get("inboundBytes") or 0),
            "outbound_bytes": int(path_item.get("outboundBytes") or 0),
            "transition_state": transition_camera.get(
                "transition_state",
                "idle",
            ),
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
        for camera_code in sorted(camera_codes):
            add_path_detail(camera_code)
        return result

    timeout = float(
        getattr(settings, "KRTC_MEDIAMTX_API_TIMEOUT_SECONDS", 3)
    )
    try:
        payload = _read_json(f"{api_base_url}/v3/paths/list", timeout)
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        result["error"] = f"mediamtx_unreachable:{type(exc).__name__}"
        for camera_code in sorted(camera_codes):
            add_path_detail(camera_code)
        return result

    items_by_name = {
        str(item.get("name", "")): item
        for item in payload.get("items") or []
        if item.get("name")
    }
    result["reachable"] = True
    for camera_code in sorted(camera_codes):
        add_path_detail(camera_code, items_by_name)
    return result
