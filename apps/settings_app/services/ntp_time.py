from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings


logger = logging.getLogger(__name__)

CONFIG_FILENAME = "ntp_settings.json"
CONFIG_MAX_BYTES = 64 * 1024
W32TM_EXECUTABLE = r"C:\Windows\System32\w32tm.exe"
NTP_TEST_TIMEOUT_SECONDS = 15
NTP_SYNC_TIMEOUT_SECONDS = 20

SOURCE_ORDER = (
    ("station_clock_lan1", "本站次母鐘 LAN1"),
    ("station_clock_lan2", "本站次母鐘 LAN2"),
    ("occ_backup_clock_lan1", "OCC 備援母鐘 LAN1"),
    ("occ_backup_clock_lan2", "OCC 備援母鐘 LAN2"),
)
SOURCE_LABELS = dict(SOURCE_ORDER)

STATUS_LABELS = {
    "disabled": "已停用",
    "not_configured": "尚未設定",
    "available": "可用",
    "unavailable": "無法使用",
    "sync_success": "校時成功",
    "sync_failed": "校時失敗",
    "permission_required": "需要系統權限",
}

_OFFSET_PATTERN = re.compile(
    r"[,，]\s*([+\-−＋－])\s*(\d+(?:[.,]\d+)?)",
)
_TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
_config_lock = threading.RLock()


class NtpConfigurationError(ValueError):
    """時間同步設定或操作不符合安全規則。"""


@dataclass(frozen=True)
class NtpSources:
    station_clock_lan1: str = ""
    station_clock_lan2: str = ""
    occ_backup_clock_lan1: str = ""
    occ_backup_clock_lan2: str = ""


@dataclass(frozen=True)
class NtpStatus:
    current_source: str | None = None
    current_source_address: str = ""
    current_status: str = "disabled"
    last_test_at: str | None = None
    last_test_source: str | None = None
    last_sync_at: str | None = None
    last_offset: str | None = None
    failure_reason: str | None = None
    source_results: dict[str, dict[str, str | None]] = field(default_factory=dict)


@dataclass(frozen=True)
class NtpConfiguration:
    enabled: bool = False
    sources: NtpSources = field(default_factory=NtpSources)
    status: NtpStatus = field(default_factory=NtpStatus)


@dataclass(frozen=True)
class TimeOperationResult:
    success: bool
    message: str
    offset: str | None = None
    permission_required: bool = False
    failure_scope: str = "source"


@dataclass(frozen=True)
class SourceCheckSummary:
    success: bool
    message: str
    recommended_source: str | None = None
    results: tuple[dict[str, str | bool | None], ...] = ()


def validate_ipv4_address(value: str, *, allow_blank: bool = True) -> str:
    normalized = str(value or "").strip()
    if not normalized and allow_blank:
        return ""
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError as exc:
        raise NtpConfigurationError("請輸入有效的 IPv4 位址。") from exc
    if address.version != 4:
        raise NtpConfigurationError("目前僅支援 IPv4 位址。")
    return str(address)


def load_ntp_configuration() -> NtpConfiguration:
    with _config_lock:
        try:
            path = _config_path()
            if not path.is_file() or path.stat().st_size > CONFIG_MAX_BYTES:
                return NtpConfiguration()
            payload = json.loads(path.read_text(encoding="utf-8"))
            source_payload = payload.get("sources") or {}
            status_payload = payload.get("status") or {}
            sources = NtpSources(
                **{
                    key: validate_ipv4_address(source_payload.get(key, ""))
                    for key, _label in SOURCE_ORDER
                }
            )
            current_source = status_payload.get("current_source")
            last_test_source = status_payload.get("last_test_source")
            if current_source not in SOURCE_LABELS:
                current_source = None
            if last_test_source not in SOURCE_LABELS:
                last_test_source = None
            current_status = str(status_payload.get("current_status") or "disabled")
            if current_status not in STATUS_LABELS:
                current_status = "disabled"
            status = NtpStatus(
                current_source=current_source,
                current_source_address=validate_ipv4_address(
                    status_payload.get("current_source_address", "")
                ),
                current_status=current_status,
                last_test_at=_safe_status_text(status_payload.get("last_test_at")),
                last_test_source=last_test_source,
                last_sync_at=_safe_status_text(status_payload.get("last_sync_at")),
                last_offset=_safe_status_text(status_payload.get("last_offset"), 80),
                failure_reason=_safe_status_text(status_payload.get("failure_reason"), 300),
                source_results=_safe_source_results(status_payload.get("source_results")),
            )
            return NtpConfiguration(
                enabled=payload.get("enabled") is True,
                sources=sources,
                status=status,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError, NtpConfigurationError):
            logger.warning("時間同步設定無效，改用停用的空白設定。")
            return NtpConfiguration()


def save_ntp_settings(*, enabled: bool, sources: dict[str, str]) -> NtpConfiguration:
    validated_sources = NtpSources(
        **{
            key: validate_ipv4_address(sources.get(key, ""))
            for key, _label in SOURCE_ORDER
        }
    )
    with _config_lock:
        current = load_ntp_configuration()
        status = current.status
        if not enabled:
            status = NtpStatus(
                current_status="disabled",
                last_test_at=status.last_test_at,
                last_test_source=status.last_test_source,
                last_sync_at=status.last_sync_at,
                last_offset=status.last_offset,
                source_results=status.source_results,
            )
        elif not any(asdict(validated_sources).values()):
            status = NtpStatus(current_status="not_configured")
        elif status.current_status == "disabled":
            status = NtpStatus(current_status="not_configured")
        elif status.current_source and (
            getattr(validated_sources, status.current_source)
            != status.current_source_address
        ):
            status = NtpStatus(current_status="not_configured")
        updated = NtpConfiguration(
            enabled=bool(enabled),
            sources=validated_sources,
            status=status,
        )
        _write_configuration(updated)
    logger.info("時間同步設定已儲存。")
    return updated


def reset_ntp_settings() -> NtpConfiguration:
    with _config_lock:
        updated = NtpConfiguration()
        _write_configuration(updated)
    logger.info("時間同步設定已恢復預設。")
    return updated


def test_ntp_source(
    source_key: str,
    address: str,
    *,
    adapter: WindowsTimeAdapter | None = None,
) -> TimeOperationResult:
    if source_key not in SOURCE_LABELS:
        raise NtpConfigurationError("時間來源項目無效。")
    with _config_lock:
        current = load_ntp_configuration()
    if not current.enabled:
        return TimeOperationResult(
            False,
            "PAO 時間同步管理目前已停用。",
            failure_scope="machine",
        )
    validated_address = validate_ipv4_address(address, allow_blank=False)
    adapter = adapter or WindowsTimeAdapter()
    logger.info("開始測試時間來源：%s。", SOURCE_LABELS[source_key])
    result = adapter.test_source(validated_address)
    with _config_lock:
        current = load_ntp_configuration()
        status = NtpStatus(
            current_source=current.status.current_source,
            current_source_address=current.status.current_source_address,
            current_status="available" if result.success else "unavailable",
            last_test_at=_now_iso(),
            last_test_source=source_key,
            last_sync_at=current.status.last_sync_at,
            last_offset=result.offset,
            failure_reason=None if result.success else result.message,
            source_results=current.status.source_results,
        )
        _write_configuration(
            NtpConfiguration(
                enabled=current.enabled,
                sources=current.sources,
                status=status,
            )
        )
    logger.log(
        logging.INFO if result.success else logging.WARNING,
        "時間來源測試%s：%s。",
        "成功" if result.success else "失敗",
        SOURCE_LABELS[source_key],
    )
    return result


def check_time_sources(
    *,
    adapter: WindowsTimeAdapter | None = None,
) -> SourceCheckSummary:
    adapter = adapter or WindowsTimeAdapter()
    with _config_lock:
        config = load_ntp_configuration()
    if not config.enabled:
        return SourceCheckSummary(False, "PAO 時間同步管理目前已停用。")

    results = []
    persisted_results = {}
    recommended_source = None
    recommended_offset = None
    for source_key, label in SOURCE_ORDER:
        address = getattr(config.sources, source_key)
        if not address:
            results.append(
                {
                    "source_key": source_key,
                    "label": label,
                    "configured": False,
                    "success": False,
                    "offset": None,
                    "message": "未設定",
                }
            )
            persisted_results[source_key] = {
                "state": "not_configured",
                "offset": None,
                "message": "未設定",
            }
            continue

        result = adapter.test_source(address)
        results.append(
            {
                "source_key": source_key,
                "label": label,
                "configured": True,
                "success": result.success,
                "offset": result.offset,
                "message": "正常" if result.success else "無法使用",
            }
        )
        persisted_results[source_key] = {
            "state": "available" if result.success else "unavailable",
            "offset": result.offset,
            "message": result.message,
        }
        if not result.success and result.failure_scope == "machine":
            status = NtpStatus(
                current_source=config.status.current_source,
                current_source_address=config.status.current_source_address,
                current_status=(
                    "permission_required"
                    if result.permission_required
                    else "unavailable"
                ),
                last_test_at=_now_iso(),
                last_sync_at=config.status.last_sync_at,
                failure_reason=result.message,
                source_results=persisted_results,
            )
            _write_status(config, status)
            logger.error("時間來源檢查因本機 Windows Time 錯誤停止。")
            return SourceCheckSummary(False, result.message, results=tuple(results))
        if result.success and recommended_source is None:
            recommended_source = source_key
            recommended_offset = result.offset

    if not any(item["configured"] for item in results):
        summary_message = "尚未設定任何時間來源。"
        current_status = "not_configured"
    elif recommended_source:
        summary_message = f"時間來源檢查完成。建議來源：{SOURCE_LABELS[recommended_source]}。"
        current_status = "available"
    else:
        summary_message = "時間來源檢查完成，目前沒有可用的時間來源。"
        current_status = "unavailable"

    status = NtpStatus(
        current_source=config.status.current_source,
        current_source_address=config.status.current_source_address,
        current_status=current_status,
        last_test_at=_now_iso(),
        last_test_source=recommended_source,
        last_sync_at=config.status.last_sync_at,
        last_offset=recommended_offset,
        failure_reason=None if recommended_source else summary_message,
        source_results=persisted_results,
    )
    _write_status(config, status)
    logger.info("時間來源一鍵檢查完成，可用來源：%s。", SOURCE_LABELS.get(recommended_source, "無"))
    return SourceCheckSummary(
        success=bool(recommended_source),
        message=summary_message,
        recommended_source=recommended_source,
        results=tuple(results),
    )


def synchronize_now(*, adapter: WindowsTimeAdapter | None = None) -> TimeOperationResult:
    adapter = adapter or WindowsTimeAdapter()
    with _config_lock:
        config = load_ntp_configuration()

    if not config.enabled:
        return _store_sync_failure(config, "disabled", "時間同步目前已停用。")

    configured_sources = [
        (key, getattr(config.sources, key))
        for key, _label in SOURCE_ORDER
        if getattr(config.sources, key)
    ]
    if not configured_sources:
        return _store_sync_failure(config, "not_configured", "尚未設定任何時間來源。")

    logger.info("已要求立即校時，開始依固定優先序測試時間來源。")
    failures = []
    for source_key, address in configured_sources:
        test_result = adapter.test_source(address)
        if not test_result.success:
            if test_result.failure_scope == "machine":
                status_name = (
                    "permission_required"
                    if test_result.permission_required
                    else "sync_failed"
                )
                return _store_sync_failure(
                    config,
                    status_name,
                    test_result.message,
                    failure_scope="machine",
                )
            failures.append(SOURCE_LABELS[source_key])
            continue

        sync_result = adapter.synchronize(address)
        if not sync_result.success and sync_result.failure_scope == "source":
            failures.append(f"{SOURCE_LABELS[source_key]}（無法完成校時）")
            continue

        status_name = "sync_success" if sync_result.success else "sync_failed"
        if sync_result.permission_required:
            status_name = "permission_required"
        user_message = sync_result.message
        if sync_result.success:
            user_message = f"校時成功。來源：{SOURCE_LABELS[source_key]}。"
            if test_result.offset:
                user_message += f" 時間偏差：{test_result.offset}。"
        sync_result = replace(
            sync_result,
            message=user_message,
            offset=test_result.offset,
        )
        updated_status = NtpStatus(
            current_source=source_key,
            current_source_address=address,
            current_status=status_name,
            last_test_at=_now_iso(),
            last_test_source=source_key,
            last_sync_at=_now_iso() if sync_result.success else config.status.last_sync_at,
            last_offset=test_result.offset,
            failure_reason=None if sync_result.success else sync_result.message,
            source_results=config.status.source_results,
        )
        _write_status(config, updated_status)
        logger.log(
            logging.INFO if sync_result.success else logging.ERROR,
            "立即校時%s，時間來源：%s。",
            "成功" if sync_result.success else "失敗",
            SOURCE_LABELS[source_key],
        )
        return sync_result

    reason = "所有已設定的時間來源均無法使用。"
    if failures:
        reason = f"無法使用的時間來源：{'、'.join(failures)}。"
    return _store_sync_failure(config, "unavailable", reason)


class WindowsTimeAdapter:
    """只允許固定 w32tm 操作的 Windows Time 窄化介面。"""

    def __init__(self, *, runner=subprocess.run):
        self._runner = runner

    def test_source(self, address: str) -> TimeOperationResult:
        validated_address = validate_ipv4_address(address, allow_blank=False)
        command = [
            W32TM_EXECUTABLE,
            "/stripchart",
            f"/computer:{validated_address}",
            "/samples:3",
            "/dataonly",
        ]
        result = self._run(command, timeout=NTP_TEST_TIMEOUT_SECONDS)
        if not result.success:
            return result
        offset = _parse_offset(result.message)
        if offset is None:
            return TimeOperationResult(
                False,
                "時間來源無回應或未取得有效 NTP 樣本。",
                failure_scope="source",
            )
        return TimeOperationResult(
            True,
            "時間來源可用。",
            offset=offset,
        )

    def synchronize(self, address: str) -> TimeOperationResult:
        validated_address = validate_ipv4_address(address, allow_blank=False)
        configure_result = self._run(
            [
                W32TM_EXECUTABLE,
                "/config",
                f"/manualpeerlist:{validated_address},0x8",
                "/syncfromflags:manual",
                "/update",
            ],
            timeout=NTP_SYNC_TIMEOUT_SECONDS,
        )
        if not configure_result.success:
            return replace(configure_result, failure_scope="machine")
        resync_result = self._run(
            [W32TM_EXECUTABLE, "/resync", "/rediscover"],
            timeout=NTP_SYNC_TIMEOUT_SECONDS,
        )
        if not resync_result.success:
            return resync_result
        return TimeOperationResult(True, "Windows 時間同步要求已成功送出。")

    def _run(self, command: list[str], *, timeout: int) -> TimeOperationResult:
        _validate_allowlisted_command(command)
        try:
            completed = self._runner(
                command,
                shell=False,
                timeout=timeout,
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
            )
        except subprocess.TimeoutExpired:
            return TimeOperationResult(False, "Windows Time 操作逾時。")
        except OSError:
            logger.exception("無法啟動 Windows Time 工具。")
            return TimeOperationResult(
                False,
                "無法啟動 Windows Time 工具。",
                failure_scope="machine",
            )

        output = "\n".join(
            part.strip()
            for part in (completed.stdout or "", completed.stderr or "")
            if part.strip()
        )
        if completed.returncode == 0:
            return TimeOperationResult(True, output or "Windows Time 操作成功。")
        permission_required = _is_permission_failure(completed.returncode, output)
        service_failure = _is_service_failure(output)
        machine_failure = permission_required or service_failure
        if permission_required:
            message = "Windows Time 操作需要系統管理員權限。"
        elif service_failure:
            message = "Windows Time 服務目前無法使用。"
        else:
            controlled_detail = re.sub(r"\s+", " ", output).strip()[:200]
            message = "Windows Time 操作失敗。"
            if controlled_detail:
                message = f"Windows Time 操作失敗：{controlled_detail}"
        return TimeOperationResult(
            False,
            message,
            permission_required=permission_required,
            failure_scope="machine" if machine_failure else "source",
        )


def status_for_template(config: NtpConfiguration) -> dict[str, object]:
    status = config.status
    current_label = SOURCE_LABELS.get(status.current_source or "", "尚無")
    if status.current_source_address:
        current_label = f"{current_label}（{status.current_source_address}）"
    source_checks = []
    for source_key, label in SOURCE_ORDER:
        result = status.source_results.get(source_key, {})
        source_checks.append(
            {
                "label": label,
                "state": result.get("state", "not_tested"),
                "offset": result.get("offset"),
                "message": result.get("message") or "尚未測試",
            }
        )
    return {
        "current_source": current_label,
        "current_status": STATUS_LABELS.get(status.current_status, "未知"),
        "last_test_at": _format_timestamp_for_display(status.last_test_at),
        "last_test_source": SOURCE_LABELS.get(status.last_test_source or "", "尚無"),
        "last_sync_at": _format_timestamp_for_display(status.last_sync_at),
        "last_offset": status.last_offset or "尚無紀錄",
        "failure_reason": status.failure_reason or "無",
        "source_checks": source_checks,
    }


def _validate_allowlisted_command(command: list[str]) -> None:
    if not command or command[0] != W32TM_EXECUTABLE:
        raise NtpConfigurationError("不允許的系統命令。")
    operation = command[1] if len(command) > 1 else ""
    if operation not in {"/stripchart", "/config", "/resync"}:
        raise NtpConfigurationError("不允許的 Windows Time 操作。")


def _parse_offset(output: str) -> str | None:
    matches = _OFFSET_PATTERN.findall(output or "")
    if not matches:
        return None
    sign, value = matches[-1]
    normalized_sign = "+" if sign in {"+", "＋"} else "-"
    normalized_value = value.replace(",", ".")
    return f"{normalized_sign}{normalized_value} 秒"


def _format_timestamp_for_display(value: str | None) -> str:
    if not value:
        return "尚無紀錄"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(_TAIPEI_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return value


def _is_permission_failure(returncode: int, output: str) -> bool:
    normalized = (output or "").lower()
    return returncode == 5 or any(
        marker in normalized
        for marker in (
            "access is denied",
            "access denied",
            "requires elevation",
            "拒絕存取",
            "存取被拒",
        )
    )


def _is_service_failure(output: str) -> bool:
    normalized = (output or "").lower()
    return any(
        marker in normalized
        for marker in (
            "service has not been started",
            "service is not running",
            "0x80070426",
            "服務尚未啟動",
            "服務未啟動",
        )
    )


def _store_sync_failure(
    config: NtpConfiguration,
    status_name: str,
    reason: str,
    *,
    failure_scope: str = "source",
) -> TimeOperationResult:
    status = NtpStatus(
        current_status=status_name,
        last_test_at=_now_iso(),
        last_sync_at=config.status.last_sync_at,
        failure_reason=reason,
        source_results=config.status.source_results,
    )
    _write_status(config, status)
    logger.warning("立即校時未完成：%s", reason)
    return TimeOperationResult(False, reason, failure_scope=failure_scope)


def _write_status(config: NtpConfiguration, status: NtpStatus) -> None:
    with _config_lock:
        _write_configuration(
            NtpConfiguration(
                enabled=config.enabled,
                sources=config.sources,
                status=status,
            )
        )


def _config_path() -> Path:
    return Path(settings.KRTC_CONFIG_DIR) / CONFIG_FILENAME


def _write_configuration(config: NtpConfiguration) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": config.enabled,
        "sources": asdict(config.sources),
        "status": asdict(config.status),
    }
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".ntp-settings-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_status_text(value, max_length: int = 64) -> str | None:
    if value is None:
        return None
    return str(value).strip()[:max_length] or None


def _safe_source_results(value) -> dict[str, dict[str, str | None]]:
    if not isinstance(value, dict):
        return {}
    safe_results = {}
    for source_key, _label in SOURCE_ORDER:
        item = value.get(source_key)
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "not_tested")
        if state not in {"not_tested", "not_configured", "available", "unavailable"}:
            state = "not_tested"
        safe_results[source_key] = {
            "state": state,
            "offset": _safe_status_text(item.get("offset"), 80),
            "message": _safe_status_text(item.get("message"), 300),
        }
    return safe_results
