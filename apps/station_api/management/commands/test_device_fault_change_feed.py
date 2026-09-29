from django.core.management.base import BaseCommand
from django.test.utils import override_settings

from apps.station_api.device_faults import recover_device_fault, report_device_fault
from apps.station_api.models import DeviceFaultChange, DeviceFaultLog


class Command(BaseCommand):
    help = "Self-test DeviceFaultLog -> DeviceFaultChange lifecycle."

    def handle(self, *args, **options):
        host_code = "PAO-CHANGE-FEED-SELFTEST"
        fault_code = "CHANGE_FEED_SELF_TEST"
        DeviceFaultLog.objects.filter(
            device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
            device_code=host_code,
            fault_code=fault_code,
        ).delete()
        try:
            with override_settings(KRTC_NOTIFICATION_HOST_CODE=host_code):
                fault, created = report_device_fault(
                    device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
                    device_code=host_code,
                    device_name="Change Feed Self Test",
                    area="PAO",
                    fault_code=fault_code,
                    fault_description="First simulated failure.",
                    severity=DeviceFaultLog.SEVERITY_INFO,
                )
                if not created:
                    raise RuntimeError("Expected first fault to be created.")
                changes = list(DeviceFaultChange.objects.filter(source_fault=fault).order_by("id"))
                if len(changes) != 1 or changes[0].change_type != DeviceFaultChange.CHANGE_CREATED:
                    raise RuntimeError("Created change was not appended.")
                self.stdout.write(self.style.SUCCESS("PASS: created fault appends created change."))

                same_fault, created = report_device_fault(
                    device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
                    device_code=host_code,
                    device_name="Change Feed Self Test",
                    area="PAO",
                    fault_code=fault_code,
                    fault_description="Repeated simulated failure.",
                    severity=DeviceFaultLog.SEVERITY_INFO,
                )
                if created or same_fault.id != fault.id:
                    raise RuntimeError("Repeated fault should refresh the same row.")
                changes = list(DeviceFaultChange.objects.filter(source_fault=fault).order_by("id"))
                if len(changes) != 2 or changes[-1].change_type != DeviceFaultChange.CHANGE_REFRESHED:
                    raise RuntimeError("Refreshed change was not appended.")
                if changes[-1].occurrence_count != 2:
                    raise RuntimeError("Refreshed snapshot missing occurrence_count=2.")
                self.stdout.write(self.style.SUCCESS("PASS: repeated fault appends refreshed change."))

                recovered = recover_device_fault(
                    device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
                    device_code=host_code,
                    fault_code=fault_code,
                )
                if len(recovered) != 1:
                    raise RuntimeError("Expected one recovered fault.")
                changes = list(DeviceFaultChange.objects.filter(source_fault=fault).order_by("id"))
                if len(changes) != 3 or changes[-1].change_type != DeviceFaultChange.CHANGE_RECOVERED:
                    raise RuntimeError("Recovered change was not appended.")
                if changes[-1].status != DeviceFaultLog.STATUS_RECOVERED or not changes[-1].recovered_at:
                    raise RuntimeError("Recovered snapshot is incomplete.")
                self.stdout.write(self.style.SUCCESS("PASS: recovery appends recovered change."))

                ids = [item.id for item in changes]
                if ids != sorted(ids) or len(set(ids)) != 3:
                    raise RuntimeError("Change IDs are not unique monotonic cursor values.")
                self.stdout.write(self.style.SUCCESS("PASS: change IDs form an append-only cursor."))
            self.stdout.write(self.style.SUCCESS("Device Fault Change Feed self-test PASSED."))
        finally:
            DeviceFaultLog.objects.filter(
                device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
                device_code=host_code,
                fault_code=fault_code,
            ).delete()
