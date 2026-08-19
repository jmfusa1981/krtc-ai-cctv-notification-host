from django.contrib import admin

from .models import ConfigurationAuditLog, InferenceHostConfiguration, OccSyncLog, OccSyncState


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
