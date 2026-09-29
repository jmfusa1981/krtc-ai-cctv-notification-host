from django import forms
from django.utils import timezone

from .models import AudioFile, BroadcastSchedule, SpeakerDevice


class BroadcastScheduleForm(forms.ModelForm):
    run_at = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        label="單次執行時間",
    )
    daily_time = forms.TimeField(
        required=False,
        input_formats=["%H:%M"],
        widget=forms.TimeInput(attrs={"type": "time"}),
        label="每日執行時間",
    )

    class Meta:
        model = BroadcastSchedule
        fields = [
            "name",
            "schedule_type",
            "audio_file",
            "speakers",
            "run_at",
            "daily_time",
            "volume_percent",
            "is_active",
        ]
        labels = {
            "name": "排程名稱",
            "schedule_type": "排程類型",
            "audio_file": "預錄音檔",
            "speakers": "播放 Speaker",
            "volume_percent": "播放音量 (%)",
            "is_active": "啟用排程",
        }
        widgets = {
            "speakers": forms.SelectMultiple(attrs={"size": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["audio_file"].queryset = AudioFile.objects.filter(is_active=True).order_by("audio_code")
        self.fields["speakers"].queryset = SpeakerDevice.objects.filter(is_active=True).order_by("speaker_code")

    def clean(self):
        cleaned = super().clean()
        schedule_type = cleaned.get("schedule_type")
        run_at = cleaned.get("run_at")
        daily_time = cleaned.get("daily_time")

        if schedule_type == BroadcastSchedule.TYPE_ONCE:
            if not run_at:
                self.add_error("run_at", "單次排程必須設定執行日期時間。")
            elif run_at <= timezone.now():
                self.add_error("run_at", "單次執行時間必須晚於目前時間。")
            cleaned["daily_time"] = None
        elif schedule_type == BroadcastSchedule.TYPE_DAILY:
            if not daily_time:
                self.add_error("daily_time", "每日排程必須設定執行時間。")
            cleaned["run_at"] = None
        volume = cleaned.get("volume_percent", 100)
        if volume is not None and not 0 <= volume <= 200:
            self.add_error("volume_percent", "音量必須介於 0～200%。")
        return cleaned
