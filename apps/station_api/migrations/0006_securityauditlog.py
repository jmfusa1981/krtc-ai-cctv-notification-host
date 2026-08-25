from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("station_api", "0005_devicefaultchange")]

    operations = [
        migrations.CreateModel(
            name="SecurityAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("occurred_at", models.DateTimeField(db_index=True)),
                ("username", models.CharField(blank=True, db_index=True, max_length=150)),
                ("display_name", models.CharField(blank=True, max_length=150)),
                ("role", models.CharField(blank=True, db_index=True, max_length=50)),
                ("action", models.CharField(db_index=True, max_length=80)),
                ("result", models.CharField(choices=[("success", "Success"), ("failed", "Failed"), ("info", "Info")], db_index=True, max_length=20)),
                ("auth_method", models.CharField(blank=True, max_length=50)),
                ("client_ip", models.GenericIPAddressField(blank=True, db_index=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=500)),
                ("detail", models.CharField(blank=True, max_length=500)),
                ("metadata", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["-occurred_at", "-id"]},
        ),
        migrations.AddIndex(model_name="securityauditlog", index=models.Index(fields=["action", "result"], name="st_audit_action_result_idx")),
        migrations.AddIndex(model_name="securityauditlog", index=models.Index(fields=["username", "occurred_at"], name="st_audit_user_time_idx")),
    ]
