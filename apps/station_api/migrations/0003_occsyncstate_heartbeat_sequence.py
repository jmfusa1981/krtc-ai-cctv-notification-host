from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("station_api", "0002_occsynclog_occsyncstate")]

    operations = [
        migrations.AddField(
            model_name="occsyncstate",
            name="heartbeat_sequence",
            field=models.PositiveBigIntegerField(
                default=0,
                help_text="Next OCC Heartbeat 1.0 sequence number to send.",
            ),
        ),
    ]
