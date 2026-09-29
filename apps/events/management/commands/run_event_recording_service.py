import signal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.events.services.recording_worker import RecordingWorker
from apps.events.services.recording_service_lock import (
    RecordingServiceAlreadyRunning,
    RecordingServiceProcessLock,
)


class Command(BaseCommand):
    help = "Run the PAO-owned NVR event recording acquisition worker."

    def handle(self, *args, **options):
        worker = RecordingWorker()

        def request_stop(signum, _frame):
            self.stdout.write(
                f"Event recording service stop requested by signal {signum}."
            )
            worker.stop_event.set()

        for signal_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            process_signal = getattr(signal, signal_name, None)
            if process_signal is not None:
                signal.signal(process_signal, request_stop)

        try:
            with RecordingServiceProcessLock(
                settings.KRTC_EVENT_RECORDING_LOCK_PATH
            ):
                self.stdout.write(self.style.SUCCESS("Event recording service started."))
                try:
                    worker.run()
                except KeyboardInterrupt:
                    worker.stop_event.set()
                    self.stdout.write("Event recording service stopping.")
        except RecordingServiceAlreadyRunning as exc:
            raise CommandError(str(exc)) from exc
