from django.core.management.base import BaseCommand, CommandError
from apps.notifications.models import SpeakerDevice
from apps.notifications.speaker_health import record_speaker_probe_result
from apps.station_api.models import DeviceFaultLog

class Command(BaseCommand):
    help = "Validate provisioning-aware Speaker System Log lifecycle without real hardware."
    def handle(self, *args, **options):
        code = "SYSLOG-SPK-SELFTEST"
        SpeakerDevice.objects.filter(speaker_code=code).delete()
        DeviceFaultLog.objects.filter(device_code=code).delete()
        speaker = SpeakerDevice.objects.create(speaker_code=code, name="Speaker Health Framework Self Test", ip_address="127.0.0.1", port=65526, username="selftest", is_active=True, deployment_state=SpeakerDevice.DEPLOYMENT_PLANNED, health_monitor_enabled=False)
        try:
            result = record_speaker_probe_result(speaker, False, "simulated unavailable")
            if result != "skipped" or DeviceFaultLog.objects.filter(device_code=code).exists():
                raise CommandError("Planned/unmonitored speaker created a fault.")
            self.stdout.write(self.style.SUCCESS("PASS: planned/unmonitored speaker creates no fault."))
            speaker.deployment_state = SpeakerDevice.DEPLOYMENT_DEPLOYED
            speaker.health_monitor_enabled = True
            speaker.save(update_fields=["deployment_state", "health_monitor_enabled", "updated_at"])
            record_speaker_probe_result(speaker, False, "simulated unavailable")
            fault = DeviceFaultLog.objects.filter(device_code=code, fault_code="SPEAKER_UNREACHABLE").first()
            if not fault or fault.status != DeviceFaultLog.STATUS_ACTIVE:
                raise CommandError("Deployed/monitored failure did not create active fault.")
            self.stdout.write(self.style.SUCCESS("PASS: deployed/monitored failure creates active fault."))
            record_speaker_probe_result(speaker, False, "simulated unavailable again")
            fault.refresh_from_db()
            if fault.occurrence_count != 2 or DeviceFaultLog.objects.filter(device_code=code, status=DeviceFaultLog.STATUS_ACTIVE).count() != 1:
                raise CommandError("Repeated Speaker failure lifecycle is incorrect.")
            self.stdout.write(self.style.SUCCESS("PASS: repeated failure refreshes one active fault."))
            record_speaker_probe_result(speaker, True, "simulated recovered")
            fault.refresh_from_db()
            if fault.status != DeviceFaultLog.STATUS_RECOVERED or fault.recovered_at is None:
                raise CommandError("Speaker recovery did not close the fault.")
            self.stdout.write(self.style.SUCCESS("PASS: successful probe recovers Speaker fault."))
            speaker.health_monitor_enabled = False
            speaker.save(update_fields=["health_monitor_enabled", "updated_at"])
            if record_speaker_probe_result(speaker, False, "ignored") != "skipped":
                raise CommandError("Monitoring OFF did not skip fault generation.")
            self.stdout.write(self.style.SUCCESS("PASS: monitoring OFF prevents new Speaker fault."))
        finally:
            SpeakerDevice.objects.filter(speaker_code=code).delete()
            DeviceFaultLog.objects.filter(device_code=code).delete()
        self.stdout.write(self.style.SUCCESS("Speaker Health Framework self-test PASSED."))
