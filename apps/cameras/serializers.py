from rest_framework import serializers

from .mediamtx import get_camera_browser_playback
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


def serialize_browser_playback(camera):
    """將 Camera 轉成所有瀏覽器畫面共用的安全播放 metadata。"""

    playback = get_camera_browser_playback(camera)
    return {
        "available": playback.available,
        "kind": "mediamtx_webrtc" if playback.available else None,
        "path": playback.path_name if playback.available else None,
        "url": playback.player_url if playback.available else None,
        "whep_url": playback.whep_url if playback.available else None,
        "reason": playback.reason,
    }
