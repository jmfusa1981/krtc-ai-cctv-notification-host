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
