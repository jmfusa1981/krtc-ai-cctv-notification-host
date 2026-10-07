import json

from django.core.management.base import BaseCommand

from apps.cameras.monitor_diagnostics import collect_monitor_media_diagnostics


class Command(BaseCommand):
    help = "診斷Monitor的MediaMTX、WebRTC reader與bridge程序狀態。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="以JSON輸出診斷結果。",
        )

    def handle(self, *args, **options):
        result = collect_monitor_media_diagnostics()
        if options["as_json"]:
            self.stdout.write(
                json.dumps(result, ensure_ascii=False, indent=2)
            )
            return

        self.stdout.write(f"monitor_media_mode={result['monitor_media_mode']}")
        self.stdout.write(f"active_profile={result['active_profile']}")
        self.stdout.write(
            "profile_transition_state="
            f"{result['profile_transition_state']}"
        )
        self.stdout.write(
            "profile_transition_from="
            f"{result['profile_transition_from']}"
        )
        self.stdout.write(
            "profile_transition_to="
            f"{result['profile_transition_to']}"
        )
        self.stdout.write(
            "profile_transition_started_at="
            f"{result['profile_transition_started_at']}"
        )
        self.stdout.write(
            "profile_transition_camera_count="
            f"{result['profile_transition_camera_count']}"
        )
        self.stdout.write(f"mediamtx_reachable={result['mediamtx_reachable']}")
        self.stdout.write(f"fallback_enabled={result['fallback_enabled']}")
        self.stdout.write(f"path_count={result['path_count']}")
        self.stdout.write(f"ready_path_count={result['ready_path_count']}")
        self.stdout.write(
            f"webrtc_session_count={result['webrtc_session_count']}"
        )
        self.stdout.write(
            f"active_reader_count={result['active_reader_count']}"
        )
        self.stdout.write(
            "active_visible_camera_count="
            f"{result['active_visible_camera_count']}"
        )
        self.stdout.write(
            "ffmpeg_bridge_process_count="
            f"{result['ffmpeg_bridge_process_count']}"
        )
        self.stdout.write(
            "transcoding_count="
            f"{result['transcoding_count']}"
        )
        for bridge in result["bridges"]:
            self.stdout.write(
                "bridge camera={camera_code} source_codec={source_codec} "
                "requested_profile={requested_profile} "
                "requested={requested_width}x{requested_height}@{requested_fps} "
                "actual_bridge_mode={actual_bridge_mode} "
                "actual_output={actual_output} state={state} pid={process_id} "
                "exit={exit_code} "
                "last_error={last_error}".format(
                    **bridge
                )
            )
        for item in result["paths"]:
            self.stdout.write(
                "camera={camera_code} path={path} ready={ready} "
                "readers={reader_count} inbound={inbound_bytes} "
                "outbound={outbound_bytes} source_codec={source_codec} "
                "bridge_mode={actual_bridge_mode} bridge_state={bridge_state} "
                "profile={profile} requested={requested_width}x{requested_height} "
                "fps={requested_fps} actual_output={actual_output} "
                "active={active_path} next={next_path} "
                "transition={transition_state}".format(
                    **item
                )
            )
        if result["error"]:
            self.stdout.write(f"error={result['error']}")
