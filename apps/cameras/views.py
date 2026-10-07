import threading
import time

import cv2
from django.contrib.auth.decorators import login_required
from apps.cameras.rtsp_utils import camera_rtsp_url
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.station_api.device_faults import recover_device_fault, report_device_fault
from apps.station_api.models import DeviceFaultLog

from .forms import MonitorProfileForm, MonitorTransitionAckForm
from .models import Camera
from .mediamtx import get_camera_playback
from .monitor_diagnostics import collect_mediamtx_path_readiness
from .monitor_profiles import request_monitor_profile
from .monitor_transitions import acknowledge_monitor_transition
from .mosaic import (
    MOSAIC_PROFILES,
    CameraMosaicSource,
    MosaicCapacityError,
    MosaicLayoutBusyError,
    MosaicSessionCapacityError,
    acquire_mosaic_stream,
    release_mosaic_stream,
)
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
        playback = get_camera_playback(camera)
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
            "browser_playback": {
                "available": playback.available,
                "kind": "mediamtx_webrtc" if playback.available else None,
                "url": playback.player_url if playback.available else None,
                "reason": playback.reason,
            },
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


@login_required
def camera_playback_api(request, camera_id):
    """回傳瀏覽器可用的安全播放端點，不揭露攝影機來源與登入資料。"""

    try:
        camera = Camera.objects.get(id=camera_id)
    except Camera.DoesNotExist:
        raise Http404("Camera not found.")

    playback = get_camera_playback(camera)
    payload = {
        "success": playback.available,
        "camera_id": camera.id,
        "camera_code": camera.camera_code,
        "available": playback.available,
        "kind": "mediamtx_webrtc" if playback.available else None,
        "url": playback.player_url if playback.available else None,
        "whep_url": playback.whep_url if playback.available else None,
        "reason": playback.reason,
    }
    return JsonResponse(
        payload,
        status=200 if playback.available else 503,
        json_dumps_params={"ensure_ascii": False},
    )


@login_required
def camera_media_status_api(request):
    """回傳不含來源網址與憑證的MediaMTX path ready快照。"""

    status = collect_mediamtx_path_readiness()
    return JsonResponse(
        {
            "success": status["reachable"],
            "reachable": status["reachable"],
            "paths": status["paths"],
            "path_details": status.get("path_details", {}),
            "transition": status["transition"],
            "error": status["error"],
        },
        status=200 if status["reachable"] else 503,
        json_dumps_params={"ensure_ascii": False},
    )


@login_required
@require_POST
def camera_media_profile_api(request):
    """驗證並寫入bridge supervisor使用的Monitor profile請求。"""

    form = MonitorProfileForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {"success": False, "errors": form.errors.get_json_data()},
            status=400,
        )
    profile_name = form.cleaned_data["profile"]
    changed = request_monitor_profile(profile_name)
    return JsonResponse(
        {"success": True, "profile": profile_name, "changed": changed}
    )


@login_required
@require_POST
def camera_media_transition_ack_api(request):
    """接收瀏覽器全組WebRTC預載完成確認，不接受部分切換。"""

    form = MonitorTransitionAckForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {"success": False, "errors": form.errors.get_json_data()},
            status=400,
        )
    acknowledged = acknowledge_monitor_transition(
        form.cleaned_data["transition_id"],
        form.cleaned_data["camera_codes"],
    )
    return JsonResponse(
        {"success": acknowledged},
        status=200 if acknowledged else 409,
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


class MosaicMjpegIterator:
    """確保StreamingHttpResponse未迭代或中途斷線時仍釋放配額。"""

    def __init__(self, mosaic_stream, session_key):
        self._mosaic_stream = mosaic_stream
        self._session_key = session_key
        self._last_version = 0
        self._closed = False
        self._close_lock = threading.Lock()

    def __iter__(self):
        return self

    def __next__(self):
        if self._closed:
            raise StopIteration
        try:
            while True:
                self._last_version, jpeg_bytes = self._mosaic_stream.wait_for_jpeg(
                    self._last_version,
                    timeout=2.0,
                )
                if jpeg_bytes is not None:
                    return (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + jpeg_bytes
                        + b"\r\n"
                    )
                if self._mosaic_stream.stopping_or_stopped:
                    self.close()
                    raise StopIteration
        except BaseException:
            self.close()
            raise

    def close(self):
        """以idempotent方式釋放一次stream及session reservation。"""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        release_mosaic_stream(self._mosaic_stream, session_key=self._session_key)


def generate_mosaic_mjpeg_frames(layout, sources, session_key=None):
    """同步取得共享Mosaic，使容量錯誤能在HTTP headers前安全回覆。"""
    mosaic_stream = acquire_mosaic_stream(
        layout,
        sources,
        session_key=session_key,
    )
    return MosaicMjpegIterator(mosaic_stream, session_key)


def resolve_mosaic_sources(profile, group_index, ordered_camera_ids=None):
    """只以資料庫Camera建立受控來源，絕不接受client提供RTSP或encode參數。"""
    if ordered_camera_ids is not None:
        if len(ordered_camera_ids) != profile.camera_limit:
            raise ValueError("count")
        if len(ordered_camera_ids) != len(set(ordered_camera_ids)):
            raise ValueError("duplicate")

        cameras_by_id = {
            camera.id: camera
            for camera in Camera.objects.filter(
                id__in=ordered_camera_ids,
                is_active=True,
            )
        }
        if len(cameras_by_id) != len(ordered_camera_ids):
            raise ValueError("unknown")
        selected_cameras = [
            cameras_by_id[camera_id]
            for camera_id in ordered_camera_ids
        ]
    else:
        cameras = list(Camera.objects.filter(is_active=True).order_by("id"))
        group_start = group_index * profile.camera_limit
        if not cameras or group_start >= len(cameras):
            raise Http404("Mosaic camera group not found.")
        selected_cameras = cameras[group_start:group_start + profile.camera_limit]

    return tuple(
        CameraMosaicSource(
            camera_id=camera.id,
            camera_code=camera.camera_code,
            rtsp_url=camera_rtsp_url(camera),
        )
        for camera in selected_cameras
    )


@login_required
def camera_mosaic_stream(request):
    """提供僅限grid9/grid16、由伺服器推導Camera清單的Mosaic串流。"""
    allowed_parameters = {"layout", "group", "camera_ids", "ts"}
    if set(request.GET) - allowed_parameters:
        return JsonResponse(
            {"success": False, "message": "Unsupported mosaic parameter."},
            status=400,
        )

    if any(len(request.GET.getlist(name)) != 1 for name in request.GET):
        return JsonResponse(
            {"success": False, "message": "Duplicate mosaic parameter."},
            status=400,
        )

    layout = request.GET.get("layout", "")
    profile = MOSAIC_PROFILES.get(layout)
    if profile is None:
        return JsonResponse(
            {"success": False, "message": "Unsupported mosaic layout."},
            status=400,
        )

    try:
        group_index = int(request.GET.get("group", "0"))
    except (TypeError, ValueError):
        group_index = -1
    if group_index < 0:
        return JsonResponse(
            {"success": False, "message": "Invalid mosaic group."},
            status=400,
        )

    ordered_camera_ids = None
    raw_camera_ids = request.GET.get("camera_ids")
    if raw_camera_ids is not None:
        try:
            ordered_camera_ids = [
                int(value)
                for value in raw_camera_ids.split(",")
                if value and value.isascii() and value.isdecimal()
            ]
        except (TypeError, ValueError):
            ordered_camera_ids = []
        if len(ordered_camera_ids) != len(raw_camera_ids.split(",")):
            return JsonResponse(
                {"success": False, "message": "Invalid mosaic camera order."},
                status=400,
            )

    try:
        sources = resolve_mosaic_sources(
            profile,
            group_index,
            ordered_camera_ids=ordered_camera_ids,
        )
    except ValueError as exc:
        messages = {
            "count": "Invalid mosaic camera count.",
            "duplicate": "Duplicate mosaic camera.",
            "unknown": "Invalid mosaic camera order.",
        }
        return JsonResponse(
            {
                "success": False,
                "message": messages.get(
                    str(exc),
                    "Invalid mosaic camera order.",
                ),
            },
            status=400,
        )
    session_key = request.session.session_key or f"user:{request.user.pk}"
    try:
        stream_iterator = generate_mosaic_mjpeg_frames(
            layout,
            sources,
            session_key=session_key,
        )
    except MosaicSessionCapacityError:
        return JsonResponse(
            {"success": False, "message": "Mosaic session capacity exceeded."},
            status=429,
        )
    except MosaicLayoutBusyError:
        return JsonResponse(
            {"success": False, "message": "Mosaic layout is restarting."},
            status=503,
        )
    except MosaicCapacityError:
        return JsonResponse(
            {"success": False, "message": "Mosaic capacity unavailable."},
            status=503,
        )

    response = StreamingHttpResponse(
        stream_iterator,
        content_type="multipart/x-mixed-replace; boundary=frame",
    )
    response["Cache-Control"] = "no-store, no-cache"
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

    # Open/read timeout properties are open-only in OpenCV's FFmpeg backend,
    # so they must be passed to the constructor rather than set afterwards.
    cap = cv2.VideoCapture(
        camera_rtsp_url(camera),
        cv2.CAP_FFMPEG,
        [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
            3000,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
            3000,
        ],
    )

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
