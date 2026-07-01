from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),

    # Home redirect
    path("", lambda request: redirect("dashboard/")),

    # Pages
    path("dashboard/", include("apps.dashboard.urls")),

    # APIs
    path("api/cameras/", include("apps.cameras.urls")),
    path("api/events/", include("apps.events.urls")),
    path("api/ai/", include("apps.ai_bridge.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path("api/records/", include("apps.records.urls")),
    path("api/settings/", include("apps.settings_app.urls")),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)