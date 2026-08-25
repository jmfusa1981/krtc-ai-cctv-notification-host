from apps.accounts.usb_key import verify_trusted_key
from apps.accounts.permissions import hidden_forbidden_response


class SuperuserUSBKeyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if request.path.startswith("/admin/"):
            # The developer backend is intentionally undiscoverable.
            # Anonymous and non-Superuser users receive the same hidden 404.
            if not user or not user.is_authenticated or not user.is_superuser:
                return hidden_forbidden_response()

            try:
                from apps.settings_app.models import UIConfiguration
                config = UIConfiguration.load()
                required = bool(config.superuser_usb_required)
                digest = (config.superuser_usb_token_sha256 or "").strip()
            except Exception:
                required = True
                digest = ""

            if required:
                ok, _ = verify_trusted_key(digest)
                if not ok:
                    return hidden_forbidden_response()

        response = self.get_response(request)

        # KRTC V6.4.6.2 - never expose Django DEBUG 404 route details.
        # Unknown URLs use the same minimal response in development and release builds.
        if response.status_code == 404:
            return hidden_forbidden_response()

        # Protected backend/frontend paths also hide authorization failures.
        hidden_prefixes = (
            "/admin/",
            "/dashboard/settings/",
            "/dashboard/system-log/",
        )
        if response.status_code == 403 and request.path.startswith(hidden_prefixes):
            return hidden_forbidden_response()

        return response

# KRTC V6.4.6.2 - Security Admin Hardening
