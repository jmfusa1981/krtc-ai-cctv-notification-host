from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.events.models import Event, EventRecordingEvidence
from apps.events.services.nvr_recording import (
    NvrRecordingError,
    create_recording_evidence,
    refresh_export_status,
)


class Command(BaseCommand):
    help = "Create or refresh NVR recording evidence for one event."

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int, help="Local PAO Event.id")
        parser.add_argument(
            "--force-new",
            action="store_true",
            help="Create a new recording evidence even when one already exists.",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Refresh the latest existing recording evidence instead of creating one.",
        )

    def handle(self, *args, **options):
        event = Event.objects.select_related("camera").filter(pk=options["event_id"]).first()
        if event is None:
            raise CommandError(f"Event not found: {options['event_id']}")

        try:
            if options["refresh"]:
                evidence = event.recording_evidences.order_by("-created_at").first()
                if evidence is None:
                    raise CommandError("No recording evidence exists for this event.")
                evidence = refresh_export_status(evidence)
            else:
                evidence = create_recording_evidence(
                    event,
                    force_new=options["force_new"],
                )
        except NvrRecordingError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Recording evidence processed."))
        self.stdout.write(f"  event_id           : {event.id}")
        self.stdout.write(f"  source_event_id    : {event.source_event_id or ''}")
        self.stdout.write(f"  camera_code        : {event.camera.camera_code if event.camera else ''}")
        self.stdout.write(f"  evidence_id        : {evidence.id}")
        self.stdout.write(f"  export_id          : {evidence.export_id}")
        self.stdout.write(f"  export_status      : {evidence.export_status}")
        self.stdout.write(f"  export_rate        : {evidence.export_rate}")
        self.stdout.write(f"  nvr_host           : {evidence.nvr_host}")
        self.stdout.write(f"  nvr_channel        : {evidence.nvr_channel}")
        self.stdout.write(
            "  evidence_start_at  : "
            f"{timezone.localtime(evidence.evidence_start_at):%Y-%m-%d %H:%M:%S}"
        )
        self.stdout.write(
            "  evidence_end_at    : "
            f"{timezone.localtime(evidence.evidence_end_at):%Y-%m-%d %H:%M:%S}"
        )
        self.stdout.write(f"  file_name          : {evidence.file_name or ''}")
        self.stdout.write(f"  last_error         : {evidence.last_error or ''}")
        if evidence.export_status == EventRecordingEvidence.STATUS_COMPLETED:
            self.stdout.write("  result             : completed/downloadable")
