import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.settings_app.services.config_backup import (
    BACKUP_FORMAT,
    BACKUP_SCHEMA_VERSION,
    configuration_counts,
    export_configuration_archive,
    inspect_configuration_archive,
)


class Command(BaseCommand):
    help = "Validate V6.6 persistent-data and configuration-backup foundation."

    def handle(self, *args, **options):
        failures = []

        def check(condition, label):
            if condition:
                self.stdout.write(self.style.SUCCESS(f"PASS: {label}"))
            else:
                failures.append(label)
                self.stdout.write(self.style.ERROR(f"FAIL: {label}"))

        for attr in ["KRTC_PERSISTENT_ROOT", "KRTC_CONFIG_DIR", "KRTC_DATA_DIR", "KRTC_MEDIA_DIR", "KRTC_LOG_DIR", "KRTC_BACKUP_DIR"]:
            check(hasattr(settings, attr), f"persistent path setting {attr}")

        check(Path(settings.DATABASES["default"]["NAME"]).parent == Path(settings.KRTC_DATA_DIR), "database uses KRTC_DATA_DIR")
        check(Path(settings.MEDIA_ROOT) == Path(settings.KRTC_MEDIA_DIR), "media uses KRTC_MEDIA_DIR")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config-backup.zip"
            export_configuration_archive(path)
            check(path.is_file() and path.stat().st_size > 0, "configuration ZIP export")
            manifest, payload = inspect_configuration_archive(path)
            check(manifest.get("format") == BACKUP_FORMAT, "backup format marker")
            check(manifest.get("backup_schema_version") == BACKUP_SCHEMA_VERSION, "backup schema version")
            camera_rows = payload.get("cameras") or []
            speaker_rows = payload.get("speakers") or []
            check(all("password" not in row and "nvr_password" not in row for row in camera_rows), "camera secrets excluded")
            check(all("password" not in row for row in speaker_rows), "speaker secrets excluded")
            check((payload.get("ui_configuration") or {}).get("usb_credentials_exported") is False, "USB credential material excluded")
            counts = configuration_counts(payload)
            check(all(isinstance(v, int) and v >= 0 for v in counts.values()), "backup counts valid")

        if failures:
            raise CommandError(f"V6.6 Configuration Backup Foundation failed: {len(failures)} failure(s).")
        self.stdout.write(self.style.SUCCESS("V6.6 Configuration Backup Foundation self-test PASSED."))
