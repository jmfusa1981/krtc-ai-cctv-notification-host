from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("station_api", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="OccSyncState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_key", models.CharField(default="default", max_length=20, unique=True)),
                ("last_event_id", models.PositiveBigIntegerField(default=0)),
                ("last_heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("last_daily_sync_at", models.DateTimeField(blank=True, null=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("consecutive_failures", models.PositiveIntegerField(default=0)),
                ("last_error", models.CharField(blank=True, max_length=500)),
            ],
        ),
        migrations.CreateModel(
            name="OccSyncLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("kind", models.CharField(choices=[("heartbeat", "Heartbeat"), ("events", "Events"), ("devices", "Devices"), ("daily", "Daily summary")], max_length=20)),
                ("status", models.CharField(choices=[("success", "Success"), ("failed", "Failed"), ("skipped", "Skipped")], max_length=20)),
                ("endpoint", models.CharField(blank=True, max_length=255)),
                ("item_count", models.PositiveIntegerField(default=0)),
                ("http_status", models.PositiveIntegerField(blank=True, null=True)),
                ("error", models.CharField(blank=True, max_length=500)),
                ("response_summary", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["-started_at"]},
        ),
    ]
