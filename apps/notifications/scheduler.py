import datetime

from django.db import transaction
from django.utils import timezone

from .models import BroadcastSchedule
from .services import (
    SOURCE_PRIORITY_SCHEDULE,
    clear_stale_schedule_broadcast_locks,
    enqueue_broadcast_log,
    process_queued_broadcasts,
)


def _advance_schedule(schedule, now):
    schedule.last_run_at = now
    if schedule.schedule_type == BroadcastSchedule.TYPE_ONCE:
        schedule.is_active = False
        schedule.next_run_at = None
    else:
        local_now = timezone.localtime(now)
        next_date = local_now.date() + datetime.timedelta(days=1)
        schedule.next_run_at = timezone.make_aware(
            datetime.datetime.combine(next_date, schedule.daily_time),
            timezone.get_current_timezone(),
        )
    schedule.save(update_fields=["last_run_at", "is_active", "next_run_at", "updated_at"])


def process_due_broadcast_schedules(limit=10):
    now = timezone.now()
    clear_stale_schedule_broadcast_locks()
    schedule_ids = list(
        BroadcastSchedule.objects.filter(
            is_active=True,
            next_run_at__isnull=False,
            next_run_at__lte=now,
        ).order_by("next_run_at").values_list("id", flat=True)[:limit]
    )

    summary = {"due_count": len(schedule_ids), "processed": [], "failed": []}

    for schedule_id in schedule_ids:
        with transaction.atomic():
            schedule = (
                BroadcastSchedule.objects.select_for_update()
                .select_related("audio_file")
                .prefetch_related("speakers")
                .get(pk=schedule_id)
            )
            if not schedule.is_active or not schedule.next_run_at or schedule.next_run_at > now:
                continue

            speakers = list(schedule.speakers.filter(is_active=True).order_by("speaker_code"))
            if not speakers:
                _advance_schedule(schedule, now)
                summary["failed"].append({"schedule_id": schedule.id, "message": "No active speakers."})
                continue

            logs = []
            for speaker in speakers:
                log, _queued = enqueue_broadcast_log(
                    speaker=speaker,
                    audio_file=schedule.audio_file,
                    queue_priority=SOURCE_PRIORITY_SCHEDULE,
                    request_payload={
                        "source": "broadcast_schedule",
                        "schedule_id": schedule.id,
                        "schedule_name": schedule.name,
                        "speaker_code": speaker.speaker_code,
                        "audio_code": schedule.audio_file.audio_code,
                        "volume_percent": schedule.volume_percent,
                    },
                    message=f"Scheduled broadcast queued: {schedule.name}",
                    requested_at=now,
                )
                logs.append(log)
            _advance_schedule(schedule, now)

        queue_result = process_queued_broadcasts(
            speaker_ids=[log.speaker_id for log in logs],
            limit=max(10, len(logs)),
            max_workers=min(len(logs), 4),
        )
        summary["processed"].append(
            {
                "schedule_id": schedule_id,
                "log_count": len(logs),
                "results": queue_result["results"],
            }
        )

    summary["queue_recovery"] = process_queued_broadcasts(
        limit=max(10, limit),
    )
    return summary
