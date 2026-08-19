from rest_framework import serializers
from .models import Camera


class CameraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Camera
        fields = [
            "id",
            "name",
            "camera_code",
            "area",
            "rtsp_url",
            "username",
            "status",
            "is_active",
            "is_online",
            "description",
            "last_checked_at",
            "created_at",
        ]