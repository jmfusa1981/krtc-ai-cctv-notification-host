from django.urls import path

from . import views

app_name = "settings_app"

urlpatterns = [
    path("", views.station_settings, name="station_settings"),
    path("manage/<str:kind>/new/", views.manage_object, name="manage_new"),
    path("manage/<str:kind>/<int:object_id>/", views.manage_object, name="manage_edit"),
    path("manage/<str:kind>/<int:object_id>/toggle/", views.toggle_object, name="manage_toggle"),
    path("manage/<str:kind>/<int:object_id>/remove/", views.remove_object, name="manage_remove"),
    path("accounts/", views.user_management, name="user_management"),
    path("accounts/new/", views.manage_user, name="user_new"),
    path("accounts/<int:object_id>/", views.manage_user, name="user_edit"),
    path("accounts/<int:object_id>/toggle/", views.toggle_user, name="user_toggle"),
    path("accounts/<int:object_id>/remove/", views.remove_user, name="user_remove"),
    path("tests/inference-host/", views.test_inference_host, name="test_inference_host"),
    path("tests/camera/", views.test_camera, name="test_camera"),
    path("tests/speaker/", views.test_speaker, name="test_speaker"),
    path("speakers/save/", views.save_speaker, name="save_speaker"),
    path("tests/audio-file/", views.test_audio_file, name="test_audio_file"),
    path("tests/maintenance-host/", views.test_maintenance_host, name="test_maintenance_host"),
]
