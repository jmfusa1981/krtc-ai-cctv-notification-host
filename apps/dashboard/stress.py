import json
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
from urllib.error import URLError

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from apps.cameras.mediamtx import player_url_for_path
from apps.cameras.monitor_diagnostics import _read_json


STRESS_PATHS = tuple(f"stress{index:02d}" for index in range(1, 17))


class StressTelemetryForm(forms.Form):
    """驗證Lab壓測頁回報的有限瀏覽器狀態。"""

    visible_stream_count = forms.IntegerField(min_value=0, max_value=16)
    loading_paths = forms.CharField(max_length=255, required=False)
    recovered_path = forms.RegexField(
        regex=r"^stress(?:0[1-9]|1[0-6])$",
        required=False,
    )
    recovery_duration_ms = forms.IntegerField(
        min_value=0,
        max_value=3_600_000,
        required=False,
    )
    timestamp = forms.DateTimeField(required=False)
    oldest_loading_started_at = forms.DateTimeField(required=False)
    event = forms.ChoiceField(
        choices=(
            ("heartbeat", "heartbeat"),
            ("loading", "loading"),
            ("recovered", "recovered"),
            ("timeout", "timeout"),
            ("layout", "layout"),
        )
    )

    def clean_loading_paths(self):
        """只接受固定stress path，避免任意內容寫入runtime狀態。"""

        value = self.cleaned_data.get("loading_paths", "")
        paths = tuple(item for item in value.split(",") if item)
        if any(path not in STRESS_PATHS for path in paths):
            raise forms.ValidationError("Invalid stress path.")
        return ",".join(paths)


def _require_lab_mode():
    """正式環境一律隱藏Lab壓測介面與API。"""

    if not settings.DEBUG:
        raise Http404("Lab stress harness is disabled.")


def _is_superuser(user):
    """壓測控制面僅允許既有superuser使用。"""

    return bool(user.is_authenticated and user.is_superuser)


def _stress_runtime_path():
    """回傳已由git忽略的瀏覽器狀態檔路徑。"""

    return Path(settings.BASE_DIR) / "runtime" / "stress" / "browser_state.json"


def _safe_api_base_url():
    """只接受不含帳密的HTTP(S) MediaMTX控制端點。"""

    value = str(getattr(settings, "KRTC_MEDIAMTX_API_BASE_URL", "")).rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return ""
    return value


@login_required
@user_passes_test(_is_superuser)
def lab_stress_monitor(request):
    """顯示與正式Monitor完全分離的Lab多路WebRTC壓測頁。"""

    _require_lab_mode()
    streams = [
        {
            "index": index,
            "path": path,
            "player_url": player_url_for_path(path),
        }
        for index, path in enumerate(STRESS_PATHS, start=1)
    ]
    return render(
        request,
        "dashboard/lab_stress_monitor.html",
        {"streams": streams},
    )


@login_required
@user_passes_test(_is_superuser)
@require_GET
def lab_stress_status_api(request):
    """讀取stress paths與WebRTC sessions，不回傳來源網址或憑證。"""

    _require_lab_mode()
    api_base_url = _safe_api_base_url()
    if not api_base_url:
        return JsonResponse(
            {"success": False, "error": "invalid_mediamtx_api_url"},
            status=503,
        )
    timeout = float(getattr(settings, "KRTC_MEDIAMTX_API_TIMEOUT_SECONDS", 3))
    try:
        paths_payload = _read_json(f"{api_base_url}/v3/paths/list", timeout)
        sessions_payload = _read_json(
            f"{api_base_url}/v3/webrtc/sessions/list",
            timeout,
        )
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        return JsonResponse(
            {
                "success": False,
                "error": f"mediamtx_unreachable:{type(exc).__name__}",
            },
            status=503,
        )

    items_by_name = {
        str(item.get("name", "")): item
        for item in paths_payload.get("items") or []
        if item.get("name") in STRESS_PATHS
    }
    paths = {}
    for path in STRESS_PATHS:
        item = items_by_name.get(path, {})
        readers = item.get("readers") or []
        paths[path] = {
            "ready": bool(item.get("online", item.get("ready", False))),
            "reader_count": len(readers),
            "webrtc_reader_count": sum(
                1 for reader in readers if reader.get("type") == "webRTCSession"
            ),
        }

    sessions = sessions_payload.get("items") or []
    stress_session_count = sum(
        1
        for item in sessions
        if str(
            item.get("path")
            or item.get("pathName")
            or item.get("path_name")
            or ""
        ) in STRESS_PATHS
    )
    return JsonResponse(
        {
            "success": True,
            "paths": paths,
            "ready_stress_path_count": sum(
                1 for item in paths.values() if item["ready"]
            ),
            "active_reader_count": sum(
                item["reader_count"] for item in paths.values()
            ),
            "webrtc_session_count": int(
                sessions_payload.get("itemCount", len(sessions))
            ),
            "stress_webrtc_session_count": stress_session_count,
        }
    )


@login_required
@user_passes_test(_is_superuser)
@require_POST
def lab_stress_telemetry_api(request):
    """將瀏覽器loading與恢復狀態原子寫入Lab runtime目錄。"""

    _require_lab_mode()
    form = StressTelemetryForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {"success": False, "errors": form.errors.get_json_data()},
            status=400,
        )
    state_path = _stress_runtime_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **form.cleaned_data,
    }
    for field_name in ("timestamp", "oldest_loading_started_at"):
        if payload[field_name]:
            payload[field_name] = payload[field_name].isoformat()
    temporary_path = state_path.with_name(
        f".{state_path.name}.{uuid4().hex}.tmp"
    )
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="ascii",
    )
    temporary_path.replace(state_path)
    return JsonResponse({"success": True})
