from apps.station_api.device_faults import recover_device_fault, report_device_fault
from apps.station_api.models import DeviceFaultLog

SPEAKER_FAULT_CODE = "SPEAKER_UNREACHABLE"

def should_monitor_speaker(speaker):
    return bool(getattr(speaker, "health_monitor_active", False))

def clear_speaker_fault_if_monitoring_disabled(speaker):
    if should_monitor_speaker(speaker):
        return 0
    return recover_device_fault(
        device_type=DeviceFaultLog.DEVICE_SPEAKER,
        device_code=speaker.speaker_code,
        fault_code=SPEAKER_FAULT_CODE,
    )

def record_speaker_probe_result(speaker, ok, message=""):
    if not should_monitor_speaker(speaker):
        clear_speaker_fault_if_monitoring_disabled(speaker)
        return "skipped"
    if ok:
        recover_device_fault(
            device_type=DeviceFaultLog.DEVICE_SPEAKER,
            device_code=speaker.speaker_code,
            fault_code=SPEAKER_FAULT_CODE,
        )
        return "recovered"
    report_device_fault(
        device_type=DeviceFaultLog.DEVICE_SPEAKER,
        device_code=speaker.speaker_code,
        device_name=speaker.name,
        area=speaker.area or "",
        fault_code=SPEAKER_FAULT_CODE,
        fault_description=(message or "Speaker health probe failed.")[:500],
        severity=DeviceFaultLog.SEVERITY_WARNING,
    )
    return "active"
