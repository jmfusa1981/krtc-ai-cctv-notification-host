from dataclasses import asdict, dataclass
import re

from django.conf import settings
from django.utils import timezone

from apps.ai_bridge.models import InferenceConnectionState, InferenceHost


HEALTHY = "healthy"
STALE = "stale"
UNREACHABLE = "unreachable"
UNCONFIGURED = "unconfigured"


def _safe_failure_reason(value):
    """遮蔽錯誤文字中可能出現的URL使用者資訊。"""

    return re.sub(
        r"(?i)(https?://)[^/@\s]+@",
        r"\1***@",
        str(value or ""),
    )[:1000]


@dataclass(frozen=True)
class EffectiveInferenceHealth:
    """集中描述一次推論主機健康觀測及其時效。"""

    host_code: str
    effective_health: str
    health_status: str
    last_health_check_at: object
    last_health_success_at: object
    age_seconds: int | None
    stale_threshold: int
    failure_reason: str

    def as_dict(self):
        """回傳可直接序列化的診斷資料。"""

        payload = asdict(self)
        for field_name in ("last_health_check_at", "last_health_success_at"):
            value = payload[field_name]
            payload[field_name] = value.isoformat() if value else None
        return payload


def inference_health_stale_seconds():
    """確保健康時效門檻至少涵蓋三個背景輪詢週期。"""

    polling_interval = max(
        1.0,
        float(getattr(settings, "INFERENCE_POLL_INTERVAL_SECONDS", 5.0)),
    )
    configured_threshold = max(
        1,
        int(getattr(settings, "INFERENCE_HEALTH_STALE_SECONDS", 60)),
    )
    return max(configured_threshold, int(polling_interval * 3))


def record_inference_health_observation(
    host,
    *,
    success,
    checked_at=None,
    health_status="ok",
    failure_reason="",
    application_version="",
):
    """以相同欄位保存手動與背景GET /health的真實結果。"""

    observed_at = checked_at or timezone.now()
    normalized_status = str(health_status or "unknown").strip().lower()
    is_healthy = bool(success and normalized_status == "ok")
    canonical_status = "ok" if is_healthy else "offline"
    reason = "" if is_healthy else _safe_failure_reason(
        failure_reason or normalized_status
    )

    state, _ = InferenceConnectionState.objects.update_or_create(
        inference_host=host,
        defaults={
            "health_status": canonical_status,
            "last_heartbeat_at": observed_at,
            "last_error": reason,
        },
    )

    host.last_health_at = observed_at
    host.status = (
        InferenceHost.STATUS_ONLINE
        if is_healthy
        else InferenceHost.STATUS_OFFLINE
    )
    update_fields = ["status", "last_health_at", "updated_at"]
    if is_healthy:
        host.last_success_at = observed_at
        host.last_error = ""
        update_fields.extend(["last_success_at", "last_error"])
    else:
        host.last_error_at = observed_at
        host.last_error = reason
        update_fields.extend(["last_error_at", "last_error"])
    if application_version:
        host.application_version = str(application_version).strip()[:50]
        update_fields.append("application_version")
    host.save(update_fields=update_fields)
    return state


def effective_inference_health(host, *, now=None):
    """依真實health觀測、成功時間與集中時效門檻計算有效狀態。"""

    threshold = inference_health_stale_seconds()
    current_time = now or timezone.now()
    if not host or not getattr(host, "is_active", False):
        return EffectiveInferenceHealth(
            host_code=getattr(host, "host_code", "") if host else "",
            effective_health=UNCONFIGURED,
            health_status="unknown",
            last_health_check_at=None,
            last_health_success_at=None,
            age_seconds=None,
            stale_threshold=threshold,
            failure_reason="",
        )

    try:
        state = host.connection_state
    except InferenceConnectionState.DoesNotExist:
        state = None
    health_status = str(
        getattr(state, "health_status", "unknown") or "unknown"
    ).strip().lower()
    checked_at = getattr(state, "last_heartbeat_at", None)
    success_at = getattr(host, "last_success_at", None)
    failure_reason = _safe_failure_reason(getattr(state, "last_error", ""))
    if health_status == "ok":
        failure_reason = ""
    age_seconds = None
    if checked_at:
        age_seconds = max(0, int((current_time - checked_at).total_seconds()))

    if health_status == "ok" and age_seconds is not None:
        effective = HEALTHY if age_seconds <= threshold else STALE
    elif checked_at and age_seconds is not None and age_seconds <= threshold:
        effective = UNREACHABLE
    elif success_at:
        effective = STALE
    else:
        effective = UNREACHABLE
        failure_reason = failure_reason or "no_health_observation"

    return EffectiveInferenceHealth(
        host_code=str(host.host_code or host.name or f"HOST-{host.pk}"),
        effective_health=effective,
        health_status=health_status,
        last_health_check_at=checked_at,
        last_health_success_at=success_at,
        age_seconds=age_seconds,
        stale_threshold=threshold,
        failure_reason=failure_reason,
    )
