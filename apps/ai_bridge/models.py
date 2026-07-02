from django.db import models


class AIModel(models.Model):
    EVENT_TYPE_CHOICES = [
        ("escalator_fall", "電扶梯人員跌倒"),
        ("luggage_roll", "大行李箱滾落"),
        ("large_luggage_intrusion", "大件行李進入設定畫面區域"),
        ("wheelchair_detected", "辨識輪椅"),
        ("passenger_loitering", "旅客逾時滯留"),
        ("crowd_count_abnormal", "人流統計異常"),
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