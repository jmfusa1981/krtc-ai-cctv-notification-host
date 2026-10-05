from django import forms
from django.contrib import admin

from apps.notifications.runtime_config import get_broadcast_runtime_config
from apps.station_api.security_audit import record_security_audit

from .models import (
    BroadcastEngineeringSettings,
    StationLocalSettings,
    UIConfiguration,
)


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


@admin.register(BroadcastEngineeringSettings)
class BroadcastEngineeringSettingsAdmin(admin.ModelAdmin):
    class BroadcastEngineeringSettingsAdminForm(forms.ModelForm):
        broadcast_test_mode = forms.TypedChoiceField(
            label="廣播運行模式",
            choices=(
                ("formal", "正式模式（PJSIP）"),
                ("test", "測試模式（Simulation）"),
            ),
            coerce=lambda value: value == "test",
            required=True,
            widget=forms.RadioSelect,
            help_text=(
                "正式模式（PJSIP）：會實際呼叫站區 IP Speaker。"
                "測試模式（Simulation）：只模擬廣播流程，不呼叫實體 Speaker。"
            ),
        )

        class Meta:
            model = BroadcastEngineeringSettings
            fields = "__all__"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if not self.is_bound and self.instance.broadcast_test_mode is None:
                backend = get_broadcast_runtime_config().operational_backend
                self.initial["broadcast_test_mode"] = (
                    "formal" if backend == "pjsip" else "test"
                )

    form = BroadcastEngineeringSettingsAdminForm

    fieldsets = (
        (
            "廣播運行模式",
            {
                "fields": (
                    "broadcast_test_mode",
                ),
            },
        ),
        (
            "PJSIP Runtime",
            {
                "fields": (
                    "pjsip_executable_path",
                    "pjsip_local_ip",
                    "pjsip_advertise_ip",
                    "pjsip_local_sip_port_base",
                    "pjsip_local_rtp_port_base",
                    "pjsip_port_step",
                    "pjsip_audio_gain_percent",
                ),
            },
        ),
        (
            "診斷狀態",
            {
                "fields": (
                    "last_diagnostic_status",
                    "last_diagnostic_message",
                    "last_diagnostic_at",
                    "updated_at",
                ),
            },
        ),
    )

    readonly_fields = (
        "last_diagnostic_status",
        "last_diagnostic_message",
        "last_diagnostic_at",
        "updated_at",
    )

    def has_module_permission(self, request):
        return bool(
            request.user
            and request.user.is_superuser
        )

    def has_view_permission(self, request, obj=None):
        return bool(
            request.user
            and request.user.is_superuser
        )

    def has_change_permission(self, request, obj=None):
        return bool(
            request.user
            and request.user.is_superuser
        )

    def has_add_permission(self, request):
        return bool(
            request.user
            and request.user.is_superuser
            and not BroadcastEngineeringSettings.objects.exists()
        )

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        previous_backend = get_broadcast_runtime_config().operational_backend
        previous = (
            BroadcastEngineeringSettings.objects
            .filter(pk=BroadcastEngineeringSettings.SINGLETON_PK)
            .values_list("broadcast_test_mode", flat=True)
            .first()
        )
        super().save_model(request, obj, form, change)

        if not change or previous != obj.broadcast_test_mode:
            new_backend = "simulation" if obj.broadcast_test_mode else "pjsip"
            record_security_audit(
                action="BROADCAST_RUNTIME_MODE_CHANGED",
                result="success",
                request=request,
                user=request.user,
                detail=(
                    f"廣播運行模式由 {previous_backend} 變更為 {new_backend}。"
                ),
                metadata={
                    "old_mode": previous_backend,
                    "new_mode": new_backend,
                },
            )


@admin.register(UIConfiguration)
class UIConfigurationAdmin(admin.ModelAdmin):
    change_form_template = (
        "admin/settings_app/uiconfiguration/change_form.html"
    )

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
                ),
            },
        ),
        (
            "系統資訊",
            {
                "fields": (
                    "updated_at",
                ),
            },
        ),
    )

    readonly_fields = (
        "updated_at",
    )

    def has_module_permission(self, request):
        return bool(
            request.user
            and request.user.is_superuser
        )

    def has_view_permission(self, request, obj=None):
        return bool(
            request.user
            and request.user.is_superuser
        )

    def has_change_permission(self, request, obj=None):
        return bool(
            request.user
            and request.user.is_superuser
        )

    def has_add_permission(self, request):
        return bool(
            request.user
            and request.user.is_superuser
            and not UIConfiguration.objects.exists()
        )

    def has_delete_permission(self, request, obj=None):
        return False
