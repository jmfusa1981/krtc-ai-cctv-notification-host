from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0004_event_severity_event_snapshot_url_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="LocalAlarmPolicy",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "singleton_key",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        unique=True,
                    ),
                ),
                (
                    "enabled_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now,
                        verbose_name="本機警報啟用時間",
                    ),
                ),
                (
                    "is_enabled",
                    models.BooleanField(
                        default=True,
                        verbose_name="啟用本機警報",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Local alarm policy",
                "verbose_name_plural": "Local alarm policies",
            },
        ),
    ]
