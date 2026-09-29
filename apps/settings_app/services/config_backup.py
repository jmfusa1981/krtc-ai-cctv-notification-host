from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import uuid
import zipfile
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.utils import timezone

BACKUP_FORMAT = "KRTC_PAO_CONFIGURATION_BACKUP"
BACKUP_SCHEMA_VERSION = "1.0"


class ConfigurationBackupError(Exception):
    pass


def _json_default(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported JSON type: {type(value)!r}")


def _safe_rtsp_url(value: str) -> str:
    """Remove URL userinfo so configuration exports do not leak camera passwords."""
    value = (value or "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        if not parsed.hostname:
            return value
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        return value


def _model(name):
    app_label, model_name = name.split(".", 1)
    return apps.get_model(app_label, model_name)


def _plain_fields(obj, names):
    return {name: getattr(obj, name) for name in names}


def _media_relpath(field_file):
    if not field_file:
        return ""
    try:
        return str(field_file.name or "").replace("\\", "/")
    except Exception:
        return ""


def _append_media(zipf, field_file, archived_names):
    rel = _media_relpath(field_file)
    if not rel or rel in archived_names:
        return
    try:
        path = Path(field_file.path)
    except Exception:
        return
    if path.is_file():
        arcname = f"media/{rel}"
        zipf.write(path, arcname)
        archived_names.add(rel)


def build_configuration_payload():
    StationLocalSettings = _model("settings_app.StationLocalSettings")
    UIConfiguration = _model("settings_app.UIConfiguration")
    InferenceHost = _model("ai_bridge.InferenceHost")
    InferenceCameraMapping = _model("ai_bridge.InferenceCameraMapping")
    AIModel = _model("ai_bridge.AIModel")
    Camera = _model("cameras.Camera")
    SpeakerDevice = _model("notifications.SpeakerDevice")
    AudioFile = _model("notifications.AudioFile")
    BroadcastRule = _model("notifications.BroadcastRule")
    BroadcastSchedule = _model("notifications.BroadcastSchedule")

    station = StationLocalSettings.load()
    ui = UIConfiguration.load()

    payload = {
        "station": _plain_fields(station, [
            "station_code", "station_name", "notification_host_name", "system_version",
            "default_monitor_grid", "carousel_interval_seconds", "dashboard_refresh_seconds",
            "notification_sound_enabled", "warning_light_enabled", "auto_broadcast_enabled",
            "maintenance_host_url", "config_version",
        ]),
        "ui_configuration": {
            **_plain_fields(ui, [
                "login_theme", "login_background_enabled", "login_overlay_opacity",
                "login_title", "login_subtitle", "login_footer_text",
            ]),
            "login_background": _media_relpath(ui.login_background),
            "superuser_usb_required": bool(ui.superuser_usb_required),
            "usb_credentials_exported": False,
        },
        "inference_hosts": [],
        "cameras": [],
        "ai_models": [],
        "camera_mappings": [],
        "speakers": [],
        "audio_files": [],
        "broadcast_rules": [],
        "broadcast_schedules": [],
    }

    for obj in InferenceHost.objects.all().order_by("host_code"):
        payload["inference_hosts"].append(_plain_fields(obj, [
            "host_code", "name", "base_url", "configuration_url", "station_code", "host_type",
            "ip_address", "port", "health_url", "events_url", "websocket_url",
            "websocket_auth_mode", "application_version", "is_active", "timeout_seconds",
            "description",
        ]))

    for obj in Camera.objects.all().order_by("camera_code"):
        item = _plain_fields(obj, [
            "name", "camera_code", "area", "username", "is_active", "description", "nvr_host",
            "nvr_port", "nvr_username", "nvr_channel", "nvr_camera_uid", "nvr_recording_enabled",
        ])
        item["rtsp_url"] = _safe_rtsp_url(obj.rtsp_url)
        item["password_exported"] = False
        item["nvr_password_exported"] = False
        payload["cameras"].append(item)

    for obj in AIModel.objects.all().order_by("model_code"):
        payload["ai_models"].append(_plain_fields(obj, [
            "name", "model_code", "version", "event_type", "api_url", "model_path",
            "confidence_threshold", "is_active", "description",
        ]))

    for obj in InferenceCameraMapping.objects.select_related("inference_host", "camera").all().order_by("id"):
        payload["camera_mappings"].append({
            "inference_host_code": obj.inference_host.host_code,
            "source_camera_id": obj.source_camera_id,
            "camera_code": obj.camera.camera_code,
            "is_active": obj.is_active,
            "description": obj.description,
        })

    for obj in SpeakerDevice.objects.all().order_by("speaker_code"):
        item = _plain_fields(obj, [
            "speaker_code", "name", "station_name", "area", "location_note", "ip_address", "port",
            "network_mode", "preferred_codec", "protocol", "sip_uri", "username", "is_active",
            "deployment_state", "health_monitor_enabled", "description",
        ])
        item["password_exported"] = False
        payload["speakers"].append(item)

    for obj in AudioFile.objects.all().order_by("audio_code"):
        item = _plain_fields(obj, [
            "audio_code", "name", "audio_type", "duration_seconds", "message_text", "is_active", "description",
        ])
        item["file"] = _media_relpath(obj.file)
        payload["audio_files"].append(item)

    for obj in BroadcastRule.objects.select_related("camera", "speaker", "audio_file").prefetch_related("speakers").all().order_by("priority", "rule_code"):
        payload["broadcast_rules"].append({
            **_plain_fields(obj, ["rule_code", "name", "event_type", "priority", "auto_broadcast", "is_active", "description"]),
            "camera_code": obj.camera.camera_code if obj.camera_id else "",
            "legacy_speaker_code": obj.speaker.speaker_code if obj.speaker_id else "",
            "speaker_codes": list(obj.speakers.values_list("speaker_code", flat=True)),
            "audio_code": obj.audio_file.audio_code,
        })

    for obj in BroadcastSchedule.objects.select_related("audio_file").prefetch_related("speakers").all().order_by("id"):
        payload["broadcast_schedules"].append({
            **_plain_fields(obj, ["name", "schedule_type", "run_at", "daily_time", "volume_percent", "is_active"]),
            "audio_code": obj.audio_file.audio_code,
            "speaker_codes": list(obj.speakers.values_list("speaker_code", flat=True)),
        })

    return payload


def configuration_counts(payload):
    keys = [
        "inference_hosts", "cameras", "ai_models", "camera_mappings", "speakers",
        "audio_files", "broadcast_rules", "broadcast_schedules",
    ]
    return {key: len(payload.get(key) or []) for key in keys}


def export_configuration_archive(output_path: Path | None = None):
    payload = build_configuration_payload()
    station_code = payload["station"].get("station_code") or "STATION"
    exported_at = timezone.localtime(timezone.now())
    manifest = {
        "format": BACKUP_FORMAT,
        "backup_schema_version": BACKUP_SCHEMA_VERSION,
        "application_version": getattr(settings, "KRTC_APP_VERSION", "PAO-V6"),
        "station_code": station_code,
        "exported_at": exported_at.isoformat(),
        "credential_policy": "Device passwords, NVR passwords, OCC bearer tokens, Django secrets and USB token hashes are not exported.",
        "counts": configuration_counts(payload),
    }
    config_bytes = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")
    config_sha = hashlib.sha256(config_bytes).hexdigest()
    manifest["configuration_sha256"] = config_sha

    if output_path is None:
        backup_dir = Path(getattr(settings, "KRTC_BACKUP_DIR", settings.BASE_DIR / "backups"))
        backup_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{station_code}_CONFIG_BACKUP_{exported_at.strftime('%Y%m%d_%H%M%S')}.zip"
        output_path = backup_dir / filename
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    archived_names = set()
    UIConfiguration = _model("settings_app.UIConfiguration")
    AudioFile = _model("notifications.AudioFile")
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        zipf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        zipf.writestr("configuration.json", config_bytes)
        zipf.writestr("SHA256.txt", f"{config_sha}  configuration.json\n".encode("ascii"))
        ui = UIConfiguration.load()
        _append_media(zipf, ui.login_background, archived_names)
        for audio in AudioFile.objects.all():
            _append_media(zipf, audio.file, archived_names)
    return output_path, manifest


def inspect_configuration_archive(archive_path: Path):
    archive_path = Path(archive_path)
    try:
        with zipfile.ZipFile(archive_path, "r") as zipf:
            manifest = json.loads(zipf.read("manifest.json").decode("utf-8"))
            config_bytes = zipf.read("configuration.json")
            payload = json.loads(config_bytes.decode("utf-8"))
    except Exception as exc:
        raise ConfigurationBackupError(f"無法讀取備份檔：{exc}") from exc

    if manifest.get("format") != BACKUP_FORMAT:
        raise ConfigurationBackupError("備份格式不正確。")
    if manifest.get("backup_schema_version") != BACKUP_SCHEMA_VERSION:
        raise ConfigurationBackupError(
            f"不支援的備份格式版本：{manifest.get('backup_schema_version') or 'unknown'}"
        )
    expected = (manifest.get("configuration_sha256") or "").lower()
    actual = hashlib.sha256(config_bytes).hexdigest().lower()
    if not expected or expected != actual:
        raise ConfigurationBackupError("configuration.json SHA256 驗證失敗。")
    return manifest, payload


def stage_uploaded_archive(uploaded_file):
    backup_dir = Path(getattr(settings, "KRTC_BACKUP_DIR", settings.BASE_DIR / "backups"))
    staging = backup_dir / "import_staging"
    staging.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    path = staging / f"{token}.zip"
    with path.open("wb") as dst:
        for chunk in uploaded_file.chunks():
            dst.write(chunk)
    try:
        manifest, payload = inspect_configuration_archive(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return token, path, manifest, payload


def staged_archive_path(token: str) -> Path:
    if not token or any(ch not in "0123456789abcdef" for ch in token.lower()) or len(token) != 32:
        raise ConfigurationBackupError("還原 token 無效。")
    backup_dir = Path(getattr(settings, "KRTC_BACKUP_DIR", settings.BASE_DIR / "backups"))
    path = backup_dir / "import_staging" / f"{token}.zip"
    if not path.is_file():
        raise ConfigurationBackupError("暫存備份檔不存在或已失效。")
    return path


def create_restore_point():
    db_name = settings.DATABASES["default"]["NAME"]
    db_path = Path(db_name)
    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3" or not db_path.is_file():
        raise ConfigurationBackupError("目前只支援 SQLite 自動還原點。")
    backup_dir = Path(getattr(settings, "KRTC_BACKUP_DIR", settings.BASE_DIR / "backups")) / "restore_points"
    backup_dir.mkdir(parents=True, exist_ok=True)
    station_code = _model("settings_app.StationLocalSettings").load().station_code or "STATION"
    stamp = timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"{station_code}_PRE_RESTORE_DB_{stamp}.sqlite3"
    shutil.copy2(db_path, target)
    return target


def _restore_media(zipf, relpath):
    relpath = (relpath or "").replace("\\", "/").lstrip("/")
    if not relpath:
        return ""
    member = f"media/{relpath}"
    if member not in zipf.namelist():
        return relpath
    media_root = Path(settings.MEDIA_ROOT)
    target = (media_root / relpath).resolve()
    if media_root.resolve() not in target.parents and target != media_root.resolve():
        raise ConfigurationBackupError("媒體檔案路徑不安全。")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipf.open(member) as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    return relpath


def _clean_defaults(model, item, excluded=()):
    valid = {f.name for f in model._meta.fields if not f.primary_key and not getattr(f, "auto_created", False)}
    valid -= set(excluded)
    return {k: v for k, v in item.items() if k in valid}


def restore_configuration_archive(archive_path: Path):
    manifest, payload = inspect_configuration_archive(archive_path)
    restore_point = create_restore_point()

    StationLocalSettings = _model("settings_app.StationLocalSettings")
    UIConfiguration = _model("settings_app.UIConfiguration")
    InferenceHost = _model("ai_bridge.InferenceHost")
    InferenceCameraMapping = _model("ai_bridge.InferenceCameraMapping")
    AIModel = _model("ai_bridge.AIModel")
    Camera = _model("cameras.Camera")
    SpeakerDevice = _model("notifications.SpeakerDevice")
    AudioFile = _model("notifications.AudioFile")
    BroadcastRule = _model("notifications.BroadcastRule")
    BroadcastSchedule = _model("notifications.BroadcastSchedule")

    with zipfile.ZipFile(archive_path, "r") as zipf, transaction.atomic():
        station = StationLocalSettings.load()
        for key, value in (payload.get("station") or {}).items():
            if hasattr(station, key) and key not in {"id", "last_synced_at", "updated_at"}:
                setattr(station, key, value)
        station.save()

        ui = UIConfiguration.load()
        ui_data = payload.get("ui_configuration") or {}
        for key in ["login_theme", "login_background_enabled", "login_overlay_opacity", "login_title", "login_subtitle", "login_footer_text"]:
            if key in ui_data:
                setattr(ui, key, ui_data[key])
        rel = _restore_media(zipf, ui_data.get("login_background"))
        if rel:
            ui.login_background = rel
        # Preserve the entire local USB security policy. The backup is informational only
        # and never changes enforcement or trusted key material on restore.
        ui.save()

        for item in payload.get("inference_hosts") or []:
            code = item.get("host_code")
            if not code:
                continue
            defaults = _clean_defaults(InferenceHost, item, excluded={"host_code", "status", "last_health_at", "last_success_at", "last_error_at", "last_error", "created_at", "updated_at"})
            InferenceHost.objects.update_or_create(host_code=code, defaults=defaults)

        for item in payload.get("cameras") or []:
            code = item.get("camera_code")
            if not code:
                continue
            existing = Camera.objects.filter(camera_code=code).first()
            defaults = _clean_defaults(Camera, item, excluded={"camera_code", "password", "nvr_password", "status", "is_online", "last_checked_at", "created_at"})
            if existing:
                defaults["password"] = existing.password
                defaults["nvr_password"] = existing.nvr_password
            Camera.objects.update_or_create(camera_code=code, defaults=defaults)

        for item in payload.get("ai_models") or []:
            code = item.get("model_code")
            if not code:
                continue
            defaults = _clean_defaults(AIModel, item, excluded={"model_code", "created_at", "updated_at"})
            AIModel.objects.update_or_create(model_code=code, defaults=defaults)

        for item in payload.get("speakers") or []:
            code = item.get("speaker_code")
            if not code:
                continue
            existing = SpeakerDevice.objects.filter(speaker_code=code).first()
            defaults = _clean_defaults(SpeakerDevice, item, excluded={"speaker_code", "password", "status", "last_checked_at", "created_at", "updated_at"})
            if existing:
                defaults["password"] = existing.password
            SpeakerDevice.objects.update_or_create(speaker_code=code, defaults=defaults)

        for item in payload.get("audio_files") or []:
            code = item.get("audio_code")
            if not code:
                continue
            rel = _restore_media(zipf, item.get("file"))
            defaults = _clean_defaults(AudioFile, item, excluded={"audio_code", "file", "created_at", "updated_at"})
            if rel:
                defaults["file"] = rel
            AudioFile.objects.update_or_create(audio_code=code, defaults=defaults)

        # Mappings are configuration, so rebuild only the mapping table.
        InferenceCameraMapping.objects.all().delete()
        for item in payload.get("camera_mappings") or []:
            host = InferenceHost.objects.filter(host_code=item.get("inference_host_code")).first()
            camera = Camera.objects.filter(camera_code=item.get("camera_code")).first()
            if not host or not camera or not item.get("source_camera_id"):
                continue
            InferenceCameraMapping.objects.update_or_create(
                inference_host=host,
                source_camera_id=item["source_camera_id"],
                defaults={
                    "camera": camera,
                    "is_active": bool(item.get("is_active", True)),
                    "description": item.get("description") or "",
                },
            )

        for item in payload.get("broadcast_rules") or []:
            code = item.get("rule_code")
            audio = AudioFile.objects.filter(audio_code=item.get("audio_code")).first()
            if not code or not audio:
                continue
            camera = Camera.objects.filter(camera_code=item.get("camera_code")).first() if item.get("camera_code") else None
            legacy = SpeakerDevice.objects.filter(speaker_code=item.get("legacy_speaker_code")).first() if item.get("legacy_speaker_code") else None
            defaults = {
                "name": item.get("name") or code,
                "event_type": item.get("event_type") or "other",
                "camera": camera,
                "speaker": legacy,
                "audio_file": audio,
                "priority": item.get("priority", 100),
                "auto_broadcast": bool(item.get("auto_broadcast", True)),
                "is_active": bool(item.get("is_active", True)),
                "description": item.get("description") or "",
            }
            rule, _ = BroadcastRule.objects.update_or_create(rule_code=code, defaults=defaults)
            rule.speakers.set(SpeakerDevice.objects.filter(speaker_code__in=item.get("speaker_codes") or []))

        # Schedules do not have a stable code; rebuild the schedule configuration only.
        BroadcastSchedule.objects.all().delete()
        for item in payload.get("broadcast_schedules") or []:
            audio = AudioFile.objects.filter(audio_code=item.get("audio_code")).first()
            if not audio:
                continue
            schedule = BroadcastSchedule.objects.create(
                name=item.get("name") or "Imported Schedule",
                schedule_type=item.get("schedule_type") or "once",
                audio_file=audio,
                run_at=item.get("run_at") or None,
                daily_time=item.get("daily_time") or None,
                volume_percent=item.get("volume_percent", 100),
                is_active=bool(item.get("is_active", True)),
            )
            schedule.speakers.set(SpeakerDevice.objects.filter(speaker_code__in=item.get("speaker_codes") or []))

    return {
        "manifest": manifest,
        "counts": configuration_counts(payload),
        "restore_point": str(restore_point),
    }
