from __future__ import annotations

from typing import Any

from django.utils import timezone


def _role_name(user) -> str:
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    if getattr(user, "is_superuser", False):
        return "Superuser"
    for name in ("Administrator", "Maintainer", "Operator"):
        try:
            if user.groups.filter(name=name).exists():
                return name
        except Exception:
            pass
    return ""


def _client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or None


def record_security_audit(
    *,
    action: str,
    result: str,
    request=None,
    user=None,
    username: str = "",
    display_name: str = "",
    role: str = "",
    auth_method: str = "",
    detail: str = "",
    metadata: dict[str, Any] | None = None,
):
    """Append one immutable security audit record. Never include secrets."""
    from .models import SecurityAuditLog

    actor = user or getattr(request, "user", None)
    if actor and getattr(actor, "is_authenticated", False):
        username = username or actor.get_username()
        display_name = display_name or actor.get_full_name()
        role = role or _role_name(actor)

    safe_meta = dict(metadata or {})
    for key in list(safe_meta):
        if key.lower() in {"password", "token", "secret", "authorization", "sessionid", "csrfmiddlewaretoken"}:
            safe_meta.pop(key, None)

    return SecurityAuditLog.objects.create(
        occurred_at=timezone.now(),
        username=(username or "")[:150],
        display_name=(display_name or "")[:150],
        role=(role or "")[:50],
        action=action,
        result=result,
        auth_method=(auth_method or "")[:50],
        client_ip=_client_ip(request),
        user_agent=((request.META.get("HTTP_USER_AGENT") if request else "") or "")[:500],
        detail=(detail or "")[:500],
        metadata=safe_meta,
    )
