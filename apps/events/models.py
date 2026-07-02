from django.db import models
from django.utils import timezone


class Event(models.Model):
    EVENT_TYPE_CHOICES = [
        ("escalator_fall", "電扶梯人員跌倒"),
        ("luggage_roll", "大行李箱滾落"),
        ("large_luggage_intrusion", "大件行李進入設定畫面區域"),
        ("wheelchair_detected", "辨識輪椅"),
        ("passenger_loitering", "旅客逾時滯留"),
        ("crowd_count_abnormal", "人流統計異常"),
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
        verbose_name="事件截圖",
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
        verbose_name="人流下限",
    )

    max_count = models.PositiveIntegerField(
        default=100,
        verbose_name="人流上限",
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
        verbose_name="是否超出正常範圍",
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