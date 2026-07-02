from django.contrib import admin
from .models import AIModel


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