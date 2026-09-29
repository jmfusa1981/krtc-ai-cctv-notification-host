from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai_bridge", "0004_inferenceconnectionstate")]
    operations = [
        migrations.AddField("inferencehost", "station_code", models.CharField(db_index=True, default="KRTC-ST-001", max_length=50)),
        migrations.AddField("inferencehost", "host_type", models.CharField(default="physical", max_length=20)),
        migrations.AddField("inferencehost", "ip_address", models.GenericIPAddressField(blank=True, null=True)),
        migrations.AddField("inferencehost", "port", models.PositiveIntegerField(default=8000)),
        migrations.AddField("inferencehost", "health_url", models.URLField(blank=True, max_length=500)),
        migrations.AddField("inferencehost", "events_url", models.URLField(blank=True, max_length=500)),
        migrations.AddField("inferencehost", "websocket_url", models.CharField(blank=True, max_length=500)),
        migrations.AddField("inferencehost", "websocket_auth_mode", models.CharField(default="none", max_length=20)),
        migrations.AddField("inferencehost", "application_version", models.CharField(blank=True, max_length=50)),
        migrations.AddField("inferenceconnectionstate", "health_status", models.CharField(default="unknown", max_length=20)),
        migrations.AddField("inferenceconnectionstate", "websocket_status", models.CharField(default="disconnected", max_length=20)),
        migrations.AddField("inferenceconnectionstate", "last_message_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("inferenceconnectionstate", "last_successful_event_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("inferenceconnectionstate", "last_catchup_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("inferenceconnectionstate", "last_error", models.TextField(blank=True)),
    ]
