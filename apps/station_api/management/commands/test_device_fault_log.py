from django.core.management.base import BaseCommand

from apps.station_api.device_faults import recover_device_fault, report_device_fault
from apps.station_api.models import DeviceFaultLog


class Command(BaseCommand):
    help = "Create and recover one demonstration DeviceFaultLog row."

    def handle(self, *args, **options):
        fault, created = report_device_fault(
            device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
            device_code="PAO-SELF-TEST",
            device_name="PAO Device Fault Log Self Test",
            area="PAO",
            fault_code="SELF_TEST",
            fault_description="Device fault log self-test.",
            severity=DeviceFaultLog.SEVERITY_INFO,
        )

        self.stdout.write(
            f"Fault ID {fault.id}: {'created' if created else 'refreshed'}"
        )

        recovered = recover_device_fault(
            device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
            device_code="PAO-SELF-TEST",
            fault_code="SELF_TEST",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Recovered {len(recovered)} self-test fault row(s)."
            )
        )
