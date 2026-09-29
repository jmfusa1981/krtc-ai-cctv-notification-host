from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="StationLocalSettings",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("station_code", models.CharField(default="DEMO", max_length=30, verbose_name="車站代碼")),
                ("station_name", models.CharField(default="KRTC Demo Station", max_length=100, verbose_name="車站名稱")),
                ("notification_host_name", models.CharField(default="KRTC Demo Station 通報主機", max_length=100, verbose_name="通報主機名稱")),
                ("system_version", models.CharField(default="V3", max_length=50, verbose_name="系統版本")),
                ("default_monitor_grid", models.PositiveSmallIntegerField(choices=[(1, "1 畫面"), (4, "4 畫面"), (9, "9 畫面"), (16, "16 畫面")], default=4, verbose_name="監視牆預設格數")),
                ("carousel_interval_seconds", models.PositiveIntegerField(default=10, validators=[django.core.validators.MinValueValidator(3), django.core.validators.MaxValueValidator(300)], verbose_name="輪播間隔秒數")),
                ("dashboard_refresh_seconds", models.PositiveIntegerField(default=5, validators=[django.core.validators.MinValueValidator(2), django.core.validators.MaxValueValidator(120)], verbose_name="Dashboard 更新秒數")),
                ("notification_sound_enabled", models.BooleanField(default=True, verbose_name="事件提示音")),
                ("warning_light_enabled", models.BooleanField(default=True, verbose_name="警示燈")),
                ("auto_broadcast_enabled", models.BooleanField(default=True, verbose_name="自動廣播")),
                ("maintenance_host_url", models.URLField(blank=True, max_length=500, verbose_name="中央維護主機 URL")),
                ("config_version", models.PositiveIntegerField(default=1, verbose_name="設定版本")),
                ("last_synced_at", models.DateTimeField(blank=True, null=True, verbose_name="最後中央同步時間")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="最後修改時間")),
            ],
            options={"verbose_name": "單站本機設定", "verbose_name_plural": "單站本機設定"},
        )
    ]
