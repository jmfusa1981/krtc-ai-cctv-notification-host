from django.urls import path

from .views import (
    manual_event_broadcast_api,
    process_pending_broadcast_logs_api,
)


app_name = "notifications"

urlpatterns = [
    path(
        "broadcast/process-pending/",
        process_pending_broadcast_logs_api,
        name="process_pending_broadcast_logs_api",
    ),
    path(
        "broadcast/event/<int:event_id>/manual/",
        manual_event_broadcast_api,
        name="manual_event_broadcast_api",
    ),
]
