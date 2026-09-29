from django.core.management.base import BaseCommand, CommandError

from apps.notifications.models import SpeakerDevice


VERIFIED_SPEAKERS = {
    "192.168.6.120": "admin",
    "192.168.6.121": "admin",
    "192.168.6.122": "admin",
    "192.168.6.123": "admin",
}


class Command(BaseCommand):
    help = "Preview or apply the SIP URIs used by the verified four-speaker package."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the verified SIP user/URI values to the database.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        matched = 0

        for ip_address, sip_user in VERIFIED_SPEAKERS.items():
            speakers = SpeakerDevice.objects.filter(ip_address=ip_address)
            if not speakers.exists():
                self.stdout.write(self.style.WARNING(f"Not found: {ip_address}"))
                continue

            for speaker in speakers:
                matched += 1
                uri = f"sip:{sip_user}@{ip_address}:5060"
                action = "APPLY" if apply_changes else "DRY RUN"
                self.stdout.write(
                    f"[{action}] {speaker.speaker_code}: {speaker.sip_uri or '(empty)'} -> {uri}"
                )
                if apply_changes:
                    speaker.protocol = SpeakerDevice.PROTOCOL_SIP
                    speaker.port = 5060
                    speaker.username = sip_user
                    speaker.sip_uri = uri
                    speaker.save(
                        update_fields=["protocol", "port", "username", "sip_uri", "updated_at"]
                    )

        if matched == 0:
            raise CommandError("No verified Speaker IP addresses were found in the database.")

        if apply_changes:
            self.stdout.write(self.style.SUCCESS(f"Updated {matched} Speaker record(s)."))
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run only. Re-run with --apply after confirming the verified SIP account is admin."
                )
            )
