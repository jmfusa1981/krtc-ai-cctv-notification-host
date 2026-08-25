from django.core.management.base import BaseCommand

from apps.station_api.device_faults import append_fault_change
from apps.station_api.models import DeviceFaultChange, DeviceFaultLog


class Command(BaseCommand):
    help = "Backfill one change-feed snapshot for existing DeviceFaultLog rows that have no changes."

    def handle(self, *args, **options):
        created = 0
        skipped_test = 0
        for fault in DeviceFaultLog.objects.order_by("id").iterator():
            code_upper = (fault.fault_code or "").upper()
            device_upper = (fault.device_code or "").upper()
            if "SELF_TEST" in code_upper or "SELFTEST" in code_upper or "SELFTEST" in device_upper:
                skipped_test += 1
                continue
            if DeviceFaultChange.objects.filter(source_fault=fault).exists():
                continue
            change_type = (
                DeviceFaultChange.CHANGE_RECOVERED
                if fault.status == DeviceFaultLog.STATUS_RECOVERED
                else DeviceFaultChange.CHANGE_CREATED
            )
            append_fault_change(fault, change_type)
            created += 1
        self.stdout.write(self.style.SUCCESS(
            f"DeviceFaultChange backfill complete: created={created}, skipped_test={skipped_test}."
        ))
