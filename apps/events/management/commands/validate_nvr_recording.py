from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.cameras.models import Camera
from apps.events.models import Event
from apps.events.services.nvr_recording import (
    NvrRecordingError,
    _camera_nvr_config,
    _local_nvr_timestamp,
    create_recording_evidence,
)


class Command(BaseCommand):
    help = "Dry-run NVR recording mapping/window validation; real execution is explicit."

    def add_arguments(self, parser):
        selector = parser.add_mutually_exclusive_group(required=True)
        selector.add_argument("--event-id", type=int)
        selector.add_argument("--camera-code")
        parser.add_argument(
            "--detected-at",
            help="Camera-only dry-run timestamp in ISO-8601 format.",
        )
        parser.add_argument("--execute", action="store_true")
        parser.add_argument(
            "--confirm",
            default="",
            help="Real execution requires the exact value REAL-NVR.",
        )

    def handle(self, *args, **options):
        event = None
        if options["event_id"] is not None:
            event = (
                Event.objects.select_related("camera")
                .filter(pk=options["event_id"])
                .first()
            )
            if event is None:
                raise CommandError(f"Event not found: {options['event_id']}")
            camera = event.camera
            detected_at = event.detected_at
        else:
            camera = Camera.objects.filter(camera_code=options["camera_code"]).first()
            if camera is None:
                raise CommandError(f"Camera not found: {options['camera_code']}")
            detected_at = parse_datetime(options["detected_at"] or "")
            if detected_at is None or timezone.is_naive(detected_at):
                raise CommandError("--detected-at must be a timezone-aware ISO-8601 value.")

        if camera is None:
            raise CommandError("Event does not resolve to a Camera.")

        # 僅借用事件模型介面解析設定；不寫入或修改攝影機資料。
        probe = event or Event(camera=camera, detected_at=detected_at)
        try:
            config = _camera_nvr_config(probe)
            start_at = detected_at - timedelta(seconds=30)
            end_at = detected_at + timedelta(seconds=90)
            start_text = _local_nvr_timestamp(start_at)
            end_text = _local_nvr_timestamp(end_at)
        except NvrRecordingError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write("NVR recording validation (DRY-RUN)" if not options["execute"] else "NVR recording validation (REAL)")
        self.stdout.write(f"  event_id    : {event.pk if event else ''}")
        self.stdout.write(f"  camera_code : {camera.camera_code}")
        self.stdout.write(f"  nvr_target  : {config.host}:{config.port}")
        self.stdout.write(f"  nvr_channel : {config.channel}")
        self.stdout.write(f"  start_time  : {start_text}")
        self.stdout.write(f"  end_time    : {end_text}")
        self.stdout.write("  duration    : 120 seconds")

        if not options["execute"]:
            self.stdout.write("  result      : no database write and no NVR request")
            return
        if options["confirm"] != "REAL-NVR":
            raise CommandError("Real execution requires --execute --confirm REAL-NVR.")
        if event is None:
            raise CommandError("Real execution requires --event-id.")

        evidence = create_recording_evidence(event)
        self.stdout.write(f"  evidence_id : {evidence.pk}")
        self.stdout.write(f"  export_id   : {evidence.export_id}")
        self.stdout.write(f"  status      : {evidence.export_status}")
        self.stdout.write(f"  local_file  : {evidence.file.name if evidence.file else ''}")
        self.stdout.write(f"  file_size   : {evidence.file_size}")
