import time

import cv2
from django.contrib.auth.decorators import login_required
from apps.cameras.rtsp_utils import camera_rtsp_url
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.utils import timezone

from apps.station_api.device_faults import recover_device_fault, report_device_fault
from apps.station_api.models import DeviceFaultLog

from .models import Camera
from .stream_pool import acquire_camera_stream


@login_required
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


def generate_mjpeg_frames(camera, profile="wall"):
    """
    Yield MJPEG frames from a shared RTSP capture.

    The shared capture remains alive for 15 seconds after the last browser
    client disconnects, so a user who leaves and returns to the monitor wall
    within the grace period can resume without reopening the RTSP channel.
    """

    if not camera.rtsp_url:
        return

    profiles = {
        "single": {"fps": 15, "max_width": 1280, "jpeg_quality": 80},
        "grid4": {"fps": 12, "max_width": 960, "jpeg_quality": 78},
        "grid9": {"fps": 8, "max_width": 640, "jpeg_quality": 65},
        "grid16": {"fps": 6, "max_width": 480, "jpeg_quality": 60},
    }
    stream_profile = profiles.get(profile, profiles["grid4"])
    frame_interval = 1.0 / stream_profile["fps"]
    shared_stream = acquire_camera_stream(camera.id, camera_rtsp_url(camera))
    last_version = 0
    next_frame_at = time.monotonic()

    try:
        while True:
            last_version, frame = shared_stream.wait_for_frame(last_version, timeout=2.0)
            if frame is None:
                if shared_stream.stopped:
                    return
                continue

            now = time.monotonic()
            if now < next_frame_at:
                continue
            next_frame_at = now + frame_interval

            frame_height, frame_width = frame.shape[:2]
            max_width = stream_profile["max_width"]
            if frame_width > max_width:
                scale = max_width / float(frame_width)
                resized_height = max(1, int(frame_height * scale))
                frame = cv2.resize(
                    frame,
                    (max_width, resized_height),
                    interpolation=cv2.INTER_AREA,
                )

            encode_success, buffer = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, stream_profile["jpeg_quality"]],
            )
            if not encode_success:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + buffer.tobytes()
                + b"\r\n"
            )
    finally:
        shared_stream.unsubscribe()


@login_required
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

    profile = request.GET.get("profile", "grid4")
    if profile not in {"single", "grid4", "grid9", "grid16"}:
        profile = "grid4"

    response = StreamingHttpResponse(
        generate_mjpeg_frames(camera, profile=profile),
        content_type="multipart/x-mixed-replace; boundary=frame",
    )

    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"

    return response


@login_required
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

        try:
            report_device_fault(
                device_type=DeviceFaultLog.DEVICE_CAMERA,
                device_code=camera.camera_code,
                device_name=camera.name,
                area=camera.area or "",
                fault_code="CAMERA_RTSP_NOT_CONFIGURED",
                fault_description="Camera does not have an RTSP URL.",
                severity=DeviceFaultLog.SEVERITY_WARNING,
            )
        except Exception:
            pass

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

    cap = cv2.VideoCapture(camera_rtsp_url(camera))

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

        try:
            recover_device_fault(
                device_type=DeviceFaultLog.DEVICE_CAMERA,
                device_code=camera.camera_code,
                fault_code="CAMERA_RTSP_NOT_CONFIGURED",
            )
            recover_device_fault(
                device_type=DeviceFaultLog.DEVICE_CAMERA,
                device_code=camera.camera_code,
                fault_code="CAMERA_RTSP_UNAVAILABLE",
            )
        except Exception:
            pass

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

    try:
        report_device_fault(
            device_type=DeviceFaultLog.DEVICE_CAMERA,
            device_code=camera.camera_code,
            device_name=camera.name,
            area=camera.area or "",
            fault_code="CAMERA_RTSP_UNAVAILABLE",
            fault_description="Unable to open RTSP stream or read frame.",
            severity=DeviceFaultLog.SEVERITY_WARNING,
        )
    except Exception:
        pass

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