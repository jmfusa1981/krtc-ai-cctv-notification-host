from django.urls import path

from . import views


app_name = "events"

urlpatterns = [
    path("trigger/", views.ai_event_trigger_api, name="ai_event_trigger_api"),
    path(
        "<int:event_id>/recordings/request/",
        views.request_event_recording_api,
        name="request_event_recording_api",
    ),
    path(
        "recordings/<int:evidence_id>/refresh/",
        views.refresh_event_recording_api,
        name="refresh_event_recording_api",
    ),
    path(
        "recordings/<int:evidence_id>/play/",
        views.play_event_recording,
        name="play_event_recording",
    ),
    path(
        "recordings/<int:evidence_id>/download/",
        views.download_event_recording,
        name="download_event_recording",
    ),
    path(
        "<int:event_id>/confirm/",
        views.confirm_event_api,
        name="confirm_event_api",
    ),
    path(
        "<int:event_id>/close/",
        views.close_event_api,
        name="close_event_api",
    ),
    path(
        "active-alarms/close/",
        views.close_active_alarm_events_api,
        name="close_active_alarm_events_api",
    ),
]
