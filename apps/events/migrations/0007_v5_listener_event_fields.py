from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("events", "0006_eventupdatelog_and_contract_v1")]
    operations = [
        migrations.AlterField("event", "event_type", models.CharField(choices=[("escalator_fall", "電扶梯跌倒"), ("luggage_roll", "行李滾落"), ("large_luggage_intrusion", "大型行李進入限制區域"), ("wheelchair_detected", "輪椅偵測"), ("passenger_loitering", "旅客逗留過久"), ("crowd_count_abnormal", "人流數量異常"), ("fire_detected", "火災偵測"), ("smoke_detected", "煙霧偵測"), ("other", "其他")], default="other", max_length=50, verbose_name="事件類型")),
        migrations.AddField("event", "external_station_name", models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField("event", "roi_id", models.CharField(blank=True, max_length=100, null=True)),
        migrations.AddField("event", "bbox", models.JSONField(blank=True, null=True)),
        migrations.AddField("event", "ingestion_mode", models.CharField(default="websocket", max_length=20)),
        migrations.AddField("event", "occ_sync_status", models.CharField(db_index=True, default="pending", max_length=20)),
        migrations.AddField("event", "occ_sync_attempts", models.PositiveIntegerField(default=0)),
        migrations.AddField("event", "occ_last_error", models.CharField(blank=True, max_length=500)),
        migrations.AddField("event", "occ_last_attempt_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("event", "occ_synced_at", models.DateTimeField(blank=True, null=True)),
        migrations.RemoveConstraint("event", name="unique_event_inference_host_source_id"),
        migrations.AddConstraint("event", models.UniqueConstraint(condition=~Q(station_code="") & ~Q(inference_host_code="") & Q(source_event_id__isnull=False), fields=("station_code", "inference_host_code", "source_event_id"), name="unique_event_station_host_source_id")),
    ]
