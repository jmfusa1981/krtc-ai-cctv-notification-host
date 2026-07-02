from django.contrib import admin
from .models import Camera


@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "area",
        "created_at",
    )
    list_filter = (
        "area",
    )
    search_fields = (
        "name",
        "area",
    )
    ordering = ("id",)