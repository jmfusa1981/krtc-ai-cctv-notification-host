from django.http import HttpResponseForbidden
from apps.accounts.usb_key import verify_trusted_key


class SuperuserUSBKeyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if request.path.startswith("/admin/") and user and user.is_authenticated and user.is_superuser:
            try:
                from apps.settings_app.models import UIConfiguration
                config = UIConfiguration.load()
                required = bool(config.superuser_usb_required)
                digest = (config.superuser_usb_token_sha256 or "").strip()
            except Exception:
                required = False
                digest = ""
            if required:
                ok, _ = verify_trusted_key(digest)
                if not ok:
                    return HttpResponseForbidden(
                        "Superuser USB Key 未插入或驗證失敗。請插入已授權的 KRTC Master USB Key 後重新整理。",
                        content_type="text/plain; charset=utf-8",
                    )
        return self.get_response(request)
