import time

import cv2
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.utils import timezone

from .models import Camera


def camera_list_api(request):
    """
    Camera list API.

    URL:
    GET /api/cameras/

    Security note:
    This API does not expose raw RTSP URLs, usernames, or passwords.
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
            "check_url": f"/api/cameras/{camera.id}/check/",
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


def camera_stream_check(request, camera_id):
    """
    Camera stream health check API.

    URL:
    GET /api/cameras/<camera_id>/check/

    Purpose:
    - Try to open the camera RTSP stream with OpenCV
    - Try to read one frame
    - Update camera.status, camera.is_online, and camera.last_checked_at
    """

    try:
        camera = Camera.objects.get(id=camera_id)
    except Camera.DoesNotExist:
        raise Http404("Camera not found.")

    if not camera.is_active:
        camera.status = "offline"
        camera.is_online = False
        camera.last_checked_at = timezone.now()
        camera.save(update_fields=["status", "is_online", "last_checked_at"])

        return JsonResponse(
            {
                "success": False,
                "camera_id": camera.id,
                "camera_code": camera.camera_code,
                "is_online": camera.is_online,
                "status": camera.status,
                "message": "Camera is inactive.",
            },
            status=400,
            json_dumps_params={"ensure_ascii": False},
        )

    if not camera.rtsp_url:
        camera.status = "error"
        camera.is_online = False
        camera.last_checked_at = timezone.now()
        camera.save(update_fields=["status", "is_online", "last_checked_at"])

        return JsonResponse(
            {
                "success": False,
                "camera_id": camera.id,
                "camera_code": camera.camera_code,
                "is_online": camera.is_online,
                "status": camera.status,
                "message": "Camera does not have an RTSP URL.",
            },
            status=400,
            json_dumps_params={"ensure_ascii": False},
        )

    cap = cv2.VideoCapture(camera.rtsp_url)

    # These properties are best-effort. Some OpenCV builds/camera drivers may ignore them.
    try:
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
    except Exception:
        pass

    is_opened = cap.isOpened()
    frame_read_success = False

    if is_opened:
        frame_read_success, _ = cap.read()

    cap.release()

    if is_opened and frame_read_success:
        camera.status = "online"
        camera.is_online = True
        camera.last_checked_at = timezone.now()
        camera.save(update_fields=["status", "is_online", "last_checked_at"])

        return JsonResponse(
            {
                "success": True,
                "camera_id": camera.id,
                "camera_code": camera.camera_code,
                "is_online": camera.is_online,
                "status": camera.status,
                "message": "Camera stream is available.",
                "stream_url": f"/api/cameras/{camera.id}/stream/",
            },
            json_dumps_params={"ensure_ascii": False},
        )

    camera.status = "error"
    camera.is_online = False
    camera.last_checked_at = timezone.now()
    camera.save(update_fields=["status", "is_online", "last_checked_at"])

    return JsonResponse(
        {
            "success": False,
            "camera_id": camera.id,
            "camera_code": camera.camera_code,
            "is_online": camera.is_online,
            "status": camera.status,
            "message": "Unable to open RTSP stream or read frame.",
        },
        status=503,
        json_dumps_params={"ensure_ascii": False},
    )