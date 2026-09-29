from django.core.management.base import BaseCommand

from apps.ai_bridge.models import InferenceHost


class Command(BaseCommand):
    help = "Create or update the approved V5 physical inference host."

    def handle(self, *args, **options):
        defaults = {
                "name": "KRTC-ST-001 實體推論主機 01",
                "station_code": "KRTC-ST-001",
                "host_type": "physical",
                "ip_address": "192.168.6.20",
                "port": 8000,
                "base_url": "http://192.168.6.20:8000",
                "health_url": "http://192.168.6.20:8000/health",
                "events_url": "http://192.168.6.20:8000/api/notify/events",
                "websocket_url": "ws://192.168.6.20:8000/ws/alerts",
                "websocket_auth_mode": "none",
                "is_active": True,
            }
        host = (InferenceHost.objects.filter(host_code="INF-KRTC-ST-001-01").first()
                or InferenceHost.objects.filter(base_url="http://192.168.6.20:8000").first())
        created = host is None
        if created:
            host = InferenceHost(host_code="INF-KRTC-ST-001-01")
        else:
            host.host_code = "INF-KRTC-ST-001-01"
        for field, value in defaults.items():
            setattr(host, field, value)
        host.save()
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Updated'} {host.host_code}"))
