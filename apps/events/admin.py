from django.contrib import admin
from .models import (
    Event,
    EventRecordingEvidence,
    CrowdFlowSetting,
    CrowdFlowRecord,
    ZoneCountState,
)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "camera",
        "ai_model",
        "event_type",
        "confidence",
        "status",
        "detected_at",
        "created_at",
    )

    list_filter = (
        "event_type",
        "status",
        "detected_at",
        "created_at",
    )

    search_fields = (
        "camera__name",
        "ai_model__name",
        "event_type",
        "description",
    )

    ordering = ("-detected_at", "-created_at")


@admin.register(EventRecordingEvidence)
class EventRecordingEvidenceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event",
        "camera",
        "nvr_host",
        "nvr_channel",
        "export_status",
        "export_rate",
        "evidence_start_at",
        "evidence_end_at",
        "created_at",
    )
    list_filter = ("export_status", "nvr_host", "created_at")
    search_fields = (
        "event__source_event_id",
        "event__event_id",
        "camera__camera_code",
        "nvr_host",
        "export_id",
        "file_name",
    )
    readonly_fields = (
        "request_payload",
        "response_payload",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)


@admin.register(CrowdFlowSetting)
class CrowdFlowSettingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "camera",
        "min_count",
        "max_count",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
        "camera",
    )

    search_fields = (
        "name",
        "camera__name",
        "description",
    )

    ordering = ("id",)


@admin.register(CrowdFlowRecord)
class CrowdFlowRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "camera",
        "count",
        "is_abnormal",
        "recorded_at",
        "created_at",
    )

    list_filter = (
        "is_abnormal",
        "camera",
        "recorded_at",
    )

    search_fields = (
        "camera__name",
    )

    ordering = ("-recorded_at", "-created_at")

@admin.register(ZoneCountState)
class ZoneCountStateAdmin(admin.ModelAdmin):
    list_display = (
        "inference_host",
        "source_camera_id",
        "roi_id",
        "count",
        "threshold",
        "source_updated_at",
        "received_at",
    )
    list_filter = ("inference_host", "station")
    search_fields = ("source_camera_id", "roi_id", "station", "camera__camera_code", "camera__name")
    readonly_fields = (
        "inference_host",
        "camera",
        "source_camera_id",
        "station",
        "roi_id",
        "count",
        "threshold",
        "source_updated_at",
        "received_at",
        "updated_at",
    )
    ordering = ("inference_host__host_code", "source_camera_id", "roi_id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

