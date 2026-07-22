from django.db import models
from django.db.models import Q
from django.utils import timezone


class Event(models.Model):
    EVENT_TYPE_CHOICES = [
        ("escalator_fall", "電扶梯跌倒"),
        ("luggage_roll", "行李滾落"),
        ("large_luggage_intrusion", "大型行李進入限制區域"),
        ("wheelchair_detected", "輪椅偵測"),
        ("passenger_loitering", "旅客逗留過久"),
        ("crowd_count_abnormal", "人流數量異常"),
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
        on_delete=models.CASCADE,
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
                fields=["source_host", "source_event_id"],
                condition=(
                    Q(source_host__isnull=False)
                    & Q(source_event_id__isnull=False)
                ),
                name="unique_event_source_host_event_id",
            ),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.camera}"


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