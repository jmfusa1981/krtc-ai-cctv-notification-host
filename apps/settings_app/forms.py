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
            "preferred_codec", "deployment_state", "health_monitor_enabled", "is_active",
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
            "deployment_state": forms.Select(attrs={"class": "form-control"}),
            "health_monitor_enabled": forms.CheckboxInput(),
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

from apps.ai_bridge.models import AIModel, InferenceCameraMapping, InferenceHost
from apps.cameras.models import Camera
from apps.notifications.models import AudioFile, BroadcastRule, BroadcastSchedule


class FrontendModelForm(forms.ModelForm):
    """Shared form styling for the non-admin maintenance UI."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "management-checkbox")
            else:
                widget.attrs.setdefault("class", "form-control")


class InferenceHostForm(FrontendModelForm):
    class Meta:
        model = InferenceHost
        fields = [
            "host_code", "name", "station_code", "host_type", "ip_address", "port",
            "base_url", "configuration_url",
            "health_url", "events_url", "websocket_url",
            "websocket_auth_mode", "timeout_seconds", "is_active", "description",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean_host_code(self):
        return self.cleaned_data["host_code"].strip().upper()

    def clean(self):
        cleaned = super().clean()
        base_url = (cleaned.get("base_url") or "").rstrip("/")
        if base_url:
            cleaned["base_url"] = base_url
            cleaned["health_url"] = (cleaned.get("health_url") or f"{base_url}/health").strip()
            cleaned["events_url"] = (cleaned.get("events_url") or f"{base_url}/api/notify/events").strip()
        return cleaned


class CameraForm(FrontendModelForm):
    class Meta:
        model = Camera
        fields = [
            "camera_code", "name", "area", "rtsp_url", "username", "password",
            "status", "is_active", "description",
        ]
        widgets = {
            "password": forms.PasswordInput(render_value=True),
            "description": forms.Textarea(attrs={"rows": 3}),
            "rtsp_url": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_camera_code(self):
        return self.cleaned_data["camera_code"].strip().upper()


class InferenceCameraMappingForm(FrontendModelForm):
    class Meta:
        model = InferenceCameraMapping
        fields = ["inference_host", "source_camera_id", "camera", "is_active", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean_source_camera_id(self):
        return self.cleaned_data["source_camera_id"].strip()


class AIModelForm(FrontendModelForm):
    class Meta:
        model = AIModel
        fields = [
            "model_code", "name", "version", "event_type", "api_url", "model_path",
            "confidence_threshold", "is_active", "description",
        ]
        widgets = {
            "model_path": forms.Textarea(attrs={"rows": 2}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_model_code(self):
        return self.cleaned_data["model_code"].strip().upper()

    def clean_confidence_threshold(self):
        value = self.cleaned_data["confidence_threshold"]
        if not 0 <= value <= 1:
            raise forms.ValidationError("信心門檻必須介於 0 與 1。")
        return value


class AudioFileForm(FrontendModelForm):
    class Meta:
        model = AudioFile
        fields = [
            "audio_code", "name", "audio_type", "file", "duration_seconds",
            "message_text", "is_active", "description",
        ]
        widgets = {
            "message_text": forms.Textarea(attrs={"rows": 3}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_audio_code(self):
        return self.cleaned_data["audio_code"].strip().upper()


class BroadcastRuleForm(FrontendModelForm):
    class Meta:
        model = BroadcastRule
        fields = [
            "rule_code", "name", "event_type", "camera", "speakers", "audio_file",
            "priority", "auto_broadcast", "is_active", "description",
        ]
        widgets = {
            "speakers": forms.SelectMultiple(attrs={"size": 6}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        speakers_field = self.fields.get("speakers")
        if speakers_field:
            speakers_field.required = True
            speakers_field.label = "Speaker Devices"
            speakers_field.queryset = SpeakerDevice.objects.all().order_by("speaker_code")

        instance = getattr(self, "instance", None)
        if (
            instance
            and instance.pk
            and not self.is_bound
            and speakers_field
            and not instance.speakers.exists()
            and instance.speaker_id
        ):
            self.initial["speakers"] = [instance.speaker_id]

    def clean_rule_code(self):
        return self.cleaned_data["rule_code"].strip().upper()

    def clean_speakers(self):
        speakers = self.cleaned_data.get("speakers")
        if not speakers:
            raise forms.ValidationError("請至少選擇一支 Speaker。")
        return speakers

    def save(self, commit=True):
        instance = super().save(commit=False)
        speakers = list(self.cleaned_data.get("speakers") or [])
        instance.speaker = speakers[0] if speakers else None
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class BroadcastScheduleForm(FrontendModelForm):
    class Meta:
        model = BroadcastSchedule
        fields = [
            "name", "schedule_type", "audio_file", "speakers", "run_at",
            "daily_time", "volume_percent", "is_active",
        ]
        widgets = {
            "run_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "daily_time": forms.TimeInput(attrs={"type": "time"}),
            "speakers": forms.SelectMultiple(attrs={"size": 6}),
        }

    def clean_volume_percent(self):
        value = self.cleaned_data["volume_percent"]
        if not 1 <= value <= 100:
            raise forms.ValidationError("音量必須介於 1 到 100%。")
        return value

    def clean(self):
        cleaned = super().clean()
        schedule_type = cleaned.get("schedule_type")
        if schedule_type == BroadcastSchedule.TYPE_ONCE and not cleaned.get("run_at"):
            self.add_error("run_at", "單次排程必須設定執行日期時間。")
        if schedule_type == BroadcastSchedule.TYPE_DAILY and not cleaned.get("daily_time"):
            self.add_error("daily_time", "每日排程必須設定執行時間。")
        if not cleaned.get("speakers"):
            self.add_error("speakers", "至少選擇一台 Speaker。")
        return cleaned


class FrontendUserForm(forms.Form):
    ROLE_CHOICES = [
        ("Operator", "Operator｜操作人員"),
        ("Maintainer", "Maintainer｜維護人員"),
        ("Administrator", "Administrator｜系統管理員"),
    ]

    username = forms.CharField(max_length=150, label="帳號")
    first_name = forms.CharField(max_length=150, required=False, label="顯示名稱")
    email = forms.EmailField(required=False, label="電子郵件")
    role = forms.ChoiceField(choices=ROLE_CHOICES, label="角色")
    password = forms.CharField(required=False, widget=forms.PasswordInput, label="新密碼")
    is_active = forms.BooleanField(required=False, initial=True, label="啟用帳號")

    def __init__(self, *args, user_instance=None, **kwargs):
        self.user_instance = user_instance
        initial = kwargs.setdefault("initial", {})
        if user_instance:
            initial.setdefault("username", user_instance.username)
            initial.setdefault("first_name", user_instance.first_name)
            initial.setdefault("email", user_instance.email)
            initial.setdefault("is_active", user_instance.is_active)
            role = user_instance.groups.filter(name__in=["Operator", "Maintainer", "Administrator"]).values_list("name", flat=True).first()
            initial.setdefault("role", role or "Operator")
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "management-checkbox")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean_username(self):
        from django.contrib.auth import get_user_model
        username = self.cleaned_data["username"].strip()
        query = get_user_model().objects.filter(username__iexact=username)
        if self.user_instance:
            query = query.exclude(pk=self.user_instance.pk)
        if query.exists():
            raise forms.ValidationError("此帳號已存在。")
        return username

    def clean_password(self):
        password = self.cleaned_data.get("password", "")
        if not self.user_instance and not password:
            raise forms.ValidationError("新增帳號時必須設定密碼。")
        if password and len(password) < 8:
            raise forms.ValidationError("密碼至少需要 8 個字元。")
        return password
