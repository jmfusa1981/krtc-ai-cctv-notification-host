from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.settings_app.services.config_backup import ConfigurationBackupError, restore_configuration_archive


class Command(BaseCommand):
    help = "Restore a KRTC station configuration backup ZIP. Creates a SQLite DB restore point first."

    def add_arguments(self, parser):
        parser.add_argument("archive")
        parser.add_argument("--confirm", action="store_true", help="Required to perform the restore.")

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Restore is destructive. Re-run with --confirm after validating the archive.")
        try:
            result = restore_configuration_archive(Path(options["archive"]))
        except ConfigurationBackupError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Configuration restore completed."))
        self.stdout.write(f"Restore point: {result['restore_point']}")
