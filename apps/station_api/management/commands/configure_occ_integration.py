from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ai_bridge.models import InferenceHost
from apps.settings_app.models import StationLocalSettings


class Command(BaseCommand):
    help = "Configure PAO station identity and physical inference host for OCC Heartbeat P0."

    def handle(self, *args, **options):
        local = StationLocalSettings.load()
        local.station_code = "KRTC-ST-001"
        local.station_name = "KRTC-ST-001"
        local.notification_host_name = "NH-KRTC-ST-001"
        local.maintenance_host_url = settings.KRTC_MAINTENANCE_API_BASE_URL
        local.system_version = settings.KRTC_APP_VERSION
        local.save(
            update_fields=[
                "station_code",
                "station_name",
                "notification_host_name",
                "maintenance_host_url",
                "system_version",
                "updated_at",
            ]
        )

        base_url = "http://192.168.6.20:8000"
        formal_code = "INF-KRTC-ST-001-01"
        base_url_host = InferenceHost.objects.filter(base_url=base_url).first()
        code_host = InferenceHost.objects.filter(host_code=formal_code).first()
        host = base_url_host or code_host
        created = host is None
        if created:
            host = InferenceHost(host_code=formal_code)
        else:
            if code_host and code_host.pk != host.pk:
                code_host.host_code = f"DISABLED-{code_host.pk}-{code_host.host_code}"[:50]
                code_host.is_active = False
                code_host.save(update_fields=["host_code", "is_active", "updated_at"])
            host.host_code = formal_code

        host.name = "KMetro Physical Inference Host 01"
        host.station_code = "KRTC-ST-001"
        host.host_type = "physical"
        host.ip_address = "192.168.6.20"
        host.port = 8000
        host.base_url = base_url
        host.health_url = f"{base_url}/health"
        host.events_url = f"{base_url}/api/notify/events"
        host.websocket_url = "ws://192.168.6.20:8000/ws/alerts"
        host.websocket_auth_mode = "none"
        if not host.application_version:
            host.application_version = "1.2.0"
        host.is_active = True
        host.save()

        InferenceHost.objects.filter(base_url=base_url).exclude(pk=host.pk).update(is_active=False)

        action = "created" if created else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                "OCC integration configured: "
                "station=KRTC-ST-001, notification_host=NH-KRTC-ST-001, "
                f"inference_host={host.host_code} ({action})"
            )
        )
