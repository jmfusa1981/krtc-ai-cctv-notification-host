from django.core.management.base import BaseCommand, CommandError

from apps.events.services.fake_nvr import (
    FakeNvrHttpServer,
    FakeNvrState,
    ensure_fake_nvr_allowed,
)


class Command(BaseCommand):
    help = "Run the development-only Fake NVR Lab HTTP server."

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=18080)
        parser.add_argument("--delay-seconds", type=float, default=5.0)
        parser.add_argument("--username", default="lab")
        parser.add_argument("--password", default="lab")

    def handle(self, *args, **options):
        ensure_fake_nvr_allowed()
        host = options["host"]
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise CommandError("Fake NVR may bind only to a loopback address.")
        state = FakeNvrState(delay_seconds=options["delay_seconds"])
        server = FakeNvrHttpServer(
            (host, options["port"]),
            state=state,
            username=options["username"],
            password=options["password"],
        )

        self.stdout.write(self.style.WARNING("FAKE NVR LAB ONLY"))
        self.stdout.write(self.style.WARNING("DO NOT USE IN PRODUCTION"))
        self.stdout.write(
            f"Listening on http://{host}:{server.server_address[1]} "
            f"with delay={state.delay_seconds:g}s"
        )
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            self.stdout.write("Fake NVR stopping.")
        finally:
            server.server_close()
