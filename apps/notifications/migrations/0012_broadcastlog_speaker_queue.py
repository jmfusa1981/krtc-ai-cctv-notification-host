from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0011_alter_broadcastrule_event_type"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="broadcastlog",
            name="uniq_active_broadcast_per_speaker",
        ),
        migrations.AddField(
            model_name="broadcastlog",
            name="dedup_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                max_length=64,
                verbose_name="Dedup Key",
            ),
        ),
        migrations.AddField(
            model_name="broadcastlog",
            name="expires_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="Queue Expires At",
            ),
        ),
        migrations.AddField(
            model_name="broadcastlog",
            name="queue_priority",
            field=models.PositiveIntegerField(
                db_index=True,
                default=100,
                help_text="數字越小，Speaker queue 中的執行優先權越高。",
                verbose_name="Queue Priority",
            ),
        ),
        migrations.AlterField(
            model_name="broadcastlog",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("queued", "Queued"),
                    ("playing", "Playing"),
                    ("success", "Success"),
                    ("failed", "Failed"),
                    ("skipped", "Skipped"),
                    ("suppressed", "Suppressed"),
                    ("expired", "Expired"),
                    ("cancelled", "Cancelled"),
                ],
                default="queued",
                max_length=20,
                verbose_name="Status",
            ),
        ),
        migrations.AddConstraint(
            model_name="broadcastlog",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("speaker__isnull", False),
                    ("status", "playing"),
                ),
                fields=("speaker",),
                name="uniq_playing_broadcast_per_speaker",
            ),
        ),
    ]
