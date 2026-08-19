from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_bridge", "0005_v5_listener_contract"),
    ]

    operations = [
        migrations.AddField(
            model_name="inferencehost",
            name="configuration_url",
            field=models.URLField(
                blank=True,
                default="",
                help_text="推論主機 Web 設定頁，例如：http://192.168.6.20:8080/",
                max_length=500,
                verbose_name="主機設定 URL",
            ),
        ),
    ]
