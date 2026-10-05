from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models


class StationLocalSettings(models.Model):
    """單站通報主機的本機設定。

    一套通報主機只允許一筆設定資料。中央維護主機完成後，本站仍保存
    最後一次有效設定，確保中央連線中斷時可以持續執行事件通報。
    """

    SINGLETON_PK = 1
    GRID_CHOICES = [
        (1, "1 畫面"),
        (4, "4 畫面"),
        (9, "9 畫面"),
        (16, "16 畫面"),
    ]

    id = models.PositiveSmallIntegerField(
        primary_key=True,
        default=SINGLETON_PK,
        editable=False,
    )

    station_code = models.CharField(
        max_length=30,
        default="DEMO",
        verbose_name="車站代碼",
    )

    station_name = models.CharField(
        max_length=100,
        default="KRTC Demo Station",
        verbose_name="車站名稱",
    )

    notification_host_name = models.CharField(
        max_length=100,
        default="KRTC Demo Station 通報主機",
        verbose_name="通報主機名稱",
    )

    system_version = models.CharField(
        max_length=50,
        default="V3",
        verbose_name="系統版本",
    )

    default_monitor_grid = models.PositiveSmallIntegerField(
        choices=GRID_CHOICES,
        default=4,
        verbose_name="監視牆預設格數",
    )

    carousel_interval_seconds = models.PositiveIntegerField(
        default=10,
        validators=[
            MinValueValidator(3),
            MaxValueValidator(300),
        ],
        verbose_name="輪播間隔秒數",
    )

    dashboard_refresh_seconds = models.PositiveIntegerField(
        default=5,
        validators=[
            MinValueValidator(2),
            MaxValueValidator(120),
        ],
        verbose_name="Dashboard 更新秒數",
    )

    notification_sound_enabled = models.BooleanField(
        default=True,
        verbose_name="事件提示音",
    )

    warning_light_enabled = models.BooleanField(
        default=True,
        verbose_name="警示燈",
    )

    auto_broadcast_enabled = models.BooleanField(
        default=True,
        verbose_name="自動廣播",
    )

    maintenance_host_url = models.URLField(
        max_length=500,
        blank=True,
        verbose_name="中央維護主機 URL",
    )

    config_version = models.PositiveIntegerField(
        default=1,
        verbose_name="設定版本",
    )

    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="最後中央同步時間",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="最後修改時間",
    )

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


class BroadcastEngineeringSettings(models.Model):
    """IP Speaker / PJSIP 工程 Runtime 設定。

    僅允許一筆設定資料。

    Production 正式廣播預設使用 PJSIP。
    Simulation 僅供 Superuser 於開發、驗證或維護期間明確啟用，
    不屬於正式營運預設。
    """

    SINGLETON_PK = 1

    id = models.PositiveSmallIntegerField(
        primary_key=True,
        default=SINGLETON_PK,
        editable=False,
    )

    broadcast_test_mode = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        verbose_name="廣播運行模式",
        help_text=(
            "未初始化時使用環境安全預設；儲存後由本設定決定正式 PJSIP "
            "或 Simulation 測試模式。"
        ),
    )

    pjsip_executable_path = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="PJSUA 執行檔路徑",
        help_text="例如 C:\\krtc-tools\\pjsip\\pjsua.exe",
    )

    pjsip_local_ip = models.GenericIPAddressField(
        protocol="IPv4",
        blank=True,
        null=True,
        verbose_name="PJSIP Local IP",
        help_text="通報主機實際用於 SIP/RTP 通訊的 IPv4 位址。",
    )

    pjsip_advertise_ip = models.GenericIPAddressField(
        protocol="IPv4",
        blank=True,
        null=True,
        verbose_name="PJSIP Advertise IP",
        help_text="PJSIP 對外宣告的 IPv4 位址；通常與 Local IP 相同。",
    )

    pjsip_local_sip_port_base = models.PositiveIntegerField(
        default=64882,
        validators=[
            MinValueValidator(1024),
            MaxValueValidator(65535),
        ],
        verbose_name="SIP Port Base",
    )

    pjsip_local_rtp_port_base = models.PositiveIntegerField(
        default=4004,
        validators=[
            MinValueValidator(1024),
            MaxValueValidator(65535),
        ],
        verbose_name="RTP Port Base",
    )

    pjsip_port_step = models.PositiveSmallIntegerField(
        default=2,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(100),
        ],
        verbose_name="Port Step",
    )

    pjsip_audio_gain_percent = models.PositiveSmallIntegerField(
        default=100,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(200),
        ],
        verbose_name="Audio Gain (%)",
        help_text="PJSIP 播放音量增益百分比；100 表示原始增益。",
    )

    last_diagnostic_status = models.CharField(
        max_length=20,
        blank=True,
        default="",
        editable=False,
        verbose_name="最後診斷狀態",
    )

    last_diagnostic_message = models.TextField(
        blank=True,
        default="",
        editable=False,
        verbose_name="最後診斷訊息",
    )

    last_diagnostic_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name="最後診斷時間",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="最後修改時間",
    )

    class Meta:
        verbose_name = "廣播工程設定"
        verbose_name_plural = "廣播工程設定"

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return obj

    def __str__(self):
        return "KRTC IP Speaker / PJSIP 廣播工程設定"


class UIConfiguration(models.Model):
    """通報主機前台介面設定。僅保留一筆，由 Superuser 管理。"""

    SINGLETON_PK = 1

    LOGIN_THEME_CHOICES = [
        ("dark", "Dark Mode"),
        ("bright", "Bright Mode"),
    ]

    id = models.PositiveSmallIntegerField(
        primary_key=True,
        default=SINGLETON_PK,
        editable=False,
    )

    login_theme = models.CharField(
        max_length=20,
        choices=LOGIN_THEME_CHOICES,
        default="dark",
        verbose_name="登入框主題",
        help_text="Dark Mode 為深色登入框；Bright Mode 為亮色半透明登入框。",
    )

    login_background_enabled = models.BooleanField(
        default=False,
        verbose_name="啟用登入背景圖片",
    )

    login_background = models.FileField(
        upload_to="ui/login/",
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["jpg", "jpeg", "png", "webp"]
            )
        ],
        verbose_name="登入背景圖片",
        help_text="支援 JPG、JPEG、PNG、WebP；建議 1920x1080 或更高解析度。",
    )

    login_overlay_opacity = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.78,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(1),
        ],
        verbose_name="背景遮罩透明度",
        help_text="0.00 為透明，1.00 為完全遮蔽；建議 0.65～0.85。",
    )

    login_title = models.CharField(
        max_length=100,
        default="通報主機操作員登入",
        verbose_name="登入頁標題",
    )

    login_subtitle = models.CharField(
        max_length=255,
        default="請使用授權帳號進入 Dashboard、Monitor Wall 與事件通報管理介面。",
        blank=True,
        verbose_name="登入頁副標題",
    )

    login_footer_text = models.CharField(
        max_length=255,
        default="KRTC AI CCTV Notification Host V6",
        blank=True,
        verbose_name="登入頁 Footer",
    )

    superuser_usb_required = models.BooleanField(
        default=False,
        verbose_name="Superuser USB 二次驗證",
    )

    superuser_usb_token_sha256 = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
        verbose_name="USB Token SHA-256",
    )

    superuser_usb_key_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        editable=False,
        verbose_name="USB Key ID",
    )

    superuser_usb_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name="USB 授權最後更新時間",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="最後修改時間",
    )

    class Meta:
        verbose_name = "前台介面設定"
        verbose_name_plural = "前台介面設定"

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return obj

    def __str__(self):
        return "KRTC AI CCTV 前台介面設定"
