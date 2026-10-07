from django.core.management.base import BaseCommand, CommandError

from apps.cameras.models import Camera
from apps.events.services.fake_nvr import FAKE_NVR_CAMERAS, ensure_fake_nvr_allowed


class Command(BaseCommand):
    help = "Preview or explicitly apply loopback Fake NVR mappings to Lab cameras."

    def add_arguments(self, parser):
        parser.add_argument(
            "--camera-code",
            action="append",
            dest="camera_codes",
            help="Repeat to select cameras; default selects CAM-001 through CAM-004.",
        )
        parser.add_argument("--port", type=int, default=18080)
        parser.add_argument("--username", default="lab")
        parser.add_argument("--password", default="lab")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm", default="")

    def handle(self, *args, **options):
        ensure_fake_nvr_allowed()
        mapping = {item["CameraCode"]: item["Channel"] for item in FAKE_NVR_CAMERAS}
        selected = options["camera_codes"] or list(mapping)
        unknown = sorted(set(selected) - set(mapping))
        if unknown:
            raise CommandError(f"Unsupported Fake NVR camera code: {', '.join(unknown)}")
        if options["port"] < 1 or options["port"] > 65535:
            raise CommandError("--port must be between 1 and 65535.")
        if not options["username"] or not options["password"]:
            raise CommandError("Lab username and password must not be blank.")
        if options["apply"] and options["confirm"] != "FAKE-NVR-LAB":
            raise CommandError("Apply requires --apply --confirm FAKE-NVR-LAB.")

        self.stdout.write("FAKE NVR LAB ONLY")
        self.stdout.write("DO NOT USE IN PRODUCTION")
        changed = 0
        for camera_code in selected:
            camera = Camera.objects.filter(camera_code=camera_code).first()
            if camera is None:
                self.stdout.write(f"  {camera_code}: not found; skipped")
                continue
            self.stdout.write(
                f"  {camera_code}: current={camera.nvr_host or '<blank>'}:"
                f"{camera.nvr_port or '<default>'} channel={camera.nvr_channel}; "
                f"target=127.0.0.1:{options['port']} "
                f"channel={mapping[camera_code]} username={options['username']}"
            )
            if not options["apply"]:
                continue
            camera.nvr_host = "127.0.0.1"
            camera.nvr_port = options["port"]
            camera.nvr_channel = mapping[camera_code]
            camera.nvr_username = options["username"]
            camera.nvr_password = options["password"]
            camera.nvr_recording_enabled = True
            camera.save(
                update_fields=[
                    "nvr_host",
                    "nvr_port",
                    "nvr_channel",
                    "nvr_username",
                    "nvr_password",
                    "nvr_recording_enabled",
                ]
            )
            changed += 1

        if options["apply"]:
            self.stdout.write(self.style.SUCCESS(f"Applied {changed} Lab mapping(s)."))
        else:
            self.stdout.write("DRY-RUN: no Camera rows were changed.")
