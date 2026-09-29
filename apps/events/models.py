from django.db import models, transaction
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime


class Event(models.Model):
    EVENT_TYPE_CHOICES = [
        ("escalator_fall", "電扶梯跌倒"),
        ("luggage_roll", "行李滾落"),
        ("large_luggage_intrusion", "大型行李進入限制區域"),
        ("wheelchair_detected", "輪椅偵測"),
        ("passenger_loitering", "旅客逗留過久"),
        ("crowd_count_abnormal", "人流數量異常"),
        ("fire_detected", "火災偵測"),
        ("smoke_detected", "煙霧偵測"),
        ("other", "其他"),
    ]

    STATUS_CHOICES = [
        ("new", "New"),
        ("processing", "Processing"),
        ("confirmed", "Confirmed"),
        ("dismissed", "Dismissed"),
        ("closed", "Closed"),
    ]

    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        verbose_name="攝影機",
    )

    ai_model = models.ForeignKey(
        "ai_bridge.AIModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        verbose_name="AI 模型",
    )

    event_type = models.CharField(
        max_length=50,
        choices=EVENT_TYPE_CHOICES,
        default="other",
        verbose_name="事件類型",
    )

    confidence = models.FloatField(
        default=0.0,
        verbose_name="信心分數",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="new",
        verbose_name="處理狀態",
    )

    snapshot = models.ImageField(
        upload_to="event_snapshots/",
        null=True,
        blank=True,
        verbose_name="事件快照",
    )

    # 正式 AI 推論主機來源資訊
    source_host = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="來源主機",
        help_text="產生此事件的外部 AI 推論主機。",
    )

    source_event_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="來源事件 ID",
        help_text="外部 AI 推論主機所建立的事件識別碼。",
    )

    # KRTC V5.14 DAILY EVENT NUMBER START
    # Stable PAO-side daily record number.  The database PK remains unchanged.
    record_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="事件紀錄日期",
    )
    record_sequence = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="當日事件流水號",
    )
    # KRTC V5.14 DAILY EVENT NUMBER END

    event_id = models.CharField(max_length=150, null=True, blank=True, unique=True, db_index=True)
    message_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    station_code = models.CharField(max_length=50, blank=True, default="", db_index=True)
    inference_host_code = models.CharField(max_length=50, blank=True, default="", db_index=True)
    camera_code = models.CharField(max_length=50, blank=True, default="", db_index=True)
    event_code = models.CharField(max_length=50, blank=True, default="", db_index=True)
    video_url = models.URLField(max_length=1000, blank=True, default="")
    mapping_status = models.CharField(max_length=20, default="resolved", db_index=True)
    ack_status = models.CharField(max_length=20, default="accepted", db_index=True)
    received_at = models.DateTimeField(default=timezone.now)
    external_station_name = models.CharField(max_length=100, blank=True, default="")
    roi_id = models.CharField(max_length=100, null=True, blank=True)
    bbox = models.JSONField(null=True, blank=True)
    ingestion_mode = models.CharField(max_length=20, default="websocket")
    occ_sync_status = models.CharField(max_length=20, default="pending", db_index=True)
    occ_sync_attempts = models.PositiveIntegerField(default=0)
    occ_last_error = models.CharField(max_length=500, blank=True)
    occ_last_attempt_at = models.DateTimeField(null=True, blank=True)
    occ_synced_at = models.DateTimeField(null=True, blank=True)

    source_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="來源原始資料",
        help_text="從 AI 推論主機取得的原始 JSON payload。",
    )

    snapshot_url = models.URLField(
        max_length=1000,
        blank=True,
        default="",
        verbose_name="遠端快照 URL",
        help_text="AI 推論主機提供的遠端事件快照網址。",
    )

    severity = models.CharField(
        max_length=30,
        blank=True,
        default="",
        db_index=True,
        verbose_name="事件嚴重程度",
        help_text="AI 推論主機回傳的事件嚴重程度。",
    )

    description = models.TextField(
        blank=True,
        verbose_name="事件說明",
    )

    detected_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="偵測時間",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="建立時間",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新時間",
    )

    class Meta:
        verbose_name = "Event"
        verbose_name_plural = "Events"
        ordering = ["-detected_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "station_code",
                    "inference_host_code",
                    "source_event_id",
                    "detected_at",
                ],
                condition=(
                    ~Q(station_code="")
                    & ~Q(inference_host_code="")
                    & Q(source_event_id__isnull=False)
                ),
                name="unique_event_station_host_source_time",
            ),
            models.UniqueConstraint(
                fields=["record_date", "record_sequence"],
                condition=(
                    Q(record_date__isnull=False)
                    & Q(record_sequence__isnull=False)
                ),
                name="unique_event_record_date_sequence",
            ),
        ]

    @property
    def record_number(self) -> str:
        """Human-facing daily event number: MMDD + four-digit sequence."""
        if self.record_date and self.record_sequence:
            return f"{self.record_date:%m%d}{self.record_sequence:04d}"
        return str(self.pk or "")

    def _record_local_date(self):
        """以可辨識的事件時間配置每日流水號日期。"""
        detected = self.detected_at or timezone.now()
        if isinstance(detected, str):
            detected = parse_datetime(detected)
            if detected is None:
                detected = timezone.now()
        if timezone.is_naive(detected):
            detected = timezone.make_aware(detected, timezone.get_current_timezone())
        return timezone.localtime(detected).date()

    def save(self, *args, **kwargs):
        """Allocate a stable PAO daily sequence without changing the database PK."""
        needs_date = self.record_date is None
        needs_sequence = self.record_sequence is None

        if needs_date:
            self.record_date = self._record_local_date()

        if needs_sequence:
            with transaction.atomic():
                existing_max = (
                    Event.objects.filter(record_date=self.record_date)
                    .aggregate(max_sequence=Max("record_sequence"))
                    .get("max_sequence")
                    or 0
                )
                counter, _created = EventDailyCounter.objects.select_for_update().get_or_create(
                    event_date=self.record_date,
                    defaults={"last_sequence": existing_max},
                )
                if counter.last_sequence < existing_max:
                    counter.last_sequence = existing_max
                counter.last_sequence += 1
                counter.save(update_fields=["last_sequence", "updated_at"])
                self.record_sequence = counter.last_sequence

                update_fields = kwargs.get("update_fields")
                if update_fields is not None:
                    kwargs["update_fields"] = list(
                        set(update_fields) | {"record_date", "record_sequence"}
                    )
                return super().save(*args, **kwargs)

        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.camera}"


class EventDailyCounter(models.Model):
    event_date = models.DateField(unique=True, db_index=True)
    last_sequence = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-event_date"]
        verbose_name = "Event daily counter"
        verbose_name_plural = "Event daily counters"

    def __str__(self):
        return f"{self.event_date}: {self.last_sequence}"


class EventUpdateLog(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="update_logs")
    message_id = models.CharField(max_length=100, blank=True, default="")
    updated_fields = models.JSONField(default=list, blank=True)
    source_payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-received_at"]


class EventRecordingEvidence(models.Model):
    STATUS_PENDING = "pending"
    STATUS_REQUESTED = "requested"
    STATUS_EXPORTING = "exporting"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "等待匯出"),
        (STATUS_REQUESTED, "已取得匯出 ID"),
        (STATUS_EXPORTING, "匯出中"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_FAILED, "失敗"),
    ]

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="recording_evidences",
        verbose_name="事件",
    )
    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recording_evidences",
        verbose_name="攝影機",
    )
    nvr_host = models.CharField(max_length=100, blank=True, db_index=True)
    nvr_port = models.PositiveIntegerField(null=True, blank=True)
    nvr_channel = models.IntegerField(null=True, blank=True)
    video_format = models.CharField(max_length=10, default="MP4")
    pre_event_seconds = models.PositiveIntegerField(default=30)
    post_event_seconds = models.PositiveIntegerField(default=90)
    evidence_start_at = models.DateTimeField()
    evidence_end_at = models.DateTimeField()
    export_id = models.CharField(max_length=100, blank=True, db_index=True)
    export_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    export_rate = models.PositiveSmallIntegerField(default=0)
    ffmpeg_status = models.IntegerField(null=True, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to="event_recordings/", blank=True)
    download_url = models.URLField(max_length=1000, blank=True, default="")
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    requested_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Event recording evidence"
        verbose_name_plural = "Event recording evidences"
        ordering = ["-created_at"]

    @property
    def is_downloadable(self):
        return bool(
            self.export_status == self.STATUS_COMPLETED
            and (self.file or self.download_url)
        )

    def __str__(self):
        return f"Event {self.event_id} recording evidence ({self.export_status})"


class LocalAlarmPolicy(models.Model):
    """Singleton policy that isolates historical events from desktop alarms."""

    singleton_key = models.PositiveSmallIntegerField(
        default=1,
        unique=True,
        editable=False,
    )
    enabled_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="本機警報啟用時間",
    )
    is_enabled = models.BooleanField(
        default=True,
        verbose_name="啟用本機警報",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Local alarm policy"
        verbose_name_plural = "Local alarm policies"

    @classmethod
    def load(cls):
        policy, _created = cls.objects.get_or_create(singleton_key=1)
        return policy

    def __str__(self):
        return f"Local alarm enabled from {self.enabled_at.isoformat()}"


class CrowdFlowSetting(models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name="設定名稱",
    )

    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.CASCADE,
        related_name="crowd_flow_settings",
        verbose_name="攝影機",
    )

    min_count = models.PositiveIntegerField(
        default=0,
        verbose_name="最小人數",
    )

    max_count = models.PositiveIntegerField(
        default=100,
        verbose_name="最大人數",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="是否啟用",
    )

    description = models.TextField(
        blank=True,
        verbose_name="說明",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="建立時間",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新時間",
    )

    class Meta:
        verbose_name = "Crowd flow setting"
        verbose_name_plural = "Crowd flow settings"
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} ({self.min_count} - {self.max_count})"


class CrowdFlowRecord(models.Model):
    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.CASCADE,
        related_name="crowd_flow_records",
        verbose_name="攝影機",
    )

    count = models.PositiveIntegerField(
        default=0,
        verbose_name="人流數量",
    )

    is_abnormal = models.BooleanField(
        default=False,
        verbose_name="是否異常",
    )

    recorded_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="紀錄時間",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="建立時間",
    )

    class Meta:
        verbose_name = "Crowd flow record"
        verbose_name_plural = "Crowd flow records"
        ordering = ["-recorded_at", "-created_at"]

    def __str__(self):
        return f"{self.camera} - {self.count}"

class ZoneCountState(models.Model):
    """Latest zone-count state received from an inference host.

    This is current-state telemetry from GET /api/notify/zone_counts, not an
    event/history table. One row is kept per inference_host + camera_id + roi_id.
    """

    inference_host = models.ForeignKey(
        "ai_bridge.InferenceHost",
        on_delete=models.CASCADE,
        related_name="zone_count_states",
        verbose_name="推論主機",
    )
    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="zone_count_states",
        verbose_name="本站攝影機",
    )
    source_camera_id = models.CharField(max_length=100, verbose_name="來源 Camera ID")
    station = models.CharField(max_length=100, blank=True, default="", verbose_name="站別")
    roi_id = models.CharField(max_length=255, verbose_name="Zone 標籤")
    count = models.PositiveIntegerField(default=0, verbose_name="目前人數")
    threshold = models.PositiveIntegerField(null=True, blank=True, verbose_name="壅塞閾值")
    source_updated_at = models.DateTimeField(null=True, blank=True, verbose_name="來源更新時間")
    received_at = models.DateTimeField(default=timezone.now, verbose_name="PAO 接收時間")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新時間")

    class Meta:
        verbose_name = "Zone count state"
        verbose_name_plural = "Zone count states"
        ordering = ["inference_host__host_code", "source_camera_id", "roi_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["inference_host", "source_camera_id", "roi_id"],
                name="uq_zone_count_host_camera_roi",
            )
        ]
        indexes = [
            models.Index(fields=["inference_host", "source_camera_id"], name="idx_zone_host_camera"),
            models.Index(fields=["source_updated_at"], name="idx_zone_updated"),
        ]

    @property
    def is_abnormal(self):
        return self.threshold is not None and self.count >= self.threshold

    def __str__(self):
        return f"{self.inference_host.host_code} / {self.source_camera_id} / {self.roi_id}: {self.count}"

