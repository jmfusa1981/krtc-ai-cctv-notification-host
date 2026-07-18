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
        default=80,
        verbose_name="Port",
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

    @property
    def endpoint_base_url(self):
        return f"{self.protocol}://{self.ip_address}:{self.port}"

    @property
    def resolved_sip_uri(self):
        if self.sip_uri:
            return self.sip_uri
        return f"sip:{self.ip_address}"


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

    EVENT_FALL_DOWN = "fall_down"
    EVENT_LUGGAGE_ROLLING = "luggage_rolling"
    EVENT_LARGE_LUGGAGE_AREA = "large_luggage_area"
    EVENT_WHEELCHAIR = "wheelchair"
    EVENT_OVERSTAYED = "overstayed"
    EVENT_CROWD_FLOW_ABNORMAL = "crowd_flow_abnormal"

    EVENT_TYPE_CHOICES = [
        (EVENT_FALL_DOWN, "電扶梯人員跌倒"),
        (EVENT_LUGGAGE_ROLLING, "大行李箱滾落"),
        (EVENT_LARGE_LUGGAGE_AREA, "大件行李進入設定畫面區域"),
        (EVENT_WHEELCHAIR, "辨識輪椅"),
        (EVENT_OVERSTAYED, "旅客逾時滯留"),
        (EVENT_CROWD_FLOW_ABNORMAL, "人流統計異常"),
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
        on_delete=models.CASCADE,
        related_name="broadcast_rules",
        verbose_name="Speaker Device",
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