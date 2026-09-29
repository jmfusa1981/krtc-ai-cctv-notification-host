from django.urls import path

from . import views

app_name = "settings_app"

urlpatterns = [
    path("", views.station_settings, name="station_settings"),
    path("general/login-background/save/", views.save_login_background, name="save_login_background"),
    path("general/login-background/reset/", views.restore_default_login_background, name="reset_login_background"),
    path("general/event-alert-sound/save/", views.save_event_alert_sound, name="save_event_alert_sound"),
    path("general/event-alert-sound/reset/", views.restore_default_event_alert_sound, name="reset_event_alert_sound"),
    path("general/time-sync/save/", views.save_ntp_configuration, name="save_ntp_configuration"),
    path("general/time-sync/test/", views.test_ntp_configuration_source, name="test_ntp_source"),
    path("general/time-sync/check/", views.check_all_ntp_sources, name="check_ntp_sources"),
    path("general/time-sync/sync-now/", views.synchronize_ntp_now, name="sync_ntp_now"),
    path("general/time-sync/reset/", views.restore_default_ntp_configuration, name="reset_ntp_configuration"),
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
    path("speakers/<int:speaker_id>/remove/", views.delete_speaker, name="delete_speaker"),
    path("tests/audio-file/", views.test_audio_file, name="test_audio_file"),
    path("tests/maintenance-host/", views.test_maintenance_host, name="test_maintenance_host"),
    path("configuration-backup/export/", views.export_station_configuration, name="config_backup_export"),
    path("configuration-backup/preview/", views.preview_station_configuration_restore, name="config_backup_preview"),
    path("configuration-backup/restore/", views.restore_station_configuration, name="config_backup_restore"),
]
