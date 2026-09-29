from django.urls import path

from . import views

app_name = "cameras"

urlpatterns = [
    path("", views.camera_list_api, name="camera_list_api"),
    path("mosaic-stream/", views.camera_mosaic_stream, name="camera_mosaic_stream"),
    path("<int:camera_id>/stream/", views.camera_mjpeg_stream, name="camera_mjpeg_stream"),
    path("<int:camera_id>/check/", views.camera_stream_check, name="camera_stream_check"),
]
