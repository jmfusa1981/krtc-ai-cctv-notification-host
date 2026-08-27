from pathlib import Path

from django.core.management.base import BaseCommand

from apps.settings_app.services.config_backup import export_configuration_archive


class Command(BaseCommand):
    help = "Export the station configuration backup ZIP."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="", help="Optional output ZIP path.")

    def handle(self, *args, **options):
        output = Path(options["output"]).expanduser() if options["output"] else None
        path, manifest = export_configuration_archive(output)
        self.stdout.write(self.style.SUCCESS(f"Configuration backup created: {path}"))
        self.stdout.write(f"Station: {manifest.get('station_code')}")
        self.stdout.write(f"Schema: {manifest.get('backup_schema_version')}")
        self.stdout.write(f"SHA256: {manifest.get('configuration_sha256')}")
