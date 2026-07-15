from django.urls import path

from .views import process_pending_broadcast_logs_api


app_name = "notifications"

urlpatterns = [
    path(
        "broadcast/process-pending/",
        process_pending_broadcast_logs_api,
        name="process_pending_broadcast_logs_api",
    ),
]