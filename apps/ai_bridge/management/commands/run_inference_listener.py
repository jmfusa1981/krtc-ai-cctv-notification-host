import asyncio

from django.core.management.base import BaseCommand, CommandError

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.websocket_client import InferenceWebSocketReceiver


class Command(BaseCommand):
    help = "Run the independent multi-inference asynchronous listener service."

    def add_arguments(self, parser):
        parser.add_argument("--host-code", action="append", dest="host_codes")
        parser.add_argument("--catchup-only", action="store_true")

    def handle(self, *args, **options):
        hosts = list(InferenceHost.objects.filter(is_active=True).order_by("host_code"))
        if options["host_codes"]:
            hosts = [host for host in hosts if host.host_code in options["host_codes"]]
        if not hosts:
            raise CommandError("No enabled inference host is configured.")
        receivers = [InferenceWebSocketReceiver(inference_host=host) for host in hosts]
        if options["catchup_only"]:
            for receiver in receivers:
                self.stdout.write(f"{receiver.host.host_code}: imported={receiver.catch_up()}")
            return
        self.stdout.write("Listening: " + ", ".join(r.ws_url for r in receivers))
        try:
            asyncio.run(self._run(receivers))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Inference listener stopped."))

    async def _run(self, receivers):
        results = await asyncio.gather(*(receiver.run_forever() for receiver in receivers), return_exceptions=True)
        failures = [result for result in results if isinstance(result, Exception)]
        if failures:
            raise CommandError("All listener tasks stopped unexpectedly.")
