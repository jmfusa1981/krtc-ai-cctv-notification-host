from django.contrib import admin
from .models import Camera


@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "camera_code",
        "name",
        "area",
        "status",
        "nvr_host",
        "nvr_channel",
        "nvr_recording_enabled",
        "created_at",
    )
    list_filter = (
        "area",
        "status",
        "nvr_recording_enabled",
    )
    search_fields = (
        "camera_code",
        "name",
        "area",
        "nvr_host",
        "nvr_camera_uid",
    )
    fieldsets = (
        (None, {"fields": ("camera_code", "name", "area", "status", "is_active", "is_online")}),
        ("Stream", {"fields": ("rtsp_url", "username", "password")}),
        (
            "NVR Evidence Export",
            {
                "fields": (
                    "nvr_recording_enabled",
                    "nvr_host",
                    "nvr_port",
                    "nvr_channel",
                    "nvr_username",
                    "nvr_password",
                    "nvr_camera_uid",
                )
            },
        ),
        ("Notes", {"fields": ("description", "last_checked_at")}),
    )
    ordering = ("camera_code", "id")
