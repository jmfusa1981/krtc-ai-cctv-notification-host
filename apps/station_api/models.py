from django.db import models


class InferenceHostConfiguration(models.Model):
    inference_host = models.OneToOneField(
        "ai_bridge.InferenceHost", on_delete=models.CASCADE, related_name="occ_configuration"
    )
    selected_model = models.ForeignKey(
        "ai_bridge.AIModel", on_delete=models.PROTECT, related_name="host_configurations"
    )
    config_version = models.CharField(max_length=80)
    applied_at = models.DateTimeField(auto_now=True)
    applied_by = models.CharField(max_length=100, blank=True)


class ConfigurationAuditLog(models.Model):
    STATUS_APPLIED = "applied"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [(STATUS_APPLIED, "Applied"), (STATUS_REJECTED, "Rejected")]

    received_at = models.DateTimeField(auto_now_add=True)
    station_code = models.CharField(max_length=50)
    notification_host_code = models.CharField(max_length=50)
    inference_host_code = models.CharField(max_length=50, blank=True)
    model_code = models.CharField(max_length=100, blank=True)
    config_version = models.CharField(max_length=80, blank=True)
    operator_code = models.CharField(max_length=100, blank=True)
    source_address = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    reason = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-received_at"]


class OccSyncState(models.Model):
    """Persistent cursor and health state for PAO to OCC synchronization."""

    singleton_key = models.CharField(max_length=20, unique=True, default="default")
    last_event_id = models.PositiveBigIntegerField(default=0)
    heartbeat_sequence = models.PositiveBigIntegerField(
        default=0,
        help_text="Next OCC Heartbeat 1.0 sequence number to send.",
    )
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    last_daily_sync_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)

    @classmethod
    def load(cls):
        value, _ = cls.objects.get_or_create(singleton_key="default")
        return value


class OccSyncLog(models.Model):
    KIND_CHOICES = [
        ("heartbeat", "Heartbeat"),
        ("events", "Events"),
        ("devices", "Devices"),
        ("daily", "Daily summary"),
    ]
    STATUS_CHOICES = [("success", "Success"), ("failed", "Failed"), ("skipped", "Skipped")]

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    endpoint = models.CharField(max_length=255, blank=True)
    item_count = models.PositiveIntegerField(default=0)
    http_status = models.PositiveIntegerField(null=True, blank=True)
    error = models.CharField(max_length=500, blank=True)
    response_summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]

class DeviceFaultLog(models.Model):
    """Structured PAO device fault lifecycle record for OCC synchronization."""

    DEVICE_CAMERA = "camera"
    DEVICE_INFERENCE_HOST = "inference_host"
    DEVICE_SPEAKER = "speaker"
    DEVICE_NOTIFICATION_HOST = "notification_host"
    DEVICE_OCC_NETWORK = "occ_network"
    DEVICE_OTHER = "other"

    DEVICE_TYPE_CHOICES = [
        (DEVICE_CAMERA, "Camera"),
        (DEVICE_INFERENCE_HOST, "Inference Host"),
        (DEVICE_SPEAKER, "IP Speaker"),
        (DEVICE_NOTIFICATION_HOST, "Notification Host"),
        (DEVICE_OCC_NETWORK, "OCC / Network"),
        (DEVICE_OTHER, "Other"),
    ]

    SEVERITY_INFO = "info"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_CHOICES = [
        (SEVERITY_INFO, "Info"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_CRITICAL, "Critical"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_RECOVERED = "recovered"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_RECOVERED, "Recovered"),
    ]

    occurred_at = models.DateTimeField(db_index=True)
    last_seen_at = models.DateTimeField(db_index=True)
    recovered_at = models.DateTimeField(null=True, blank=True, db_index=True)

    station_code = models.CharField(max_length=50, db_index=True)
    station_name = models.CharField(max_length=100, blank=True)

    device_type = models.CharField(
        max_length=30,
        choices=DEVICE_TYPE_CHOICES,
        db_index=True,
    )
    device_code = models.CharField(max_length=100, db_index=True)
    device_name = models.CharField(max_length=150)
    area = models.CharField(max_length=150, blank=True)

    fault_code = models.CharField(max_length=100, db_index=True)
    fault_description = models.CharField(max_length=500)

    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default=SEVERITY_WARNING,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True,
    )

    occurrence_count = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(
                fields=["station_code", "status", "device_type"],
                name="st_fault_station_status_idx",
            ),
            models.Index(
                fields=["device_code", "fault_code", "status"],
                name="st_fault_device_code_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.station_code} {self.device_code} "
            f"{self.fault_code} ({self.status})"
        )


class DeviceFaultChange(models.Model):
    """Append-only snapshot feed used by OCC incremental System Log synchronization."""

    CHANGE_CREATED = "created"
    CHANGE_REFRESHED = "refreshed"
    CHANGE_RECOVERED = "recovered"
    CHANGE_TYPE_CHOICES = [
        (CHANGE_CREATED, "Created"),
        (CHANGE_REFRESHED, "Refreshed"),
        (CHANGE_RECOVERED, "Recovered"),
    ]

    source_fault = models.ForeignKey(
        DeviceFaultLog,
        on_delete=models.CASCADE,
        related_name="changes",
    )
    change_type = models.CharField(max_length=20, choices=CHANGE_TYPE_CHOICES, db_index=True)
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    occurred_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    recovered_at = models.DateTimeField(null=True, blank=True)
    station_code = models.CharField(max_length=50, db_index=True)
    station_name = models.CharField(max_length=100, blank=True)
    device_type = models.CharField(max_length=30, db_index=True)
    device_code = models.CharField(max_length=100, db_index=True)
    device_name = models.CharField(max_length=150)
    area = models.CharField(max_length=150, blank=True)
    fault_code = models.CharField(max_length=100, db_index=True)
    fault_description = models.CharField(max_length=500)
    severity = models.CharField(max_length=20, db_index=True)
    status = models.CharField(max_length=20, db_index=True)
    occurrence_count = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["station_code", "device_type", "change_type"], name="st_faultchg_station_type_idx"),
            models.Index(fields=["source_fault", "change_type"], name="st_faultchg_source_type_idx"),
        ]

    def __str__(self):
        return f"change={self.id} fault={self.source_fault_id} {self.fault_code} ({self.change_type})"


class SecurityAuditLog(models.Model):
    """Append-only human/security audit trail for PAO local review and OCC pull."""

    RESULT_SUCCESS = "success"
    RESULT_FAILED = "failed"
    RESULT_INFO = "info"
    RESULT_CHOICES = [
        (RESULT_SUCCESS, "Success"),
        (RESULT_FAILED, "Failed"),
        (RESULT_INFO, "Info"),
    ]

    occurred_at = models.DateTimeField(db_index=True)
    username = models.CharField(max_length=150, blank=True, db_index=True)
    display_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=50, blank=True, db_index=True)
    action = models.CharField(max_length=80, db_index=True)
    result = models.CharField(max_length=20, choices=RESULT_CHOICES, db_index=True)
    auth_method = models.CharField(max_length=50, blank=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=500, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["action", "result"], name="st_audit_action_result_idx"),
            models.Index(fields=["username", "occurred_at"], name="st_audit_user_time_idx"),
        ]

    def __str__(self):
        return f"{self.occurred_at} {self.username or '-'} {self.action} {self.result}"
