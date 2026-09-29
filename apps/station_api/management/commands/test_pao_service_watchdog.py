from django.core.management.base import BaseCommand
from django.test.utils import override_settings

from apps.station_api.models import DeviceFaultLog
from apps.station_api.service_watchdog import _sync_service_fault


class Command(BaseCommand):
    help = "Self-test the PAO service watchdog DeviceFaultLog lifecycle."

    def handle(self, *args, **options):
        host_code = "PAO-WATCHDOG-SELFTEST"
        fault_code = "PAO_WATCHDOG_SELFTEST"

        DeviceFaultLog.objects.filter(
            device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
            device_code=host_code,
            fault_code=fault_code,
        ).delete()

        try:
            with override_settings(KRTC_NOTIFICATION_HOST_CODE=host_code):
                _sync_service_fault(
                    fault_code=fault_code,
                    healthy=False,
                    description="Simulated internal PAO service failure.",
                    severity=DeviceFaultLog.SEVERITY_WARNING,
                )
                row = DeviceFaultLog.objects.get(
                    device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
                    device_code=host_code,
                    fault_code=fault_code,
                )
                if row.status != DeviceFaultLog.STATUS_ACTIVE or row.occurrence_count != 1:
                    raise RuntimeError("First service failure did not create one active fault.")
                self.stdout.write(self.style.SUCCESS("PASS: first service failure creates active fault."))

                _sync_service_fault(
                    fault_code=fault_code,
                    healthy=False,
                    description="Simulated repeated internal PAO service failure.",
                    severity=DeviceFaultLog.SEVERITY_WARNING,
                )
                row.refresh_from_db()
                if row.occurrence_count != 2:
                    raise RuntimeError("Repeated service failure did not refresh the same fault.")
                self.stdout.write(self.style.SUCCESS("PASS: repeated failure refreshes one fault."))

                _sync_service_fault(
                    fault_code=fault_code,
                    healthy=True,
                    description="Service recovered.",
                )
                row.refresh_from_db()
                if row.status != DeviceFaultLog.STATUS_RECOVERED or row.recovered_at is None:
                    raise RuntimeError("Service recovery did not recover the active fault.")
                self.stdout.write(self.style.SUCCESS("PASS: service recovery marks fault recovered."))

            self.stdout.write(self.style.SUCCESS("PAO Service Watchdog self-test PASSED."))
        finally:
            DeviceFaultLog.objects.filter(
                device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
                device_code=host_code,
                fault_code=fault_code,
            ).delete()
