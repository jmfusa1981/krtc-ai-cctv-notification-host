from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[("notifications","0007_broadcastschedule")]
    operations=[migrations.AddField(model_name="broadcastschedule",name="volume_percent",field=models.PositiveSmallIntegerField(default=100,verbose_name="Volume Percent"))]
