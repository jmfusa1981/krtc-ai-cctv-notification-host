from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("ai_bridge", "0003_inferencehost_alter_aimodel_event_type_and_more")]
    operations = [
        migrations.CreateModel(
            name="ConfigurationAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("station_code", models.CharField(max_length=50)),
                ("notification_host_code", models.CharField(max_length=50)),
                ("inference_host_code", models.CharField(blank=True, max_length=50)),
                ("model_code", models.CharField(blank=True, max_length=100)),
                ("config_version", models.CharField(blank=True, max_length=80)),
                ("operator_code", models.CharField(blank=True, max_length=100)),
                ("source_address", models.GenericIPAddressField(blank=True, null=True)),
                ("status", models.CharField(choices=[("applied", "Applied"), ("rejected", "Rejected")], max_length=20)),
                ("reason", models.CharField(blank=True, max_length=255)),
                ("payload", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["-received_at"]},
        ),
        migrations.CreateModel(
            name="InferenceHostConfiguration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("config_version", models.CharField(max_length=80)),
                ("applied_at", models.DateTimeField(auto_now=True)),
                ("applied_by", models.CharField(blank=True, max_length=100)),
                ("inference_host", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="occ_configuration", to="ai_bridge.inferencehost")),
                ("selected_model", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="host_configurations", to="ai_bridge.aimodel")),
            ],
        ),
    ]
