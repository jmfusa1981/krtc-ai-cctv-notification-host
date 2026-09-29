from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("ai_bridge", "0006_inferencehost_configuration_url"),
        ("cameras", "0003_camera_nvr_fields"),
        ("events", "0010_daily_event_record_number"),
    ]

    operations = [
        migrations.CreateModel(
            name="ZoneCountState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_camera_id", models.CharField(max_length=100, verbose_name="來源 Camera ID")),
                ("station", models.CharField(blank=True, default="", max_length=100, verbose_name="站別")),
                ("roi_id", models.CharField(max_length=255, verbose_name="Zone 標籤")),
                ("count", models.PositiveIntegerField(default=0, verbose_name="目前人數")),
                ("threshold", models.PositiveIntegerField(blank=True, null=True, verbose_name="壅塞閾值")),
                ("source_updated_at", models.DateTimeField(blank=True, null=True, verbose_name="來源更新時間")),
                ("received_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="PAO 接收時間")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新時間")),
                ("camera", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="zone_count_states", to="cameras.camera", verbose_name="本站攝影機")),
                ("inference_host", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="zone_count_states", to="ai_bridge.inferencehost", verbose_name="推論主機")),
            ],
            options={
                "verbose_name": "Zone count state",
                "verbose_name_plural": "Zone count states",
                "ordering": ["inference_host__host_code", "source_camera_id", "roi_id"],
            },
        ),
        migrations.AddConstraint(
            model_name="zonecountstate",
            constraint=models.UniqueConstraint(fields=("inference_host", "source_camera_id", "roi_id"), name="uq_zone_count_host_camera_roi"),
        ),
        migrations.AddIndex(
            model_name="zonecountstate",
            index=models.Index(fields=["inference_host", "source_camera_id"], name="idx_zone_host_camera"),
        ),
        migrations.AddIndex(
            model_name="zonecountstate",
            index=models.Index(fields=["source_updated_at"], name="idx_zone_updated"),
        ),
    ]
