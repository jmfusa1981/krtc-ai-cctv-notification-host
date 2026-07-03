from django.db import models


class Camera(models.Model):
    STATUS_CHOICES = [
        ("online", "Online"),
        ("offline", "Offline"),
        ("maintenance", "Maintenance"),
        ("error", "Error"),
    ]

    name = models.CharField(max_length=100)
    camera_code = models.CharField(max_length=50, unique=True)
    area = models.CharField(max_length=100)

    rtsp_url = models.TextField(
        blank=True,
        help_text="RTSP / MJPEG / HLS stream URL for this camera.",
    )

    username = models.CharField(
        max_length=100,
        blank=True,
        help_text="Camera login username, if required.",
    )

    password = models.CharField(
        max_length=100,
        blank=True,
        help_text="Camera login password, if required.",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="offline",
        help_text="Current camera connection status.",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Whether this camera should be displayed on the monitoring dashboard.",
    )

    is_online = models.BooleanField(
        default=False,
        help_text="Legacy/simple online flag. Can be synchronized with status later.",
    )

    description = models.TextField(
        blank=True,
        help_text="Camera description or installation notes.",
    )

    last_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["camera_code"]

    def __str__(self):
        return f"{self.camera_code} - {self.name}"