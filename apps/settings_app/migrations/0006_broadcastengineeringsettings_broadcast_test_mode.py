from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("settings_app", "0005_broadcastengineeringsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="broadcastengineeringsettings",
            name="broadcast_test_mode",
            field=models.BooleanField(
                blank=True,
                default=None,
                help_text=(
                    "未初始化時使用環境安全預設；儲存後由本設定決定正式 "
                    "PJSIP 或 Simulation 測試模式。"
                ),
                null=True,
                verbose_name="廣播運行模式",
            ),
        ),
    ]
