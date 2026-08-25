FAULT_CATALOG_VERSION = "1.0"
SYSTEM_LOG_SCHEMA_VERSION = "1.1"

FAULT_CATALOG = {
    "CAMERA_RTSP_NOT_CONFIGURED": {"device_type": "camera", "severity": "warning", "title": "Camera RTSP not configured"},
    "CAMERA_RTSP_UNAVAILABLE": {"device_type": "camera", "severity": "warning", "title": "Camera RTSP unavailable"},
    "INFERENCE_HEALTH_UNAVAILABLE": {"device_type": "inference_host", "severity": "critical", "title": "Inference host health endpoint unavailable"},
    "INFERENCE_HEALTH_BAD_STATUS": {"device_type": "inference_host", "severity": "critical", "title": "Inference host health status abnormal"},
    "SPEAKER_UNREACHABLE": {"device_type": "speaker", "severity": "warning", "title": "IP speaker unreachable"},
    "OCC_SYNC_UNAVAILABLE": {"device_type": "occ_network", "severity": "warning", "title": "PAO to OCC synchronization unavailable"},
    "PAO_INFERENCE_POLLING_STOPPED": {"device_type": "notification_host", "severity": "critical", "title": "PAO inference polling service stopped"},
    "PAO_BROADCAST_SCHEDULER_UNHEALTHY": {"device_type": "notification_host", "severity": "warning", "title": "PAO broadcast scheduler unhealthy"},
}


def canonical_severity(fault_code, requested_severity):
    item = FAULT_CATALOG.get(str(fault_code or "").strip())
    return item["severity"] if item else requested_severity
