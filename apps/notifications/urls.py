from django.urls import path

from .views import (
    create_broadcast_schedule_api,
    delete_broadcast_schedule_api,
    manual_event_broadcast_api,
    manual_station_broadcast_api,
    process_pending_broadcast_logs_api,
    toggle_broadcast_schedule_api,
    start_live_microphone_broadcast_api,
    stop_live_microphone_broadcast_api,
    live_microphone_broadcast_status_api,
)


app_name = "notifications"

urlpatterns = [
    path("broadcast/live/start/", start_live_microphone_broadcast_api, name="start_live_microphone_broadcast_api"),
    path("broadcast/live/stop/", stop_live_microphone_broadcast_api, name="stop_live_microphone_broadcast_api"),
    path("broadcast/live/status/", live_microphone_broadcast_status_api, name="live_microphone_broadcast_status_api"),
    path(
        "broadcast/schedules/create/",
        create_broadcast_schedule_api,
        name="create_broadcast_schedule_api",
    ),
    path(
        "broadcast/schedules/<int:schedule_id>/toggle/",
        toggle_broadcast_schedule_api,
        name="toggle_broadcast_schedule_api",
    ),
    path(
        "broadcast/schedules/<int:schedule_id>/delete/",
        delete_broadcast_schedule_api,
        name="delete_broadcast_schedule_api",
    ),
    path(
        "broadcast/manual/",
        manual_station_broadcast_api,
        name="manual_station_broadcast_api",
    ),
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
