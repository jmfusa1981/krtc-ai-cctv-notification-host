from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cameras", "0002_camera_description_camera_status_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="camera",
            name="nvr_host",
            field=models.CharField(blank=True, help_text="NVR host IP used for event evidence export.", max_length=100),
        ),
        migrations.AddField(
            model_name="camera",
            name="nvr_port",
            field=models.PositiveIntegerField(blank=True, help_text="NVR web service port. Falls back to project settings when blank.", null=True),
        ),
        migrations.AddField(
            model_name="camera",
            name="nvr_username",
            field=models.CharField(blank=True, help_text="NVR software login account. Falls back to project settings when blank.", max_length=100),
        ),
        migrations.AddField(
            model_name="camera",
            name="nvr_password",
            field=models.CharField(blank=True, help_text="NVR software login password. Never show this value in frontend logs.", max_length=100),
        ),
        migrations.AddField(
            model_name="camera",
            name="nvr_channel",
            field=models.IntegerField(blank=True, help_text="NVR channel used by export.cgi for this camera.", null=True),
        ),
        migrations.AddField(
            model_name="camera",
            name="nvr_camera_uid",
            field=models.CharField(blank=True, help_text="Camera UID returned by the NVR camera list command.", max_length=100),
        ),
        migrations.AddField(
            model_name="camera",
            name="nvr_recording_enabled",
            field=models.BooleanField(default=True, help_text="Whether PAO may request NVR evidence clips for this camera."),
        ),
    ]
