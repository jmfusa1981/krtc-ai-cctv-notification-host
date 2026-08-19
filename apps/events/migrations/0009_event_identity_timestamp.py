from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("events", "0008_eventrecordingevidence")]

    operations = [
        migrations.RemoveConstraint(
            model_name="event",
            name="unique_event_station_host_source_id",
        ),
        migrations.AddConstraint(
            model_name="event",
            constraint=models.UniqueConstraint(
                fields=(
                    "station_code",
                    "inference_host_code",
                    "source_event_id",
                    "detected_at",
                ),
                condition=(
                    ~Q(station_code="")
                    & ~Q(inference_host_code="")
                    & Q(source_event_id__isnull=False)
                ),
                name="unique_event_station_host_source_time",
            ),
        ),
    ]
