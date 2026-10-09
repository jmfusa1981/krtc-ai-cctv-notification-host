import json

from django.core.management.base import BaseCommand

from apps.station_api.integration.client import encode_json_body
from apps.station_api.integration.config import OccIntegrationConfig
from apps.station_api.integration.heartbeat import HeartbeatSender
from apps.station_api.integration.signing import body_sha256, build_signed_headers
from apps.station_api.integration.state import integration_state


class Command(BaseCommand):
    help = "Safely diagnose PAO to OCC Integration Contract v1.0 configuration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Build and sign one heartbeat without sending it.",
        )

    def handle(self, *args, **options):
        config = OccIntegrationConfig.from_settings()
        report = {
            "configuration": config.public_dict(),
            "state": integration_state(),
        }
        if options["dry_run"]:
            payload = HeartbeatSender(config=config).build_request()
            body = encode_json_body(payload)
            headers = build_signed_headers(
                method="POST",
                path=HeartbeatSender.path,
                body=body,
                station_code=config.station_code,
                host_code=config.host_code,
                shared_secret=config.shared_secret,
            )
            report["dry_run"] = {
                "path": HeartbeatSender.path,
                "request_id": payload["request_id"],
                "body_sha256": body_sha256(body),
                "header_names": sorted(headers),
                "signature_header_present": "X-KRTC-Signature" in headers,
                "sent": False,
            }
        self.stdout.write(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        )
