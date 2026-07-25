from django.contrib import admin

from .models import StationLocalSettings


@admin.register(StationLocalSettings)
class StationLocalSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "station_code",
        "station_name",
        "notification_host_name",
        "system_version",
        "config_version",
        "updated_at",
    )

    def has_add_permission(self, request):
        return not StationLocalSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
