from django.contrib import admin

from .models import (
    AIModel,
    InferenceCameraMapping,
    InferenceHost,
)


@admin.register(AIModel)
class AIModelAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "model_code",
        "version",
        "event_type",
        "confidence_threshold",
        "is_active",
        "created_at",
    )

    list_filter = (
        "event_type",
        "is_active",
    )

    search_fields = (
        "name",
        "model_code",
        "version",
        "description",
    )

    ordering = ("id",)


@admin.register(InferenceHost)
class InferenceHostAdmin(admin.ModelAdmin):
    list_display = (
        "host_code",
        "name",
        "base_url",
        "status",
        "is_active",
        "timeout_seconds",
        "last_health_at",
        "last_success_at",
    )

    list_filter = (
        "status",
        "is_active",
    )

    search_fields = (
        "host_code",
        "name",
        "base_url",
        "description",
        "last_error",
    )

    readonly_fields = (
        "last_health_at",
        "last_success_at",
        "last_error_at",
        "last_error",
        "created_at",
        "updated_at",
    )

    ordering = (
        "host_code",
    )


@admin.register(InferenceCameraMapping)
class InferenceCameraMappingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "inference_host",
        "source_camera_id",
        "camera",
        "is_active",
        "updated_at",
    )

    list_filter = (
        "inference_host",
        "is_active",
    )

    search_fields = (
        "inference_host__host_code",
        "inference_host__name",
        "source_camera_id",
        "camera__camera_code",
        "camera__name",
    )

    autocomplete_fields = (
        "inference_host",
        "camera",
    )

    ordering = (
        "inference_host__host_code",
        "source_camera_id",
    )