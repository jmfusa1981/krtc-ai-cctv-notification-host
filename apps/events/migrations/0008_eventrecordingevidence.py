from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("cameras", "0003_camera_nvr_fields"),
        ("events", "0007_v5_listener_event_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="EventRecordingEvidence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nvr_host", models.CharField(blank=True, db_index=True, max_length=100)),
                ("nvr_port", models.PositiveIntegerField(blank=True, null=True)),
                ("nvr_channel", models.IntegerField(blank=True, null=True)),
                ("video_format", models.CharField(default="MP4", max_length=10)),
                ("pre_event_seconds", models.PositiveIntegerField(default=30)),
                ("post_event_seconds", models.PositiveIntegerField(default=90)),
                ("evidence_start_at", models.DateTimeField()),
                ("evidence_end_at", models.DateTimeField()),
                ("export_id", models.CharField(blank=True, db_index=True, max_length=100)),
                ("export_status", models.CharField(choices=[("pending", "等待匯出"), ("requested", "已取得匯出 ID"), ("exporting", "匯出中"), ("completed", "已完成"), ("failed", "失敗")], db_index=True, default="pending", max_length=20)),
                ("export_rate", models.PositiveSmallIntegerField(default=0)),
                ("ffmpeg_status", models.IntegerField(blank=True, null=True)),
                ("file_name", models.CharField(blank=True, max_length=255)),
                ("file", models.FileField(blank=True, upload_to="event_recordings/")),
                ("download_url", models.URLField(blank=True, default="", max_length=1000)),
                ("request_payload", models.JSONField(blank=True, default=dict)),
                ("response_payload", models.JSONField(blank=True, default=dict)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("requested_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("camera", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="recording_evidences", to="cameras.camera", verbose_name="攝影機")),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recording_evidences", to="events.event", verbose_name="事件")),
            ],
            options={
                "verbose_name": "Event recording evidence",
                "verbose_name_plural": "Event recording evidences",
                "ordering": ["-created_at"],
            },
        ),
    ]
