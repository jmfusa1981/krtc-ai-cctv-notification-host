from django.contrib import admin

from .models import StationLocalSettings, UIConfiguration


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


@admin.register(UIConfiguration)
class UIConfigurationAdmin(admin.ModelAdmin):
    change_form_template = "admin/settings_app/uiconfiguration/change_form.html"
    fieldsets = (
        (
            "登入頁",
            {
                "fields": (
                    "login_theme",
                    "login_background_enabled",
                    "login_background",
                    "login_overlay_opacity",
                    "login_title",
                    "login_subtitle",
                    "login_footer_text",
                )
            },
        ),
        ("系統資訊", {"fields": ("updated_at",)}),
    )
    readonly_fields = ("updated_at",)

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_add_permission(self, request):
        return bool(request.user and request.user.is_superuser and not UIConfiguration.objects.exists())

    def has_delete_permission(self, request, obj=None):
        return False
