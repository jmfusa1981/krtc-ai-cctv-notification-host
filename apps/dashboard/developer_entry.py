from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.accounts.usb_key import verify_trusted_key
from apps.settings_app.models import UIConfiguration
from apps.station_api.security_audit import record_security_audit


@never_cache
@require_GET
@login_required
def developer_entry(request):
    """Hidden Superuser-only UI gate for the Django developer backend.

    This endpoint is intentionally not the security boundary. The existing
    /admin/ USB middleware remains the final enforcement layer.
    """
    if not request.user.is_superuser:
        raise Http404

    try:
        config = UIConfiguration.load()
        usb_required = bool(config.superuser_usb_required)
        expected_digest = (config.superuser_usb_token_sha256 or "").strip()
    except Exception:
        # Fail closed for the hidden shortcut if configuration cannot be read.
        return JsonResponse({"ok": False}, status=403)

    if usb_required:
        ok, _ = verify_trusted_key(expected_digest)
        if not ok:
            record_security_audit(action="USB_VERIFY_FAILED", result="failed", request=request, user=request.user, auth_method="PASSWORD+USB", detail="Hidden developer entry rejected")
            return JsonResponse({"ok": False}, status=403)
        record_security_audit(action="USB_VERIFY_SUCCESS", result="success", request=request, user=request.user, auth_method="PASSWORD+USB", detail="Hidden developer entry accepted")

    return JsonResponse(
        {
            "ok": True,
            "redirect": reverse("admin:index"),
        }
    )
