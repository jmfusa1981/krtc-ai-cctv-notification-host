from __future__ import annotations

import logging

from django.utils import timezone

from apps.station_api.occ_runtime import read_runtime_status, write_runtime_status


logger = logging.getLogger(__name__)


def integration_state() -> dict:
    """讀取可供 health 與 diagnostics 共用的輕量 runtime state。"""

    payload = read_runtime_status()
    return {
        "enabled": bool(payload.get("integration_enabled", False)),
        "configured": bool(payload.get("integration_configured", False)),
        "last_attempt_at": payload.get("last_attempt_at"),
        "last_success_at": payload.get("last_success_at"),
        "last_failure_at": payload.get("last_failure_at"),
        "last_error_code": str(payload.get("last_error_code") or ""),
        "last_error_message": str(payload.get("last_error_message") or ""),
        "reachable": payload.get("occ_reachable"),
    }


def record_configuration(*, enabled: bool, configured: bool) -> dict:
    """僅在 configured 狀態轉換時記錄訊息，避免週期性洗版。"""

    previous = read_runtime_status()
    if previous.get("integration_configured") is not configured:
        logger.info(
            "OCC integration configuration changed: configured=%s enabled=%s",
            configured,
            enabled,
        )
    return write_runtime_status(
        integration_enabled=enabled,
        integration_configured=configured,
    )


def record_attempt() -> dict:
    """記錄送出嘗試時間，不寫入 payload、header 或密鑰。"""

    return write_runtime_status(last_attempt_at=timezone.now().isoformat())


def record_success() -> dict:
    """記錄成功並只在 unreachable 轉 reachable 時寫 log。"""

    previous = read_runtime_status()
    if previous.get("occ_reachable") is not True:
        logger.info("OCC integration became reachable.")
    return write_runtime_status(
        last_success_at=timezone.now().isoformat(),
        last_error_code="",
        last_error_message="",
        occ_reachable=True,
    )


def record_failure(code: str, message: str, *, reachable: bool = False) -> dict:
    """記錄遮蔽後的失敗摘要與連線狀態轉換。"""

    previous = read_runtime_status()
    if previous.get("occ_reachable") is not reachable:
        logger.warning(
            "OCC integration reachability changed: reachable=%s code=%s",
            reachable,
            code,
        )
    if code == "authentication_failed":
        logger.warning("OCC integration authentication failed.")
    return write_runtime_status(
        last_failure_at=timezone.now().isoformat(),
        last_error_code=str(code or "unknown_error")[:100],
        last_error_message=str(message or "")[:500],
        occ_reachable=reachable,
    )
