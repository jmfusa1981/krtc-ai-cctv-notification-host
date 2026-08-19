from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.validators import FileExtensionValidator

from apps.cameras.models import Camera
from apps.events.models import Event


class SpeakerDevice(models.Model):
    """
    IP Speaker / PAO 設備資料

    用途：
    1. 管理站點、區域、位置的廣播設備
    2. 預留 IP Speaker / PAO 串接資訊
    3. 後續可由 BroadcastRule 指定播放目標
    """

    STATUS_ONLINE = "online"
    STATUS_OFFLINE = "offline"
    STATUS_MAINTENANCE = "maintenance"
    STATUS_ERROR = "error"
    STATUS_UNKNOWN = "unknown"

    STATUS_CHOICES = [
        (STATUS_ONLINE, "Online"),
        (STATUS_OFFLINE, "Offline"),
        (STATUS_MAINTENANCE, "Maintenance"),
        (STATUS_ERROR, "Error"),
        (STATUS_UNKNOWN, "Unknown"),
    ]

    PROTOCOL_HTTP = "http"
    PROTOCOL_HTTPS = "https"
    PROTOCOL_SIP = "sip"
    PROTOCOL_RTSP = "rtsp"
    PROTOCOL_CUSTOM = "custom"

    PROTOCOL_CHOICES = [
        (PROTOCOL_HTTP, "HTTP"),
        (PROTOCOL_HTTPS, "HTTPS"),
        (PROTOCOL_SIP, "SIP"),
        (PROTOCOL_RTSP, "RTSP"),
        (PROTOCOL_CUSTOM, "Custom"),
    ]

    NETWORK_STATIC = "static"
    NETWORK_DHCP = "dhcp"
    NETWORK_MODE_CHOICES = [
        (NETWORK_STATIC, "固定 IP"),
        (NETWORK_DHCP, "DHCP"),
    ]

    CODEC_PCMU = "PCMU/8000"
    CODEC_PCMA = "PCMA/8000"
    CODEC_G726_32 = "G726-32/8000"
    CODEC_CHOICES = [
        (CODEC_PCMU, "G.711 μ-law (PCMU)"),
        (CODEC_PCMA, "G.711 A-law (PCMA)"),
        (CODEC_G726_32, "G.726 32 kbps"),
    ]

    speaker_code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Speaker Code",
        help_text="例如：SPK-001、PAO-A1",
    )

    name = models.CharField(
        max_length=100,
        verbose_name="Speaker Name",
        help_text="例如：月台區 A1 IP Speaker",
    )

    station_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Station Name",
        help_text="例如：R10 美麗島站",
    )

    area = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Area",
        help_text="例如：月台區、穿堂層、電扶梯區",
    )

    location_note = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Location Note",
        help_text="設備實際位置補充說明",
    )

    ip_address = models.GenericIPAddressField(
        verbose_name="IP Address",
        help_text="IP Speaker / PAO 的 IP 位址",
    )

    port = models.PositiveIntegerField(
        default=5060,
        verbose_name="SIP Port",
    )

    network_mode = models.CharField(
        max_length=10,
        choices=NETWORK_MODE_CHOICES,
        default=NETWORK_STATIC,
        verbose_name="Network Mode",
        help_text="記錄設備採固定 IP 或 DHCP；不會遠端改寫設備網路設定。",
    )

    preferred_codec = models.CharField(
        max_length=30,
        choices=CODEC_CHOICES,
        default=CODEC_PCMU,
        verbose_name="Preferred Codec",
    )

    protocol = models.CharField(
        max_length=20,
        choices=PROTOCOL_CHOICES,
        default=PROTOCOL_HTTP,
        verbose_name="Protocol",
    )

    sip_uri = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="SIP URI",
        help_text="例如：sip:4267@192.168.6.120。若使用 MicroSIP 撥號，優先使用此欄位。",
    )

    username = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Username",
    )

    password = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Password",
        help_text="PoC 階段暫存。正式版建議改用環境變數或加密儲存。",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_UNKNOWN,
        verbose_name="Status",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Is Active",
    )

    last_checked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Last Checked At",
    )

    description = models.TextField(
        blank=True,
        verbose_name="Description",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
    )

    class Meta:
        verbose_name = "Speaker Device"
        verbose_name_plural = "Speaker Devices"
        ordering = ["speaker_code"]

    def __str__(self):
        return f"{self.speaker_code} - {self.name}"

    def save(self, *args, **kwargs):
        self.speaker_code = (self.speaker_code or "").strip().upper()
        self.username = (self.username or "").strip()
        if self.protocol == self.PROTOCOL_SIP and self.username and self.ip_address:
            self.sip_uri = f"sip:{self.username}@{self.ip_address}:{self.port or 5060}"
        super().save(*args, **kwargs)

    @property
    def endpoint_base_url(self):
        return f"{self.protocol}://{self.ip_address}:{self.port}"

    @property
    def resolved_sip_uri(self):
        if self.sip_uri:
            return self.sip_uri.strip()
        sip_user = (self.username or "").strip()
        if not sip_user:
            return ""
        sip_port = self.port or 5060
        return f"sip:{sip_user}@{self.ip_address}:{sip_port}"


class AudioFile(models.Model):
    """
    預錄廣播音檔

    用途：
    1. 管理事件觸發時要播放的音檔
    2. 後續由 BroadcastRule 指定事件對應音檔
    """

    AUDIO_TYPE_ALERT = "alert"
    AUDIO_TYPE_GUIDANCE = "guidance"
    AUDIO_TYPE_WARNING = "warning"
    AUDIO_TYPE_TEST = "test"
    AUDIO_TYPE_OTHER = "other"

    AUDIO_TYPE_CHOICES = [
        (AUDIO_TYPE_ALERT, "Alert"),
        (AUDIO_TYPE_GUIDANCE, "Guidance"),
        (AUDIO_TYPE_WARNING, "Warning"),
        (AUDIO_TYPE_TEST, "Test"),
        (AUDIO_TYPE_OTHER, "Other"),
    ]

    audio_code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Audio Code",
        help_text="例如：AUD-FALL-001",
    )

    name = models.CharField(
        max_length=100,
        verbose_name="Audio Name",
        help_text="例如：電扶梯人員跌倒警示廣播",
    )

    audio_type = models.CharField(
        max_length=20,
        choices=AUDIO_TYPE_CHOICES,
        default=AUDIO_TYPE_ALERT,
        verbose_name="Audio Type",
    )

    file = models.FileField(
        upload_to="audio_files/",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["mp3", "wav", "ogg"]
            )
        ],
        verbose_name="Audio File",
    )

    duration_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Duration Seconds",
    )

    message_text = models.TextField(
        blank=True,
        verbose_name="Message Text",
        help_text="音檔對應的文字稿或廣播內容",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Is Active",
    )

    description = models.TextField(
        blank=True,
        verbose_name="Description",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
    )

    class Meta:
        verbose_name = "Audio File"
        verbose_name_plural = "Audio Files"
        ordering = ["audio_code"]

    def __str__(self):
        return f"{self.audio_code} - {self.name}"


class BroadcastRule(models.Model):
    """
    事件與廣播規則

    用途：
    AI Event / Event 發生後，根據 event_type / camera / location 找到對應規則，
    決定要讓哪一台 Speaker 播放哪一個音檔。
    """

    EVENT_ESCALATOR_FALL = "escalator_fall"
    EVENT_LUGGAGE_ROLL = "luggage_roll"
    EVENT_LARGE_LUGGAGE_INTRUSION = "large_luggage_intrusion"
    EVENT_WHEELCHAIR_DETECTED = "wheelchair_detected"
    EVENT_PASSENGER_LOITERING = "passenger_loitering"
    EVENT_CROWD_COUNT_ABNORMAL = "crowd_count_abnormal"
    EVENT_OTHER = "other"

    EVENT_TYPE_CHOICES = [
        (EVENT_ESCALATOR_FALL, "電扶梯人員跌倒"),
        (EVENT_LUGGAGE_ROLL, "大行李箱滾落"),
        (EVENT_LARGE_LUGGAGE_INTRUSION, "大件行李進入設定畫面區域"),
        (EVENT_WHEELCHAIR_DETECTED, "辨識輪椅"),
        (EVENT_PASSENGER_LOITERING, "旅客逾時滯留"),
        (EVENT_CROWD_COUNT_ABNORMAL, "人流統計異常"),
        (EVENT_OTHER, "其他"),
    ]

    rule_code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Rule Code",
        help_text="例如：RULE-FALL-A1",
    )

    name = models.CharField(
        max_length=100,
        verbose_name="Rule Name",
        help_text="例如：月台 A1 跌倒事件廣播規則",
    )

    event_type = models.CharField(
        max_length=50,
        choices=EVENT_TYPE_CHOICES,
        verbose_name="Event Type",
    )

    camera = models.ForeignKey(
        Camera,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="broadcast_rules",
        verbose_name="Camera",
        help_text="可選。若不指定，代表此事件類型的通用規則。",
    )

    speaker = models.ForeignKey(
        SpeakerDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="legacy_broadcast_rules",
        verbose_name="Legacy Speaker Device",
        help_text="舊版單一 Speaker 相容欄位。新規則請使用 Speaker Devices 多選欄位。",
    )

    speakers = models.ManyToManyField(
        SpeakerDevice,
        blank=True,
        related_name="broadcast_rules",
        verbose_name="Speaker Devices",
        help_text="可多選。事件命中此 Rule 後，會對每一支 Speaker 建立個別廣播任務。",
    )

    audio_file = models.ForeignKey(
        AudioFile,
        on_delete=models.CASCADE,
        related_name="broadcast_rules",
        verbose_name="Audio File",
    )

    priority = models.PositiveIntegerField(
        default=100,
        verbose_name="Priority",
        help_text="數字越小優先權越高。",
    )

    auto_broadcast = models.BooleanField(
        default=True,
        verbose_name="Auto Broadcast",
        help_text="是否在事件發生後自動建立廣播紀錄。",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Is Active",
    )

    description = models.TextField(
        blank=True,
        verbose_name="Description",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
    )

    class Meta:
        verbose_name = "Broadcast Rule"
        verbose_name_plural = "Broadcast Rules"
        ordering = ["priority", "rule_code"]

    def __str__(self):
        return f"{self.rule_code} - {self.name}"

    def target_speakers_queryset(self, *, active_only=False):
        queryset = self.speakers.all().order_by("speaker_code")
        if active_only:
            queryset = queryset.filter(is_active=True)
        if self.pk and queryset.exists():
            return queryset
        if self.speaker_id is None:
            return SpeakerDevice.objects.none()
        fallback = SpeakerDevice.objects.filter(pk=self.speaker_id)
        if active_only:
            fallback = fallback.filter(is_active=True)
        return fallback.order_by("speaker_code")

    def target_speaker_codes(self):
        return ", ".join(
            self.target_speakers_queryset().values_list("speaker_code", flat=True)
        )


class BroadcastLog(models.Model):
    """
    廣播紀錄

    用途：
    1. 記錄事件發生後是否建立廣播任務
    2. 預留後續實際呼叫 IP Speaker / PAO API 的結果
    3. Demo 階段可先用 pending / success / failed 表示流程
    """

    STATUS_PENDING = "pending"
    STATUS_PLAYING = "playing"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PLAYING, "Playing"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
    ]

    event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="broadcast_logs",
        verbose_name="Event",
    )

    rule = models.ForeignKey(
        BroadcastRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="broadcast_logs",
        verbose_name="Broadcast Rule",
    )

    speaker = models.ForeignKey(
        SpeakerDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="broadcast_logs",
        verbose_name="Speaker Device",
    )

    audio_file = models.ForeignKey(
        AudioFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="broadcast_logs",
        verbose_name="Audio File",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        verbose_name="Status",
    )

    request_payload = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Request Payload",
        help_text="預留後續實際呼叫 Speaker API 時記錄 request。",
    )

    response_payload = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Response Payload",
        help_text="預留後續實際呼叫 Speaker API 時記錄 response。",
    )

    message = models.TextField(
        blank=True,
        verbose_name="Message",
    )

    requested_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="Requested At",
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Started At",
    )

    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Finished At",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
    )

    class Meta:
        verbose_name = "Broadcast Log"
        verbose_name_plural = "Broadcast Logs"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["speaker"],
                condition=models.Q(
                    speaker__isnull=False,
                    status__in=["pending", "playing"],
                ),
                name="uniq_active_broadcast_per_speaker",
            ),
        ]

    def __str__(self):
        speaker_code = self.speaker.speaker_code if self.speaker else "No Speaker"
        audio_code = self.audio_file.audio_code if self.audio_file else "No Audio"
        return f"{speaker_code} / {audio_code} / {self.status}"

class BroadcastSchedule(models.Model):
    """Minimal single-station prerecorded broadcast schedule."""

    TYPE_ONCE = "once"
    TYPE_DAILY = "daily"
    TYPE_CHOICES = [
        (TYPE_ONCE, "單次"),
        (TYPE_DAILY, "每日"),
    ]

    name = models.CharField(max_length=100, verbose_name="Schedule Name")
    schedule_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default=TYPE_ONCE,
        verbose_name="Schedule Type",
    )
    audio_file = models.ForeignKey(
        AudioFile,
        on_delete=models.PROTECT,
        related_name="broadcast_schedules",
        verbose_name="Audio File",
    )
    speakers = models.ManyToManyField(
        SpeakerDevice,
        related_name="broadcast_schedules",
        verbose_name="Speaker Devices",
    )
    run_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="One-time Run At",
        help_text="單次排程使用。",
    )
    daily_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name="Daily Time",
        help_text="每日排程使用。",
    )
    next_run_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Next Run At",
    )
    last_run_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Last Run At",
    )
    volume_percent = models.PositiveSmallIntegerField(default=100, verbose_name="Volume Percent")
    is_active = models.BooleanField(default=True, verbose_name="Is Active")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_broadcast_schedules",
        verbose_name="Created By",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Broadcast Schedule"
        verbose_name_plural = "Broadcast Schedules"
        ordering = ["next_run_at", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_schedule_type_display()})"

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.schedule_type == self.TYPE_ONCE and not self.run_at:
            errors["run_at"] = "單次排程必須設定執行日期時間。"
        if self.schedule_type == self.TYPE_DAILY and not self.daily_time:
            errors["daily_time"] = "每日排程必須設定執行時間。"
        if errors:
            raise ValidationError(errors)

    def calculate_next_run(self, reference=None):
        import datetime
        from django.utils import timezone

        reference = reference or timezone.now()
        if self.schedule_type == self.TYPE_ONCE:
            return self.run_at if self.run_at and self.run_at > reference else None

        if not self.daily_time:
            return None
        local_reference = timezone.localtime(reference)
        candidate = timezone.make_aware(
            datetime.datetime.combine(local_reference.date(), self.daily_time),
            timezone.get_current_timezone(),
        )
        if candidate <= reference:
            candidate += datetime.timedelta(days=1)
        return candidate

    def save(self, *args, **kwargs):
        if self.is_active and not self.next_run_at:
            self.next_run_at = self.calculate_next_run()
        if not self.is_active:
            self.next_run_at = None
        super().save(*args, **kwargs)
