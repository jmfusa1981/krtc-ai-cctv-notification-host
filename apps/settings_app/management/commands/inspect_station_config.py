from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.settings_app.services.config_backup import ConfigurationBackupError, configuration_counts, inspect_configuration_archive


class Command(BaseCommand):
    help = "Validate and inspect a KRTC station configuration backup ZIP without restoring it."

    def add_arguments(self, parser):
        parser.add_argument("archive")

    def handle(self, *args, **options):
        try:
            manifest, payload = inspect_configuration_archive(Path(options["archive"]))
        except ConfigurationBackupError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Configuration backup validation PASSED."))
        self.stdout.write(f"Station: {manifest.get('station_code')}")
        self.stdout.write(f"Schema: {manifest.get('backup_schema_version')}")
        for key, value in configuration_counts(payload).items():
            self.stdout.write(f"{key}: {value}")
