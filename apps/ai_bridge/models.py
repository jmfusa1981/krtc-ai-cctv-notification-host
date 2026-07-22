from django.db import models
from django.db.models import Q


class AIModel(models.Model):
    EVENT_TYPE_CHOICES = [
        ("escalator_fall", "電扶梯跌倒"),
        ("luggage_roll", "行李滾落"),
        ("large_luggage_intrusion", "大型行李進入限制區域"),
        ("wheelchair_detected", "輪椅偵測"),
        ("passenger_loitering", "旅客逗留過久"),
        ("crowd_count_abnormal", "人流數量異常"),
        ("other", "其他"),
    ]

    name = models.CharField(
        max_length=100,
        verbose_name="模型名稱",
    )

    model_code = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="模型代碼",
    )

    version = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="版本",
    )

    event_type = models.CharField(
        max_length=50,
        choices=EVENT_TYPE_CHOICES,
        default="other",
        verbose_name="對應事件類型",
    )

    api_url = models.URLField(
        max_length=500,
        blank=True,
        verbose_name="AI API URL",
    )

    model_path = models.TextField(
        blank=True,
        verbose_name="模型路徑",
    )

    confidence_threshold = models.FloatField(
        default=0.8,
        verbose_name="信心分數門檻",
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
        verbose_name = "AI model"
        verbose_name_plural = "AI models"
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} ({self.version})"


class InferenceHost(models.Model):
    STATUS_ONLINE = "online"
    STATUS_OFFLINE = "offline"
    STATUS_ERROR = "error"
    STATUS_UNKNOWN = "unknown"
    STATUS_MAINTENANCE = "maintenance"

    STATUS_CHOICES = [
        (STATUS_ONLINE, "Online"),
        (STATUS_OFFLINE, "Offline"),
        (STATUS_ERROR, "Error"),
        (STATUS_UNKNOWN, "Unknown"),
        (STATUS_MAINTENANCE, "Maintenance"),
    ]

    host_code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="推論主機代碼",
        help_text="例如：INF-001",
    )

    name = models.CharField(
        max_length=100,
        verbose_name="推論主機名稱",
        help_text="例如：第一月台 AI 推論主機",
    )

    base_url = models.URLField(
        max_length=500,
        unique=True,
        verbose_name="Base URL",
        help_text="例如：http://192.168.6.20:8000",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="是否啟用",
    )

    timeout_seconds = models.PositiveIntegerField(
        default=10,
        verbose_name="HTTP Timeout 秒數",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_UNKNOWN,
        db_index=True,
        verbose_name="主機狀態",
    )

    last_health_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="最後 Health 檢查時間",
    )

    last_success_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="最後成功輪詢時間",
    )

    last_error_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="最後錯誤時間",
    )

    last_error = models.TextField(
        blank=True,
        verbose_name="最後錯誤訊息",
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
        verbose_name = "Inference host"
        verbose_name_plural = "Inference hosts"
        ordering = ["host_code"]

    def __str__(self):
        return f"{self.host_code} - {self.name}"

    @property
    def normalized_base_url(self):
        return self.base_url.rstrip("/")


class InferenceCameraMapping(models.Model):
    inference_host = models.ForeignKey(
        InferenceHost,
        on_delete=models.CASCADE,
        related_name="camera_mappings",
        verbose_name="推論主機",
    )

    source_camera_id = models.CharField(
        max_length=100,
        verbose_name="來源 Camera ID",
        help_text="推論主機 API 回傳的 camera_id，例如 cam_01。",
    )

    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.CASCADE,
        related_name="inference_camera_mappings",
        verbose_name="Django Camera",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
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
        verbose_name = "Inference camera mapping"
        verbose_name_plural = "Inference camera mappings"
        ordering = [
            "inference_host__host_code",
            "source_camera_id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "inference_host",
                    "source_camera_id",
                ],
                name="unique_inference_host_source_camera",
            ),
            models.UniqueConstraint(
                fields=[
                    "inference_host",
                    "camera",
                ],
                condition=Q(is_active=True),
                name="unique_active_camera_per_inference_host",
            ),
        ]

    def __str__(self):
        return (
            f"{self.inference_host.host_code} / "
            f"{self.source_camera_id} -> "
            f"{self.camera.camera_code}"
        )