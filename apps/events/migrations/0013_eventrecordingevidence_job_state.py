from django.db import migrations, models


def backfill_recording_job_fields(apps, schema_editor):
    """以既有事件資料補齊錄影工作的持久識別與事件時間。"""

    evidence_model = apps.get_model("events", "EventRecordingEvidence")
    for evidence in evidence_model.objects.select_related("event", "camera").iterator():
        event = evidence.event
        evidence.source_event_id = event.source_event_id or ""
        evidence.camera_code = (
            evidence.camera.camera_code if evidence.camera_id else event.camera_code or ""
        )
        evidence.event_time = event.detected_at
        evidence.save(
            update_fields=["source_event_id", "camera_code", "event_time"]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0012_alter_event_event_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventrecordingevidence",
            name="camera_code",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="eventrecordingevidence",
            name="download_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="eventrecordingevidence",
            name="downloaded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="eventrecordingevidence",
            name="event_time",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="eventrecordingevidence",
            name="file_size",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="eventrecordingevidence",
            name="last_polled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="eventrecordingevidence",
            name="next_poll_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="eventrecordingevidence",
            name="poll_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="eventrecordingevidence",
            name="retry_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="eventrecordingevidence",
            name="source_event_id",
            field=models.CharField(blank=True, db_index=True, max_length=150),
        ),
        migrations.AddField(
            model_name="eventrecordingevidence",
            name="warning_issued_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="eventrecordingevidence",
            name="export_status",
            field=models.CharField(
                choices=[
                    ("pending", "等待匯出"),
                    ("requested", "已取得匯出 ID"),
                    ("exporting", "匯出中"),
                    ("ready", "可下載"),
                    ("downloading", "下載中"),
                    ("completed", "已完成"),
                    ("failed", "失敗"),
                    ("expired", "已逾期"),
                    ("cancelled", "已取消"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
        migrations.RunPython(
            backfill_recording_job_fields,
            migrations.RunPython.noop,
        ),
    ]
