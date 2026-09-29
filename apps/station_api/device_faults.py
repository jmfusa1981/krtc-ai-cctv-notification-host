from django.db import transaction
from django.utils import timezone

from apps.settings_app.models import StationLocalSettings

from .fault_catalog import canonical_severity
from .models import DeviceFaultChange, DeviceFaultLog


def _station_identity():
    local = StationLocalSettings.load()
    return {
        "station_code": (local.station_code or "").strip(),
        "station_name": (local.station_name or "").strip(),
    }


def append_fault_change(fault, change_type):
    """Append an immutable snapshot of one DeviceFaultLog lifecycle change."""
    return DeviceFaultChange.objects.create(
        source_fault=fault,
        change_type=change_type,
        occurred_at=fault.occurred_at,
        last_seen_at=fault.last_seen_at,
        recovered_at=fault.recovered_at,
        station_code=fault.station_code,
        station_name=fault.station_name,
        device_type=fault.device_type,
        device_code=fault.device_code,
        device_name=fault.device_name,
        area=fault.area,
        fault_code=fault.fault_code,
        fault_description=fault.fault_description,
        severity=fault.severity,
        status=fault.status,
        occurrence_count=fault.occurrence_count,
    )


@transaction.atomic
def report_device_fault(
    *,
    device_type,
    device_code,
    device_name,
    fault_code,
    fault_description,
    area="",
    severity=DeviceFaultLog.SEVERITY_WARNING,
    occurred_at=None,
):
    now = occurred_at or timezone.now()
    identity = _station_identity()
    severity = canonical_severity(fault_code, severity)

    active = (
        DeviceFaultLog.objects.select_for_update()
        .filter(
            station_code=identity["station_code"],
            device_type=device_type,
            device_code=device_code,
            fault_code=fault_code,
            status=DeviceFaultLog.STATUS_ACTIVE,
        )
        .order_by("-id")
        .first()
    )

    if active:
        active.device_name = device_name
        active.area = area
        active.fault_description = fault_description
        active.severity = severity
        active.last_seen_at = now
        active.occurrence_count += 1
        active.save(
            update_fields=[
                "device_name",
                "area",
                "fault_description",
                "severity",
                "last_seen_at",
                "occurrence_count",
                "updated_at",
            ]
        )
        append_fault_change(active, DeviceFaultChange.CHANGE_REFRESHED)
        return active, False

    fault = DeviceFaultLog.objects.create(
        occurred_at=now,
        last_seen_at=now,
        station_code=identity["station_code"],
        station_name=identity["station_name"],
        device_type=device_type,
        device_code=device_code,
        device_name=device_name,
        area=area,
        fault_code=fault_code,
        fault_description=fault_description,
        severity=severity,
        status=DeviceFaultLog.STATUS_ACTIVE,
    )
    append_fault_change(fault, DeviceFaultChange.CHANGE_CREATED)
    return fault, True


@transaction.atomic
def recover_device_fault(
    *,
    device_type,
    device_code,
    fault_code="",
    recovered_at=None,
):
    now = recovered_at or timezone.now()
    identity = _station_identity()

    queryset = DeviceFaultLog.objects.select_for_update().filter(
        station_code=identity["station_code"],
        device_type=device_type,
        device_code=device_code,
        status=DeviceFaultLog.STATUS_ACTIVE,
    )

    if fault_code:
        queryset = queryset.filter(fault_code=fault_code)

    rows = list(queryset)
    for item in rows:
        item.status = DeviceFaultLog.STATUS_RECOVERED
        item.recovered_at = now
        item.last_seen_at = now
        item.save(
            update_fields=[
                "status",
                "recovered_at",
                "last_seen_at",
                "updated_at",
            ]
        )

        append_fault_change(item, DeviceFaultChange.CHANGE_RECOVERED)

    return rows
