import ipaddress
import re

from django.core.management.base import BaseCommand, CommandError

from apps.notifications.models import SpeakerDevice


SIP_USER_PATTERN = re.compile(r"^[^@:\s]+$")


class Command(BaseCommand):
    help = (
        "以顯式部署參數預覽或更新一筆既有 Speaker SIP 設定；"
        "預設只做 dry run。"
    )

    def add_arguments(self, parser):
        parser.add_argument("--speaker-code", required=True)
        parser.add_argument("--speaker-ip", required=True)
        parser.add_argument("--sip-user", required=True)
        parser.add_argument("--sip-port", type=int, default=5060)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="寫入資料庫；未提供時只顯示差異。",
        )
        parser.add_argument(
            "--confirm-speaker",
            help="寫入時必須與 --speaker-code 完全相同。",
        )

    def handle(self, *args, **options):
        speaker_code = options["speaker_code"].strip().upper()
        speaker_ip = self._validate_ipv4(options["speaker_ip"])
        sip_user = options["sip_user"].strip()
        sip_port = options["sip_port"]

        if not SIP_USER_PATTERN.fullmatch(sip_user):
            raise CommandError("--sip-user contains invalid SIP URI characters.")
        if not 1 <= sip_port <= 65535:
            raise CommandError("--sip-port must be between 1 and 65535.")

        try:
            speaker = SpeakerDevice.objects.get(speaker_code=speaker_code)
        except SpeakerDevice.DoesNotExist as exc:
            raise CommandError(
                f"SpeakerDevice not found: {speaker_code}."
            ) from exc

        target_uri = f"sip:{sip_user}@{speaker_ip}:{sip_port}"
        self.stdout.write(
            f"[DRY RUN] {speaker.speaker_code}: "
            f"IP {speaker.ip_address} -> {speaker_ip}; "
            f"URI {speaker.resolved_sip_uri or '(empty)'} -> {target_uri}"
        )

        if not options["apply"]:
            self.stdout.write("No database records were changed.")
            return

        if options["confirm_speaker"] != speaker_code:
            raise CommandError(
                "Apply blocked: --confirm-speaker must exactly match "
                "--speaker-code."
            )

        speaker.protocol = SpeakerDevice.PROTOCOL_SIP
        speaker.ip_address = speaker_ip
        speaker.port = sip_port
        speaker.username = sip_user
        speaker.sip_uri = target_uri
        speaker.full_clean()
        speaker.save(
            update_fields=[
                "protocol",
                "ip_address",
                "port",
                "username",
                "sip_uri",
                "updated_at",
            ]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Updated Speaker {speaker.speaker_code}: {target_uri}"
            )
        )

    @staticmethod
    def _validate_ipv4(value):
        try:
            address = ipaddress.ip_address(str(value).strip())
        except ValueError as exc:
            raise CommandError("--speaker-ip must be a valid IPv4 address.") from exc
        if address.version != 4:
            raise CommandError("--speaker-ip must be an IPv4 address.")
        return str(address)
