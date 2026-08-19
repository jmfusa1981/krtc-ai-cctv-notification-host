from pathlib import Path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.urls import include, path
from django.utils._os import safe_join

from config.media_views import protected_media
from apps.accounts.superuser_usb_views import superuser_usb_manager


def public_login_background(request, path):
    """Serve only login-page UI background assets without authentication."""
    login_media_root = settings.MEDIA_ROOT / "ui" / "login"
    try:
        file_path = safe_join(login_media_root, path)
    except Exception as exc:
        raise Http404("Invalid login background path.") from exc

    file_path = Path(file_path)
    if not file_path.is_file():
        raise Http404("Login background not found.")

    return FileResponse(file_path.open("rb"))


urlpatterns = [
    path(
        "admin/usb-key/",
        superuser_usb_manager,
        name="superuser_usb_manager",
    ),
    path("admin/", admin.site.urls),

    # Frontend login / logout
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),

    # Home redirect
    path("", lambda request: redirect("/dashboard/")),

    # Pages
    path("dashboard/", include("apps.dashboard.urls")),
    path("dashboard/settings/", include("apps.settings_app.urls")),

    # APIs
    path("api/cameras/", include("apps.cameras.urls")),
    path("api/events/", include("apps.events.urls")),
    path("api/ai/", include("apps.ai_bridge.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path("api/records/", include("apps.records.urls")),
    path("api/v1/", include("apps.station_api.urls")),

    # Public login-page background media.
    # This narrow route must remain before the protected /media/ catch-all.
    path(
        "media/ui/login/<path:path>",
        public_login_background,
        name="public_login_background",
    ),

    # Protected operational media
    path(
        "media/<path:path>",
        protected_media,
        name="protected_media",
    ),
]


# Development-only media serving.
# Production uses protected_media above.
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
