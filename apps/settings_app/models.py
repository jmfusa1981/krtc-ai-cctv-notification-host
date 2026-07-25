from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class StationLocalSettings(models.Model):
    """單站通報主機的本機設定。

    一套通報主機只允許一筆設定資料。中央維護主機完成後，本站仍保存
    最後一次有效設定，確保中央連線中斷時可以持續執行事件通報。
    """

    SINGLETON_PK = 1
    GRID_CHOICES = [(1, "1 畫面"), (4, "4 畫面"), (9, "9 畫面"), (16, "16 畫面")]

    id = models.PositiveSmallIntegerField(primary_key=True, default=SINGLETON_PK, editable=False)
    station_code = models.CharField(max_length=30, default="DEMO", verbose_name="車站代碼")
    station_name = models.CharField(max_length=100, default="KRTC Demo Station", verbose_name="車站名稱")
    notification_host_name = models.CharField(
        max_length=100, default="KRTC Demo Station 通報主機", verbose_name="通報主機名稱"
    )
    system_version = models.CharField(max_length=50, default="V3", verbose_name="系統版本")

    default_monitor_grid = models.PositiveSmallIntegerField(
        choices=GRID_CHOICES, default=4, verbose_name="監視牆預設格數"
    )
    carousel_interval_seconds = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(3), MaxValueValidator(300)],
        verbose_name="輪播間隔秒數",
    )
    dashboard_refresh_seconds = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(2), MaxValueValidator(120)],
        verbose_name="Dashboard 更新秒數",
    )
    notification_sound_enabled = models.BooleanField(default=True, verbose_name="事件提示音")
    warning_light_enabled = models.BooleanField(default=True, verbose_name="警示燈")
    auto_broadcast_enabled = models.BooleanField(default=True, verbose_name="自動廣播")

    maintenance_host_url = models.URLField(
        max_length=500, blank=True, verbose_name="中央維護主機 URL"
    )
    config_version = models.PositiveIntegerField(default=1, verbose_name="設定版本")
    last_synced_at = models.DateTimeField(null=True, blank=True, verbose_name="最後中央同步時間")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="最後修改時間")

    class Meta:
        verbose_name = "單站本機設定"
        verbose_name_plural = "單站本機設定"

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return obj

    def __str__(self):
        return f"{self.station_code} - {self.station_name}"
