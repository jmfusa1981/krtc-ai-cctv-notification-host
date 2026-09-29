from django.contrib import admin

from .models import ConfigurationAuditLog, DeviceFaultChange, DeviceFaultLog, InferenceHostConfiguration, OccSyncLog, OccSyncState, SecurityAuditLog


@admin.register(InferenceHostConfiguration)
class InferenceHostConfigurationAdmin(admin.ModelAdmin):
    list_display = ("inference_host", "selected_model", "config_version", "applied_at", "applied_by")
    readonly_fields = ("applied_at",)


@admin.register(ConfigurationAuditLog)
class ConfigurationAuditLogAdmin(admin.ModelAdmin):
    list_display = ("received_at", "station_code", "inference_host_code", "model_code", "config_version", "status", "operator_code")
    list_filter = ("status", "station_code", "inference_host_code")
    search_fields = ("config_version", "operator_code", "reason")
    readonly_fields = tuple(field.name for field in ConfigurationAuditLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(OccSyncState)
class OccSyncStateAdmin(admin.ModelAdmin):
    list_display = ("singleton_key", "last_event_id", "last_heartbeat_at", "last_daily_sync_at", "consecutive_failures")
    readonly_fields = tuple(field.name for field in OccSyncState._meta.fields)


@admin.register(OccSyncLog)
class OccSyncLogAdmin(admin.ModelAdmin):
    list_display = ("started_at", "kind", "status", "item_count", "http_status", "error")
    list_filter = ("kind", "status")
    readonly_fields = tuple(field.name for field in OccSyncLog._meta.fields)

@admin.register(DeviceFaultLog)
class DeviceFaultLogAdmin(admin.ModelAdmin):
    list_display = (
        "occurred_at",
        "station_code",
        "device_type",
        "device_code",
        "device_name",
        "fault_code",
        "status",
        "recovered_at",
    )
    list_filter = ("station_code", "device_type", "severity", "status")
    search_fields = (
        "station_code",
        "station_name",
        "device_code",
        "device_name",
        "area",
        "fault_code",
        "fault_description",
    )
    ordering = ("-occurred_at", "-id")
    date_hierarchy = "occurred_at"
    list_per_page = 50
    list_max_show_all = 200
    readonly_fields = tuple(field.name for field in DeviceFaultLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DeviceFaultChange)
class DeviceFaultChangeAdmin(admin.ModelAdmin):
    list_display = ("id", "changed_at", "change_type", "source_fault_id", "station_code", "device_type", "device_code", "fault_code", "status", "occurrence_count")
    list_filter = ("change_type", "station_code", "device_type", "severity", "status")
    search_fields = ("station_code", "station_name", "device_code", "device_name", "area", "fault_code", "fault_description")
    ordering = ("-id",)
    date_hierarchy = "changed_at"
    list_per_page = 50
    list_max_show_all = 200
    readonly_fields = tuple(field.name for field in DeviceFaultChange._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SecurityAuditLog)
class SecurityAuditLogAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "username", "role", "action", "result", "auth_method", "client_ip")
    list_filter = ("role", "action", "result", "auth_method")
    search_fields = ("username", "display_name", "client_ip", "detail")
    ordering = ("-occurred_at", "-id")
    readonly_fields = tuple(field.name for field in SecurityAuditLog._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
