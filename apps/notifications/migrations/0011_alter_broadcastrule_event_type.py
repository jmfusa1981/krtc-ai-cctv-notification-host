from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0010_speakerdevice_deployment_state_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="broadcastrule",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("fall_detected", "人員跌倒"),
                    ("fire_detected", "火光偵測"),
                    ("smoke_detected", "煙霧偵測"),
                    ("dwell_alert", "旅客滯留"),
                    ("crowd_alert", "人潮聚集"),
                    ("luggage_roll_detected", "行李箱滾落（電扶梯功能）"),
                    ("large_luggage_detected", "大件行李（禁制區功能）"),
                    ("wheelchair_detected", "輪椅偵測（禁制區功能）"),
                ],
                max_length=50,
                verbose_name="AI事件類別",
            ),
        ),
    ]
