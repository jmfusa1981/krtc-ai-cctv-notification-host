from django.db import migrations, models
import django.db.models.deletion


def copy_legacy_speaker_to_speakers(apps, schema_editor):
    BroadcastRule = apps.get_model("notifications", "BroadcastRule")
    for rule in BroadcastRule.objects.exclude(speaker_id=None):
        rule.speakers.add(rule.speaker_id)


def copy_first_speaker_back_to_legacy(apps, schema_editor):
    BroadcastRule = apps.get_model("notifications", "BroadcastRule")
    for rule in BroadcastRule.objects.all():
        speaker_id = rule.speakers.values_list("id", flat=True).order_by("speaker_code").first()
        if speaker_id:
            rule.speaker_id = speaker_id
            rule.save(update_fields=["speaker"])


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0008_broadcastschedule_volume_percent"),
    ]

    operations = [
        migrations.AlterField(
            model_name="broadcastrule",
            name="speaker",
            field=models.ForeignKey(
                blank=True,
                help_text="舊版單一 Speaker 相容欄位。新規則請使用 Speaker Devices 多選欄位。",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="legacy_broadcast_rules",
                to="notifications.speakerdevice",
                verbose_name="Legacy Speaker Device",
            ),
        ),
        migrations.AddField(
            model_name="broadcastrule",
            name="speakers",
            field=models.ManyToManyField(
                blank=True,
                help_text="可多選。事件命中此 Rule 後，會對每一支 Speaker 建立個別廣播任務。",
                related_name="broadcast_rules",
                to="notifications.speakerdevice",
                verbose_name="Speaker Devices",
            ),
        ),
        migrations.RunPython(
            copy_legacy_speaker_to_speakers,
            copy_first_speaker_back_to_legacy,
        ),
    ]
