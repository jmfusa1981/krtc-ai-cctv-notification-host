import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from .models import BroadcastLog, BroadcastSchedule
from .services import process_single_broadcast_log


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
                try:
                    with transaction.atomic():
                        logs.append(
                            BroadcastLog.objects.create(
                            speaker=speaker,
                            audio_file=schedule.audio_file,
                            status=BroadcastLog.STATUS_PENDING,
                            request_payload={
                                "source": "broadcast_schedule",
                                "schedule_id": schedule.id,
                                "schedule_name": schedule.name,
                                "speaker_code": speaker.speaker_code,
                                "audio_code": schedule.audio_file.audio_code,
                                "volume_percent": schedule.volume_percent,
                            },
                            message=f"Scheduled broadcast created: {schedule.name}",
                                requested_at=now,
                            )
                        )
                except IntegrityError:
                    summary["failed"].append(
                        {"schedule_id": schedule.id, "speaker": speaker.speaker_code, "message": "Speaker busy."}
                    )
            _advance_schedule(schedule, now)

        def worker(log_id):
            close_old_connections()
            try:
                return process_single_broadcast_log(BroadcastLog.objects.get(pk=log_id))
            finally:
                close_old_connections()

        results = []
        if logs:
            with ThreadPoolExecutor(max_workers=min(len(logs), 4), thread_name_prefix="krtc-schedule") as executor:
                futures = [executor.submit(worker, log.id) for log in logs]
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        results.append({"status": "failed", "message": str(exc)})
        summary["processed"].append({"schedule_id": schedule_id, "log_count": len(logs), "results": results})

    return summary
