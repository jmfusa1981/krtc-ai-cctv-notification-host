from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.ai_bridge.services.event_importer import matching_auto_broadcast_rules_for_event
from apps.events.models import Event
from apps.notifications.models import BroadcastLog, BroadcastRule, SpeakerDevice


class Command(BaseCommand):
    help = "Diagnose why automatic BroadcastRule playback did or did not run."

    def add_arguments(self, parser):
        parser.add_argument("--event-id", type=int, default=None)
        parser.add_argument("--source-event-id", default="")
        parser.add_argument("--limit", type=int, default=5)

    def handle(self, *args, **options):
        events = self._get_events(options)

        self.stdout.write("Auto broadcast diagnostics")
        self.stdout.write(f"Playback mode: {getattr(settings, 'BROADCAST_PLAYBACK_MODE', 'simulation')}")
        self.stdout.write(
            "Auto process on import: "
            f"{getattr(settings, 'AUTO_BROADCAST_PROCESS_ON_IMPORT', True)}"
        )
        self.stdout.write("")

        for event in events:
            self._print_event(event)
            self.stdout.write("")

    def _get_events(self, options):
        queryset = Event.objects.select_related("camera").order_by("-detected_at", "-created_at")
        event_id = options["event_id"]
        source_event_id = str(options["source_event_id"] or "").strip()

        if event_id is not None:
            queryset = queryset.filter(pk=event_id)
        elif source_event_id:
            queryset = queryset.filter(source_event_id=source_event_id)
        else:
            queryset = queryset[: max(1, int(options["limit"]))]

        events = list(queryset)
        if not events:
            raise CommandError("No matching Event rows found.")
        return events

    def _print_event(self, event):
        camera_code = event.camera.camera_code if event.camera else "(no camera)"
        self.stdout.write(
            self.style.HTTP_INFO(
                f"Event #{event.pk}: source_event_id={event.source_event_id} "
                f"type={event.event_type} camera={camera_code}"
            )
        )
        self.stdout.write(
            f"  mapping_status={event.mapping_status} "
            f"event_code={event.event_code} camera_code={event.camera_code} "
            f"ingestion_mode={event.ingestion_mode}"
        )

        rules = self._matching_rules(event)
        if rules:
            self.stdout.write(f"  matching_rules={len(rules)}")
            for rule in rules:
                audio = rule.audio_file
                speakers = list(rule.target_speakers_queryset())
                speaker_codes = ", ".join(speaker.speaker_code for speaker in speakers) or "(no speaker)"
                speaker_health = ", ".join(
                    f"{speaker.speaker_code}:active={speaker.is_active},status={speaker.status}"
                    for speaker in speakers
                ) or "(no speaker)"
                self.stdout.write(
                    "    "
                    f"{rule.rule_code}: active={rule.is_active} "
                    f"auto={rule.auto_broadcast} "
                    f"speakers={speaker_codes} "
                    f"speaker_health={speaker_health} "
                    f"audio={audio.audio_code} "
                    f"audio_active={audio.is_active}"
                )
        else:
            self.stdout.write(self.style.WARNING("  matching_rules=0"))
            if event.mapping_status != "resolved" and event.camera_id is not None:
                self.stdout.write("    Reason: event mapping_status is not resolved.")
            if event.camera_id is None:
                self.stdout.write(
                    "    Reason: event has no mapped Camera; only Camera-empty "
                    "global rules can match this event."
                )
            self.stdout.write(
                "    Check BroadcastRule event_type/camera and InferenceCameraMapping."
            )

        logs = list(
            BroadcastLog.objects
            .filter(event=event)
            .select_related("rule", "speaker", "audio_file")
            .order_by("-created_at")[:10]
        )
        if logs:
            self.stdout.write(f"  broadcast_logs={len(logs)}")
            for log in logs:
                reason = ""
                if isinstance(log.response_payload, dict):
                    reason = str(log.response_payload.get("reason") or "")
                speaker_code = log.speaker.speaker_code if log.speaker else "(no speaker)"
                rule_code = log.rule.rule_code if log.rule else "(no rule)"
                self.stdout.write(
                    "    "
                    f"log_id={log.pk} status={log.status} "
                    f"rule={rule_code} speaker={speaker_code} "
                    f"message={log.message[:120]} reason={reason}"
                )
        else:
            self.stdout.write(self.style.WARNING("  broadcast_logs=0"))

        busy = list(
            BroadcastLog.objects
            .filter(
                speaker__in=[
                    speaker
                    for rule in rules
                    for speaker in rule.target_speakers_queryset()
                ],
                status__in=[BroadcastLog.STATUS_PENDING, BroadcastLog.STATUS_PLAYING],
            )
            .select_related("speaker")
            .order_by("created_at")
        )
        if busy:
            self.stdout.write("  active speaker locks:")
            for log in busy:
                self.stdout.write(
                    "    "
                    f"speaker={log.speaker.speaker_code} "
                    f"log_id={log.pk} status={log.status} source={self._log_source(log)}"
                )

    @staticmethod
    def _matching_rules(event):
        return matching_auto_broadcast_rules_for_event(event)

    @staticmethod
    def _log_source(log):
        if isinstance(log.request_payload, dict):
            return str(log.request_payload.get("source") or "")
        return ""
