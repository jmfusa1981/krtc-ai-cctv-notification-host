from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
from zoneinfo import ZoneInfo


def backfill_daily_numbers(apps, schema_editor):
    Event = apps.get_model('events', 'Event')
    EventDailyCounter = apps.get_model('events', 'EventDailyCounter')
    tz = ZoneInfo(getattr(settings, 'TIME_ZONE', 'Asia/Taipei'))

    sequences = {}
    events = Event.objects.all().order_by('detected_at', 'id')
    for event in events.iterator(chunk_size=500):
        detected = event.detected_at
        if detected.tzinfo is None:
            detected = detected.replace(tzinfo=tz)
        local_date = detected.astimezone(tz).date()
        seq = sequences.get(local_date, 0) + 1
        sequences[local_date] = seq
        Event.objects.filter(pk=event.pk).update(
            record_date=local_date,
            record_sequence=seq,
        )

    EventDailyCounter.objects.bulk_create(
        [
            EventDailyCounter(event_date=event_date, last_sequence=seq)
            for event_date, seq in sequences.items()
        ],
        ignore_conflicts=True,
    )


def reverse_backfill(apps, schema_editor):
    Event = apps.get_model('events', 'Event')
    Event.objects.all().update(record_date=None, record_sequence=None)


class Migration(migrations.Migration):
    dependencies = [
        ('events', '0009_event_identity_timestamp'),
    ]

    operations = [
        migrations.CreateModel(
            name='EventDailyCounter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_date', models.DateField(db_index=True, unique=True)),
                ('last_sequence', models.PositiveIntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Event daily counter',
                'verbose_name_plural': 'Event daily counters',
                'ordering': ['-event_date'],
            },
        ),
        migrations.AddField(
            model_name='event',
            name='record_date',
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name='事件紀錄日期'),
        ),
        migrations.AddField(
            model_name='event',
            name='record_sequence',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='當日事件流水號'),
        ),
        migrations.RunPython(backfill_daily_numbers, reverse_backfill),
        migrations.AddConstraint(
            model_name='event',
            constraint=models.UniqueConstraint(
                fields=('record_date', 'record_sequence'),
                condition=Q(record_date__isnull=False, record_sequence__isnull=False),
                name='unique_event_record_date_sequence',
            ),
        ),
    ]
