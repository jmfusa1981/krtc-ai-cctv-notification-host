import time

import cv2
from django.http import Http404, JsonResponse, StreamingHttpResponse

from .models import Camera


def camera_list_api(request):
    """
    Camera list API.

    URL:
    GET /api/cameras/

    Security note:
    This API does not expose the raw RTSP URL because it may contain
    the IP camera username and password.
    """

    cameras = Camera.objects.all().order_by("camera_code")

    data = []

    for camera in cameras:
        data.append({
            "id": camera.id,
            "name": camera.name,
            "camera_code": camera.camera_code,
            "area": camera.area,
            "has_stream": bool(camera.rtsp_url),
            "stream_url": f"/api/cameras/{camera.id}/stream/",
            "status": camera.status,
            "is_active": camera.is_active,
            "is_online": camera.is_online,
            "description": camera.description,
            "last_checked_at": camera.last_checked_at.strftime("%Y-%m-%d %H:%M:%S") if camera.last_checked_at else None,
            "created_at": camera.created_at.strftime("%Y-%m-%d %H:%M:%S") if camera.created_at else None,
        })

    return JsonResponse(
        {
            "success": True,
            "count": len(data),
            "cameras": data,
        },
        json_dumps_params={"ensure_ascii": False},
    )


def generate_mjpeg_frames(camera):
    """
    Read RTSP stream from an IP camera and yield MJPEG frames.

    Step 11 PoC:
    - OpenCV reads camera.rtsp_url
    - Each frame is encoded as JPEG
    - Django streams frames as multipart MJPEG
    """

    rtsp_url = camera.rtsp_url

    if not rtsp_url:
        return

    cap = cv2.VideoCapture(rtsp_url)

    if not cap.isOpened():
        cap.release()
        return

    try:
        while True:
            success, frame = cap.read()

            if not success:
                time.sleep(0.1)
                continue

            encode_success, buffer = cv2.imencode(".jpg", frame)

            if not encode_success:
                continue

            frame_bytes = buffer.tobytes()

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                frame_bytes +
                b"\r\n"
            )

    finally:
        cap.release()


def camera_mjpeg_stream(request, camera_id):
    """
    MJPEG stream endpoint.

    URL:
    GET /api/cameras/<camera_id>/stream/

    Example:
    http://127.0.0.1:8000/api/cameras/1/stream/
    """

    try:
        camera = Camera.objects.get(id=camera_id, is_active=True)
    except Camera.DoesNotExist:
        raise Http404("Camera not found or inactive.")

    if not camera.rtsp_url:
        return JsonResponse(
            {
                "success": False,
                "message": "This camera does not have an RTSP URL.",
            },
            status=400,
            json_dumps_params={"ensure_ascii": False},
        )

    response = StreamingHttpResponse(
        generate_mjpeg_frames(camera),
        content_type="multipart/x-mixed-replace; boundary=frame",
    )

    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"

    return response