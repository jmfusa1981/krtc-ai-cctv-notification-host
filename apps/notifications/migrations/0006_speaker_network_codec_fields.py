from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("notifications", "0005_normalize_event_type_values")]

    operations = [
        migrations.AlterField(
            model_name="speakerdevice",
            name="port",
            field=models.PositiveIntegerField(default=5060, verbose_name="SIP Port"),
        ),
        migrations.AddField(
            model_name="speakerdevice",
            name="network_mode",
            field=models.CharField(
                choices=[("static", "固定 IP"), ("dhcp", "DHCP")],
                default="static",
                help_text="記錄設備採固定 IP 或 DHCP；不會遠端改寫設備網路設定。",
                max_length=10,
                verbose_name="Network Mode",
            ),
        ),
        migrations.AddField(
            model_name="speakerdevice",
            name="preferred_codec",
            field=models.CharField(
                choices=[
                    ("PCMU/8000", "G.711 μ-law (PCMU)"),
                    ("PCMA/8000", "G.711 A-law (PCMA)"),
                    ("G726-32/8000", "G.726 32 kbps"),
                ],
                default="PCMU/8000",
                max_length=30,
                verbose_name="Preferred Codec",
            ),
        ),
    ]
