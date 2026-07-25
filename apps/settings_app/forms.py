from django import forms

from .models import StationLocalSettings


class StationLocalSettingsForm(forms.ModelForm):
    class Meta:
        model = StationLocalSettings
        fields = [
            "station_code",
            "station_name",
            "notification_host_name",
            "system_version",
            "default_monitor_grid",
            "carousel_interval_seconds",
            "dashboard_refresh_seconds",
            "notification_sound_enabled",
            "warning_light_enabled",
            "auto_broadcast_enabled",
            "maintenance_host_url",
        ]
        widgets = {
            "station_code": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "station_name": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "notification_host_name": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "system_version": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "default_monitor_grid": forms.Select(attrs={"class": "form-control"}),
            "carousel_interval_seconds": forms.NumberInput(
                attrs={"class": "form-control", "min": 3, "max": 300, "step": 1}
            ),
            "dashboard_refresh_seconds": forms.NumberInput(
                attrs={"class": "form-control", "min": 2, "max": 60, "step": 1}
            ),
            "maintenance_host_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "例如：http://192.168.6.10:8000",
                    "autocomplete": "off",
                }
            ),
        }
        error_messages = {
            "station_code": {"required": "請輸入車站代碼。"},
            "station_name": {"required": "請輸入車站名稱。"},
            "notification_host_name": {"required": "請輸入通報主機名稱。"},
            "system_version": {"required": "請輸入系統版本。"},
            "maintenance_host_url": {"invalid": "請輸入有效的 HTTP 或 HTTPS URL。"},
        }

    def clean_station_code(self):
        value = self.cleaned_data["station_code"].strip().upper()
        if not value:
            raise forms.ValidationError("請輸入車站代碼。")
        return value

    def clean_station_name(self):
        value = self.cleaned_data["station_name"].strip()
        if not value:
            raise forms.ValidationError("請輸入車站名稱。")
        return value

    def clean_notification_host_name(self):
        value = self.cleaned_data["notification_host_name"].strip()
        if not value:
            raise forms.ValidationError("請輸入通報主機名稱。")
        return value

    def clean_system_version(self):
        value = self.cleaned_data["system_version"].strip()
        if not value:
            raise forms.ValidationError("請輸入系統版本。")
        return value

    def clean_dashboard_refresh_seconds(self):
        value = self.cleaned_data["dashboard_refresh_seconds"]
        if not 2 <= value <= 60:
            raise forms.ValidationError("Dashboard 更新間隔必須介於 2 到 60 秒。")
        return value
