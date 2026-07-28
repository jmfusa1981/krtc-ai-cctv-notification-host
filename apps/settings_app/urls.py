from django.urls import path

from . import views

app_name = "settings_app"

urlpatterns = [
    path("", views.station_settings, name="station_settings"),
    path("tests/inference-host/", views.test_inference_host, name="test_inference_host"),
    path("tests/camera/", views.test_camera, name="test_camera"),
    path("tests/speaker/", views.test_speaker, name="test_speaker"),
    path("speakers/save/", views.save_speaker, name="save_speaker"),
    path("tests/audio-file/", views.test_audio_file, name="test_audio_file"),
    path("tests/maintenance-host/", views.test_maintenance_host, name="test_maintenance_host"),
]
