from django.db import models


class AIModel(models.Model):
    name = models.CharField(max_length=100)
    model_code = models.CharField(max_length=50, unique=True)
    version = models.CharField(max_length=50)
    event_type = models.CharField(max_length=50)
    api_url = models.URLField(blank=True)
    model_path = models.TextField(blank=True)
    confidence_threshold = models.FloatField(default=0.8)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["model_code"]

    def __str__(self):
        return f"{self.model_code} v{self.version}"