from django.urls import path

from .views import (
    create_broadcast_schedule_api,
    delete_broadcast_schedule_api,
    manual_event_broadcast_api,
    manual_station_broadcast_api,
    process_pending_broadcast_logs_api,
    reset_speaker_workflows_api,
    toggle_broadcast_schedule_api,
    start_live_microphone_broadcast_api,
    stop_live_microphone_broadcast_api,
    live_microphone_broadcast_status_api,
    start_audio_recording_api,
    stop_audio_recording_api,
    save_audio_recording_api,
    discard_audio_recording_api,
    audio_recording_status_api,
)


app_name = "notifications"

urlpatterns = [
    path("broadcast/recorder/start/", start_audio_recording_api, name="start_audio_recording_api"),
    path("broadcast/recorder/stop/", stop_audio_recording_api, name="stop_audio_recording_api"),
    path("broadcast/recorder/save/", save_audio_recording_api, name="save_audio_recording_api"),
    path("broadcast/recorder/discard/", discard_audio_recording_api, name="discard_audio_recording_api"),
    path("broadcast/recorder/status/", audio_recording_status_api, name="audio_recording_status_api"),
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
        "broadcast/reset-workflows/",
        reset_speaker_workflows_api,
        name="reset_speaker_workflows_api",
    ),
    path(
        "broadcast/event/<int:event_id>/manual/",
        manual_event_broadcast_api,
        name="manual_event_broadcast_api",
    ),
]
