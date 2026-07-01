from django.db import models


class Event(models.Model):
    EVENT_TYPES = [
        ("intrusion", "Intrusion"),
        ("fall", "Fall"),
        ("fight", "Fight"),
        ("fire", "Fire"),
        ("abnormal", "Abnormal Behavior"),
    ]

    STATUS_CHOICES = [
        ("new", "New"),
        ("reviewing", "Reviewing"),
        ("confirmed", "Confirmed"),
        ("false_alarm", "False Alarm"),
        ("notified", "Notified"),
        ("closed", "Closed"),
    ]

    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.CASCADE,
        related_name="events",
    )

    ai_model = models.ForeignKey(
        "ai_bridge.AIModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )

    event_type = models.CharField(
        max_length=50,
        choices=EVENT_TYPES,
    )

    confidence = models.FloatField(default=0.0)

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default="new",
    )

    snapshot = models.ImageField(
        upload_to="snapshots/",
        null=True,
        blank=True,
    )

    description = models.TextField(blank=True)

    detected_at = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-detected_at"]

    def __str__(self):
        return f"{self.event_type} - {self.camera.camera_code} - {self.status}"