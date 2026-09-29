from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

from django.conf import settings
from django.utils import timezone


_runtime_lock = threading.Lock()
_ALLOWED_FIELDS = {
    "state",
    "pid",
    "started_at",
    "updated_at",
    "last_heartbeat_attempt_at",
    "last_heartbeat_success_at",
    "last_worker_cycle_at",
    "last_error",
}


def _status_path() -> Path:
    return Path(settings.KRTC_OCC_SERVICE_STATUS_PATH)


def _safe_error(value) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1[REDACTED]@", text)
    text = re.sub(
        r"(?i)(token|authorization|api[-_ ]?key|password|secret)(\s*[:=]\s*)[^\s,;]+",
        r"\1\2[REDACTED]",
        text,
    )
    return text[:500]


def _read_unlocked(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {key: payload[key] for key in _ALLOWED_FIELDS if key in payload}


def read_runtime_status() -> dict:
    """讀取 OCC service 狀態；缺失或損毀時回傳空字典。"""
    with _runtime_lock:
        return _read_unlocked(_status_path())


def write_runtime_status(**updates) -> dict:
    """以同目錄暫存檔與原子替換發布無憑證的存活狀態。"""
    path = _status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _runtime_lock:
        payload = _read_unlocked(path)
        for key, value in updates.items():
            if key not in _ALLOWED_FIELDS:
                continue
            payload[key] = _safe_error(value) if key == "last_error" else value
        payload["pid"] = os.getpid()
        payload["updated_at"] = timezone.now().isoformat()

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump(payload, temporary, ensure_ascii=False, sort_keys=True)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()
        return dict(payload)
