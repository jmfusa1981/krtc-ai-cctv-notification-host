from django.http import JsonResponse
from .models import Camera


def camera_list_api(request):
    cameras = Camera.objects.all().order_by("id")

    data = []

    for camera in cameras:
        data.append({
            "id": camera.id,
            "name": camera.name,
            "area": camera.area,
            "created_at": camera.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })

    return JsonResponse(
        {
            "success": True,
            "count": len(data),
            "cameras": data,
        },
        json_dumps_params={"ensure_ascii": False},
    )