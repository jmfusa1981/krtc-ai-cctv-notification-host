from django.contrib import admin

from .models import (
    SpeakerDevice,
    AudioFile,
    BroadcastRule,
    BroadcastLog,
)


@admin.register(SpeakerDevice)
class SpeakerDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "speaker_code",
        "name",
        "station_name",
        "area",
        "ip_address",
        "port",
        "protocol",
        "status",
        "is_active",
        "last_checked_at",
    )
    list_filter = (
        "status",
        "protocol",
        "is_active",
        "station_name",
        "area",
    )
    search_fields = (
        "speaker_code",
        "name",
        "station_name",
        "area",
        "location_note",
        "ip_address",
    )
    ordering = ("speaker_code",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "endpoint_base_url",
    )


@admin.register(AudioFile)
class AudioFileAdmin(admin.ModelAdmin):
    list_display = (
        "audio_code",
        "name",
        "audio_type",
        "duration_seconds",
        "is_active",
        "created_at",
    )
    list_filter = (
        "audio_type",
        "is_active",
    )
    search_fields = (
        "audio_code",
        "name",
        "message_text",
        "description",
    )
    ordering = ("audio_code",)
    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(BroadcastRule)
class BroadcastRuleAdmin(admin.ModelAdmin):
    list_display = (
        "rule_code",
        "name",
        "event_type",
        "camera",
        "speaker",
        "audio_file",
        "priority",
        "auto_broadcast",
        "is_active",
    )
    list_filter = (
        "event_type",
        "auto_broadcast",
        "is_active",
        "speaker",
        "audio_file",
    )
    search_fields = (
        "rule_code",
        "name",
        "description",
        "camera__camera_code",
        "camera__name",
        "speaker__speaker_code",
        "speaker__name",
        "audio_file__audio_code",
        "audio_file__name",
    )
    ordering = (
        "priority",
        "rule_code",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(BroadcastLog)
class BroadcastLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event",
        "rule",
        "speaker",
        "audio_file",
        "status",
        "requested_at",
        "started_at",
        "finished_at",
    )
    list_filter = (
        "status",
        "speaker",
        "audio_file",
        "requested_at",
    )
    search_fields = (
        "message",
        "speaker__speaker_code",
        "speaker__name",
        "audio_file__audio_code",
        "audio_file__name",
        "rule__rule_code",
        "rule__name",
    )
    ordering = ("-created_at",)
    readonly_fields = (
        "created_at",
        "updated_at",
    )