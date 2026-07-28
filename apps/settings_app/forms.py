from django import forms

from apps.notifications.models import SpeakerDevice
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


class SpeakerDeviceForm(forms.ModelForm):
    class Meta:
        model = SpeakerDevice
        fields = [
            "speaker_code", "name", "area", "location_note",
            "network_mode", "ip_address", "port", "username",
            "preferred_codec", "is_active",
        ]
        widgets = {
            "speaker_code": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "name": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "area": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "location_note": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "network_mode": forms.Select(attrs={"class": "form-control"}),
            "ip_address": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "port": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 65535}),
            "username": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "preferred_codec": forms.Select(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(),
        }

    def clean_speaker_code(self):
        return self.cleaned_data["speaker_code"].strip().upper()

    def clean_port(self):
        value = self.cleaned_data["port"]
        if not 1 <= value <= 65535:
            raise forms.ValidationError("SIP Port 必須介於 1 到 65535。")
        return value

    def clean(self):
        cleaned = super().clean()
        if not (cleaned.get("username") or "").strip():
            self.add_error("username", "請輸入 SIP Username。")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.protocol = SpeakerDevice.PROTOCOL_SIP
        if commit:
            instance.save()
        return instance
