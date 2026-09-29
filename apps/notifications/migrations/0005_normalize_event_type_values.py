from django.db import migrations


FORWARD_EVENT_TYPE_MAP = {
    "fall_down": "escalator_fall",
    "luggage_rolling": "luggage_roll",
    "large_luggage_area": "large_luggage_intrusion",
    "wheelchair": "wheelchair_detected",
    "overstayed": "passenger_loitering",
    "crowd_flow_abnormal": "crowd_count_abnormal",
}

def normalize_event_type_values(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    BroadcastRule = apps.get_model("notifications", "BroadcastRule")

    for old_value, new_value in FORWARD_EVENT_TYPE_MAP.items():
        Event.objects.filter(event_type=old_value).update(event_type=new_value)
        BroadcastRule.objects.filter(event_type=old_value).update(
            event_type=new_value
        )
class Migration(migrations.Migration):
    dependencies = [
        ("events", "0003_alter_event_options_event_updated_at_and_more"),
        ("notifications", "0004_alter_broadcastrule_event_type"),
    ]

    operations = [
        migrations.RunPython(
            normalize_event_type_values,
            migrations.RunPython.noop,
        ),
    ]