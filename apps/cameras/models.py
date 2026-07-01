from django.db import models


class Camera(models.Model):
    name = models.CharField(max_length=100)
    camera_code = models.CharField(max_length=50, unique=True)
    area = models.CharField(max_length=100)
    rtsp_url = models.TextField(blank=True)
    username = models.CharField(max_length=100, blank=True)
    password = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    is_online = models.BooleanField(default=False)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["camera_code"]

    def __str__(self):
        return f"{self.camera_code} - {self.name}"