from django.urls import path

from . import views

app_name = "cameras"

urlpatterns = [
    path("", views.camera_list_api, name="camera_list_api"),
    path("mosaic-stream/", views.camera_mosaic_stream, name="camera_mosaic_stream"),
    path("media-status/", views.camera_media_status_api, name="camera_media_status_api"),
    path("media-profile/", views.camera_media_profile_api, name="camera_media_profile_api"),
    path(
        "media-transition-ack/",
        views.camera_media_transition_ack_api,
        name="camera_media_transition_ack_api",
    ),
    path("<int:camera_id>/playback/", views.camera_playback_api, name="camera_playback_api"),
    path("<int:camera_id>/stream/", views.camera_mjpeg_stream, name="camera_mjpeg_stream"),
    path("<int:camera_id>/check/", views.camera_stream_check, name="camera_stream_check"),
]
