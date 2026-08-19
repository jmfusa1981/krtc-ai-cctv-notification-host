import ctypes
import json
import secrets
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.usb_key import (
    DRIVE_REMOVABLE,
    KEY_PROJECT,
    KEY_TYPE,
    key_relative_path,
    read_key_file,
    token_sha256,
)


def update_env(path, values):
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    target_keys = set(values)
    output = []
    seen = set()

    for line in lines:
        stripped = line.strip()

        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()

            if key in target_keys:
                output.append(f"{key}={values[key]}")
                seen.add(key)
                continue

        output.append(line)

    for key, value in values.items():
        if key not in seen:
            output.append(f"{key}={value}")

    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def removable_drives():
    if not hasattr(ctypes, "windll"):
        return []

    get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    result = []

    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:\\")
        try:
            if root.exists() and get_drive_type(str(root)) == DRIVE_REMOVABLE:
                result.append(root)
        except OSError:
            continue

    return result


def resolve_drive(explicit_drive):
    if explicit_drive:
        value = explicit_drive.rstrip("\\/")

        if len(value) == 1:
            value += ":"

        root = Path(value + "\\")

        if not root.exists():
            raise CommandError(f"Drive not found: {root}")

        return root

    drives = removable_drives()

    if not drives:
        raise CommandError(
            "No removable USB drive detected. Insert the KRTC USB Key and retry."
        )

    if len(drives) > 1:
        labels = ", ".join(str(item) for item in drives)
        raise CommandError(
            "Multiple removable USB drives detected: "
            f"{labels}. Retry with --drive E: (or the intended drive)."
        )

    return drives[0]


class Command(BaseCommand):
    help = (
        "Create or register a portable KRTC Skynet Master USB Key. "
        "If an existing valid key is present, its token is reused and trusted "
        "by this host instead of being overwritten."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--drive",
            required=False,
            help="Optional removable drive root, e.g. E:. "
                 "If omitted, a single removable USB is auto-detected.",
        )

    def handle(self, *args, **options):
        root = resolve_drive(options.get("drive"))
        rel = key_relative_path()
        key_path = root / rel
        key_path.parent.mkdir(parents=True, exist_ok=True)

        existing = read_key_file(key_path) if key_path.exists() else None

        if existing:
            payload = existing
            created = False
            self.stdout.write(
                self.style.WARNING(
                    f"Existing KRTC Master USB Key detected: {key_path}"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    "Existing token will be reused; the USB Key will not be overwritten."
                )
            )
        else:
            token = secrets.token_urlsafe(48)

            payload = {
                "type": KEY_TYPE,
                "project": KEY_PROJECT,
                "key_id": "SKYNET-MASTER-01",
                "scope": "ALL_TRUSTED_HOSTS",
                "token": token,
            }

            key_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            created = True

        digest = token_sha256(str(payload["token"]))

        env_path = Path(settings.BASE_DIR) / ".env"

        update_env(
            env_path,
            {
                "KRTC_SUPERUSER_USB_REQUIRED": "True",
                "KRTC_SUPERUSER_USB_TOKEN_SHA256": digest,
                "KRTC_SUPERUSER_USB_KEY_RELATIVE_PATH":
                    r"KRTC_SUPERUSER_KEY\krtc_superuser.key",
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created KRTC Skynet Master USB Key: {key_path}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Registered existing KRTC Skynet Master USB Key on this host."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Host trust configuration updated: {env_path}"
            )
        )

        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "Restart Django so the updated .env USB settings take effect."
            )
        )
