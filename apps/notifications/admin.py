from django.contrib import admin

from .models import (
    SpeakerDevice,
    AudioFile,
    BroadcastRule,
    BroadcastLog,
    BroadcastSchedule,
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
        "network_mode",
        "preferred_codec",
        "protocol",
        "sip_uri",
        "status",
        "is_active",
        "last_checked_at",
    )
    list_filter = (
        "status",
        "protocol",
        "network_mode",
        "preferred_codec",
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
        "sip_uri",
    )
    ordering = ("speaker_code",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "endpoint_base_url",
        "resolved_sip_uri",
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
        "speaker_targets",
        "audio_file",
        "priority",
        "auto_broadcast",
        "is_active",
    )
    list_filter = (
        "event_type",
        "auto_broadcast",
        "is_active",
        "speakers",
        "audio_file",
    )
    search_fields = (
        "rule_code",
        "name",
        "description",
        "camera__camera_code",
        "camera__name",
        "speakers__speaker_code",
        "speakers__name",
        "speakers__sip_uri",
        "speaker__speaker_code",
        "speaker__name",
        "speaker__sip_uri",
        "audio_file__audio_code",
        "audio_file__name",
    )
    exclude = ("speaker",)
    filter_horizontal = ("speakers",)
    ordering = (
        "priority",
        "rule_code",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )

    @admin.display(description="Speaker Devices")
    def speaker_targets(self, obj):
        return obj.target_speaker_codes() or "(no speaker)"


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
        "speaker__sip_uri",
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

@admin.register(BroadcastSchedule)
class BroadcastScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "schedule_type",
        "audio_file",
        "next_run_at",
        "last_run_at",
        "is_active",
    )
    list_filter = ("schedule_type", "is_active", "audio_file")
    search_fields = ("name", "audio_file__audio_code", "speakers__speaker_code")
    filter_horizontal = ("speakers",)
    readonly_fields = ("next_run_at", "last_run_at", "created_at", "updated_at")
