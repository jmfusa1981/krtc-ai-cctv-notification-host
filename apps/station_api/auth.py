import hmac
from functools import wraps

from django.conf import settings
from django.http import JsonResponse


def require_occ_token(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        configured = settings.KRTC_OCC_API_TOKEN
        if not configured:
            return JsonResponse({"detail": "OCC API token is not configured."}, status=503)
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {configured}"
        if not hmac.compare_digest(supplied, expected):
            return JsonResponse({"detail": "Invalid credentials."}, status=401)
        return view(request, *args, **kwargs)

    return wrapped

