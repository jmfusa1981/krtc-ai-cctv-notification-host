from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("notifications", "0006_speaker_network_codec_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="BroadcastSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, verbose_name="Schedule Name")),
                ("schedule_type", models.CharField(choices=[("once", "單次"), ("daily", "每日")], default="once", max_length=10, verbose_name="Schedule Type")),
                ("run_at", models.DateTimeField(blank=True, help_text="單次排程使用。", null=True, verbose_name="One-time Run At")),
                ("daily_time", models.TimeField(blank=True, help_text="每日排程使用。", null=True, verbose_name="Daily Time")),
                ("next_run_at", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Next Run At")),
                ("last_run_at", models.DateTimeField(blank=True, null=True, verbose_name="Last Run At")),
                ("is_active", models.BooleanField(default=True, verbose_name="Is Active")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created At")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated At")),
                ("audio_file", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="broadcast_schedules", to="notifications.audiofile", verbose_name="Audio File")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_broadcast_schedules", to=settings.AUTH_USER_MODEL, verbose_name="Created By")),
                ("speakers", models.ManyToManyField(related_name="broadcast_schedules", to="notifications.speakerdevice", verbose_name="Speaker Devices")),
            ],
            options={"verbose_name": "Broadcast Schedule", "verbose_name_plural": "Broadcast Schedules", "ordering": ["next_run_at", "name"]},
        ),
    ]
