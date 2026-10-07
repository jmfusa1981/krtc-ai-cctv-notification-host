import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.cameras.mediamtx import camera_path_name, get_camera_playback
from apps.cameras.models import Camera
from apps.cameras.monitor_diagnostics import (
    _load_bridge_statuses,
    collect_mediamtx_path_readiness,
    collect_monitor_media_diagnostics,
)
from apps.cameras.monitor_transitions import (
    acknowledge_monitor_transition,
    load_monitor_transition_state,
)


class MediaMTXPlaybackTests(SimpleTestCase):
    def camera(self, code="CAM-004", **overrides):
        values = {
            "camera_code": code,
            "is_active": True,
            "is_online": True,
            "status": "online",
        }
        values.update(overrides)
        return Camera(**values)

    @override_settings(
        KRTC_MEDIAMTX_ENABLED=True,
        KRTC_MONITOR_MEDIA_MODE="mediamtx",
        KRTC_MEDIAMTX_WEBRTC_BASE_URL="http://192.168.6.25:8889",
        KRTC_MEDIAMTX_PHASE1_CAMERA_CODES=(
            "CAM-001",
            "CAM-002",
            "CAM-003",
            "CAM-004",
        ),
    )
    def test_four_camera_paths_are_distinct_and_credential_free(self):
        playbacks = [
            get_camera_playback(self.camera(f"CAM-{index:03d}"))
            for index in range(1, 5)
        ]

        self.assertEqual(
            [playback.path_name for playback in playbacks],
            ["cam001", "cam002", "cam003", "cam004"],
        )
        self.assertEqual(len({playback.player_url for playback in playbacks}), 4)
        for playback in playbacks:
            self.assertTrue(playback.available)
            self.assertNotIn("@", playback.player_url)
            self.assertNotIn("rtsp", playback.player_url)

    def test_camera_path_rejects_unsafe_code(self):
        self.assertEqual(camera_path_name("CAM-004"), "cam004")
        self.assertEqual(camera_path_name("../CAM-004"), "")

    @override_settings(KRTC_MEDIAMTX_ENABLED=False)
    def test_disabled_configuration_is_unavailable(self):
        self.assertEqual(get_camera_playback(self.camera()).reason, "disabled")

    @override_settings(
        KRTC_MEDIAMTX_ENABLED=True,
        KRTC_MEDIAMTX_WEBRTC_BASE_URL="",
        KRTC_MEDIAMTX_PHASE1_CAMERA_CODES=("CAM-004",),
    )
    def test_missing_base_url_is_unavailable(self):
        playback = get_camera_playback(self.camera())
        self.assertFalse(playback.available)
        self.assertEqual(playback.reason, "invalid_configuration")

    @override_settings(
        KRTC_MEDIAMTX_ENABLED=True,
        KRTC_MEDIAMTX_WEBRTC_BASE_URL="http://operator:secret@localhost:8889",
        KRTC_MEDIAMTX_PHASE1_CAMERA_CODES=("CAM-004",),
    )
    def test_base_url_with_credentials_is_rejected(self):
        playback = get_camera_playback(self.camera())
        self.assertFalse(playback.available)
        self.assertEqual(playback.reason, "invalid_configuration")

    @override_settings(
        KRTC_MEDIAMTX_ENABLED=True,
        KRTC_MEDIAMTX_WEBRTC_BASE_URL="http://localhost:8889",
        KRTC_MEDIAMTX_PHASE1_CAMERA_CODES=("CAM-004",),
    )
    def test_offline_or_inactive_camera_is_unavailable(self):
        offline = get_camera_playback(
            self.camera(status="offline", is_online=False)
        )
        inactive = get_camera_playback(self.camera(is_active=False))
        self.assertEqual(offline.reason, "offline")
        self.assertEqual(inactive.reason, "inactive")


@override_settings(
    KRTC_MEDIAMTX_ENABLED=True,
    KRTC_MONITOR_MEDIA_MODE="mediamtx",
    KRTC_MEDIAMTX_WEBRTC_BASE_URL="http://192.168.6.25:8889",
    KRTC_MEDIAMTX_PHASE1_CAMERA_CODES=(
        "CAM-001",
        "CAM-002",
        "CAM-003",
        "CAM-004",
    ),
)
class MediaMTXEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mediamtx-user", password="test-pass")
        self.camera = Camera.objects.create(
            camera_code="CAM-004",
            name="Lab Camera",
            area="Lab",
            rtsp_url="rtsp://root:root@192.168.6.92/cam1/h264",
            username="root",
            password="root",
            status="online",
            is_online=True,
            is_active=True,
        )

    def test_playback_endpoint_requires_login(self):
        response = self.client.get(
            reverse("cameras:camera_playback_api", args=[self.camera.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_playback_endpoint_returns_safe_webrtc_url(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("cameras:camera_playback_api", args=[self.camera.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["kind"], "mediamtx_webrtc")
        self.assertIn("/cam004", response.json()["url"])
        self.assertNotIn("root", response.content.decode("utf-8"))
        self.assertNotIn("192.168.6.92", response.content.decode("utf-8"))

    def test_media_status_endpoint_requires_login(self):
        response = self.client.get(reverse("cameras:camera_media_status_api"))

        self.assertEqual(response.status_code, 302)

    def test_media_profile_endpoint_requires_login(self):
        response = self.client.post(
            reverse("cameras:camera_media_profile_api"),
            {"profile": "grid4"},
        )

        self.assertEqual(response.status_code, 302)

    def test_media_transition_ack_requires_login_and_csrf(self):
        transition_url = reverse("cameras:camera_media_transition_ack_api")
        anonymous_response = self.client.post(
            transition_url,
            {
                "transition_id": "transition-001",
                "camera_codes": "CAM-001",
            },
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        csrf_response = csrf_client.post(
            transition_url,
            {
                "transition_id": "transition-001",
                "camera_codes": "CAM-001",
            },
        )

        self.assertEqual(anonymous_response.status_code, 302)
        self.assertEqual(csrf_response.status_code, 403)

    def test_media_profile_endpoint_validates_and_writes_safe_state(self):
        self.client.force_login(self.user)
        with TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "profile.json"
            with override_settings(
                KRTC_MONITOR_PROFILE_STATE_PATH=state_path
            ):
                response = self.client.post(
                    reverse("cameras:camera_media_profile_api"),
                    {"profile": "grid16"},
                )
                invalid_response = self.client.post(
                    reverse("cameras:camera_media_profile_api"),
                    {"profile": "unsafe"},
                )

            payload = json.loads(state_path.read_text(encoding="ascii"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["profile"], "grid16")
        self.assertRegex(
            payload["request_id"],
            r"^[0-9a-f]{8}-[0-9a-f-]{27}$",
        )
        self.assertEqual(invalid_response.status_code, 400)

    def test_transition_ack_requires_complete_preloaded_camera_set(self):
        self.client.force_login(self.user)
        with TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "transition.json"
            ack_path = Path(temporary_directory) / "ack.json"
            state_path.write_text(
                json.dumps(
                    {
                        "TransitionId": "transition-001",
                        "ProfileTransitionState": "preloading",
                        "FromProfile": "grid4",
                        "ToProfile": "grid9",
                        "StartedAt": "2026-10-07T01:02:03Z",
                        "CameraCount": 2,
                        "Cameras": [
                            {
                                "CameraCode": "CAM-001",
                                "ActivePath": "cam001",
                                "NextPath": "cam001_b",
                                "TransitionState": "preloading",
                            },
                            {
                                "CameraCode": "CAM-003",
                                "ActivePath": "cam003",
                                "NextPath": "cam003_b",
                                "TransitionState": "preloading",
                            },
                        ],
                    }
                ),
                encoding="ascii",
            )
            with override_settings(
                KRTC_MONITOR_TRANSITION_STATE_PATH=state_path,
                KRTC_MONITOR_TRANSITION_ACK_PATH=ack_path,
            ):
                transition = load_monitor_transition_state()
                incomplete = acknowledge_monitor_transition(
                    "transition-001",
                    ["CAM-001"],
                )
                response = self.client.post(
                    reverse("cameras:camera_media_transition_ack_api"),
                    {
                        "transition_id": "transition-001",
                        "camera_codes": "CAM-001,CAM-003",
                    },
                )

            ack_payload = json.loads(ack_path.read_text(encoding="ascii"))

        self.assertEqual(transition["profile_transition_state"], "preloading")
        self.assertEqual(transition["profile_transition_camera_count"], 2)
        self.assertFalse(incomplete)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ack_payload["CameraCodes"], ["CAM-001", "CAM-003"])

    @patch("apps.cameras.views.collect_mediamtx_path_readiness")
    def test_media_status_endpoint_returns_safe_path_readiness(self, collect):
        collect.return_value = {
            "reachable": True,
            "paths": {"CAM-001": True, "CAM-004": False},
            "path_details": {
                "CAM-001": {
                    "camera": "CAM-001",
                    "path": "cam001",
                    "ready": True,
                    "reader_count": 1,
                    "webrtc_reader_count": 1,
                    "transition_state": "idle",
                },
            },
            "transition": {
                "profile_transition_state": "idle",
                "cameras": {},
            },
            "error": "",
        }
        self.client.force_login(self.user)

        response = self.client.get(reverse("cameras:camera_media_status_api"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["paths"],
            {"CAM-001": True, "CAM-004": False},
        )
        self.assertEqual(
            response.json()["path_details"]["CAM-001"]["reader_count"],
            1,
        )
        content = response.content.decode("utf-8")
        self.assertNotIn("root", content)
        self.assertNotIn("192.168.6.92", content)

    def test_monitor_embeds_safe_player_without_camera_source(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard:monitor"))
        content = response.content.decode("utf-8")

        self.assertContains(response, "data-mediamtx-player")
        self.assertContains(response, "http://192.168.6.25:8889/cam004")
        self.assertNotIn("root:root", content)
        self.assertNotIn("192.168.6.92", content)

    def test_monitor_renders_four_independent_webrtc_players(self):
        for index in range(1, 4):
            Camera.objects.create(
                camera_code=f"CAM-{index:03d}",
                name=f"Lab Camera {index}",
                area="Lab",
                rtsp_url=f"rtsp://private-{index}/cam1/h264",
                username="private-user",
                password="private-password",
                status="online",
                is_online=True,
                is_active=True,
            )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:monitor"))
        content = response.content.decode("utf-8")

        self.assertEqual(content.count("data-mediamtx-player"), 8)
        for index in range(1, 5):
            self.assertIn(f"/cam{index:03d}?", content)
        self.assertNotIn("private-password", content)

    def test_offline_camera_uses_isolated_fallback(self):
        Camera.objects.create(
            camera_code="CAM-002",
            name="Offline Camera",
            area="Lab",
            rtsp_url="rtsp://private-offline/cam1/h264",
            username="private-user",
            password="private-password",
            status="offline",
            is_online=False,
            is_active=True,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:monitor"))
        content = response.content.decode("utf-8")

        self.assertEqual(content.count("data-mediamtx-player"), 2)
        self.assertIn('data-stream-url="/api/cameras/2/stream/"', content)
        self.assertNotIn("/cam002?controls", content)
        self.assertNotIn("private-password", content)


class MediaMTXFrontendContractTests(SimpleTestCase):
    def test_publisher_configuration_and_browser_cleanup_contract(self):
        project_root = Path(settings.BASE_DIR)
        config = (project_root / "config/mediamtx.lab.yml").read_text(
            encoding="utf-8"
        )
        script = (project_root / "static/js/monitor.js").read_text(
            encoding="utf-8"
        )
        shared_player = (
            project_root / "static/js/mediamtx_player.js"
        ).read_text(encoding="utf-8")

        for path_name in ("cam001", "cam002", "cam003", "cam004"):
            self.assertIn(f"  {path_name}:", config)
        self.assertEqual(config.count("source: publisher"), 6)
        self.assertIn("  cam001_b:", config)
        self.assertIn("  cam003_b:", config)
        self.assertNotIn("source: rtsp://", config)
        self.assertNotIn("root:root", config)
        self.assertIn("function releaseWebRTCPlayer", script)
        self.assertIn("KRTCMediaPlayer.releaseWebRTC(player)", script)
        self.assertIn('player.src = "about:blank"', shared_player)
        self.assertIn("function scheduleWebRTCReconnect", script)
        self.assertIn('window.addEventListener("pagehide", cleanupMonitorPage', script)

    def test_camera_bridge_resolves_h264_copy_and_h265_transcode_profiles(self):
        bridge = (
            Path(settings.BASE_DIR)
            / "tools/mediamtx/start_camera_bridge_lab.ps1"
        ).read_text(encoding="utf-8")
        resolver = (
            Path(settings.BASE_DIR)
            / "tools/mediamtx/camera_bridge_codec.ps1"
        ).read_text(encoding="utf-8")

        self.assertGreaterEqual(bridge.count('"-rtsp_transport", "tcp"'), 2)
        self.assertRegex(bridge, r'"-map",\s*"0:v:0"')
        self.assertRegex(resolver, r'"-c:v",\s*"copy"')
        self.assertRegex(resolver, r'"-c:v",\s*"libx264"')
        self.assertRegex(resolver, r'"-preset",\s*"veryfast"')
        self.assertRegex(resolver, r'"-tune",\s*"zerolatency"')
        self.assertRegex(resolver, r'"-pix_fmt",\s*"yuv420p"')
        self.assertIn("force_original_aspect_ratio=decrease", resolver)
        self.assertIn("pad={0}:{1}:(ow-iw)/2:(oh-ih)/2", resolver)
        self.assertIn("fps={2}", resolver)
        self.assertRegex(resolver, r'"-fps_mode",\s*"cfr"')
        self.assertNotRegex(resolver, r'"-r",\s*"?30"?')
        self.assertIn('"-an"', bridge)
        self.assertIn('"-dn"', bridge)
        self.assertNotIn("libx265", resolver)

    def test_lab_profiles_use_native_h264_copy_for_all_four_cameras(self):
        profiles = (
            Path(settings.BASE_DIR)
            / "tools/mediamtx/camera_bridge_profiles.lab.psd1"
        ).read_text(encoding="utf-8")

        for camera_code in ("CAM-001", "CAM-002", "CAM-003", "CAM-004"):
            self.assertRegex(
                profiles,
                rf'"{camera_code}"\s*=\s*@\{{[^}}]*SourceCodec\s*=\s*"H264"',
            )
        self.assertNotIn('SourceCodec = "H265"', profiles)

    def test_monitor_media_contract_freezes_copy_first_policy(self):
        contract = (
            Path(settings.BASE_DIR)
            / "docs/KRTC_V6_8_Monitor_Media_Contract.md"
        ).read_text(encoding="utf-8")

        for section in (
            "## 1. System Responsibility",
            "## 2. Primary Media Path",
            "## 3. Codec Policy",
            "## 4. Display Canvas Policy",
            "## 5. Layout Policy",
            "## 6. Adaptive Profile Semantic Change",
            "## 7. Stream Selection Policy",
            "## 8. Camera Configuration Boundary",
            "## 9. Resource Stability Policy",
            "## 10. Fallback Policy",
            "## 11. Media Freeze Acceptance",
        ):
            self.assertIn(section, contract)
        self.assertIn("Camera Native H264", contract)
        self.assertIn("actual_output=source-copy", contract)
        self.assertIn("transcoding_count=0", contract)
        self.assertIn("30–60分鐘soak test移入Full Integration Stress", contract)

    def test_source_path_remains_documented_phase2_boundary(self):
        project_root = Path(settings.BASE_DIR)
        bridge = (
            project_root / "tools/mediamtx/start_camera_bridge_lab.ps1"
        ).read_text(encoding="utf-8")
        profiles = (
            project_root / "tools/mediamtx/camera_bridge_profiles.lab.psd1"
        ).read_text(encoding="utf-8")
        contract = (
            project_root / "docs/KRTC_V6_8_Monitor_Media_Contract.md"
        ).read_text(encoding="utf-8")

        self.assertIn("@$cameraHost/cam1/h264", bridge)
        self.assertNotIn("SourcePath", profiles)
        self.assertIn("Phase 2", contract)
        self.assertIn("`SourcePath`", contract)

    def test_camera_bridge_has_safe_cam004_destination_and_invocation(self):
        bridge = (
            Path(settings.BASE_DIR)
            / "tools/mediamtx/start_camera_bridge_lab.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '$destinationUrl = "rtsp://127.0.0.1:8554/$pathName"',
            bridge,
        )
        self.assertIn(
            "$pathName = [string]$cameraProfile.Path",
            bridge,
        )
        self.assertIn("& $FfmpegPath @ffmpegArguments", bridge)
        self.assertNotIn("root:root", bridge)
        self.assertNotIn("Invoke-Expression", bridge)
        self.assertNotRegex(
            bridge,
            r"Write-Host[^\r\n]*(cameraPassword|cameraUsername|sourceUrl)",
        )

    def test_all_grid_layouts_activate_webrtc_and_hidden_slots_release(self):
        project_root = Path(settings.BASE_DIR)
        script = (project_root / "static/js/monitor.js").read_text(
            encoding="utf-8"
        )
        template = (
            project_root / "templates/dashboard/monitor.html"
        ).read_text(encoding="utf-8")

        self.assertIn("function syncVisibleWebRTCPlayers()", script)
        self.assertIn(
            'monitorMediaMode !== "mediamtx"',
            script,
        )
        self.assertRegex(
            script,
            r"if \(slot\.hidden\) \{\s*scheduleCameraStreamRelease\(card\);",
        )
        self.assertRegex(
            script,
            r"cancelScheduledStreamRelease\(card\);\s*"
            r"if \(!monitorMediaStatus\)",
        )
        self.assertRegex(
            script,
            r"if \(isCameraMediaReady\(card\)\) \{\s*"
            r"activateWebRTCPlayer\(card, player\);\s*"
            r"\} else \{\s*activateCameraFallback\(card, player\);",
        )
        self.assertRegex(
            script,
            r"monitorGrid\.hidden = false;\s*"
            r"syncVisibleWebRTCPlayers\(\);\s*"
            r"syncVisibleCameraStreams\(\);",
        )
        self.assertIn("v=20261007-dashboard-unification", template)
        self.assertIn("js/mediamtx_player.js", template)
        self.assertIn('data-media-mode="{{ monitor_media_mode', template)
        self.assertIn("data-media-status-url=", template)
        self.assertIn("function loadMonitorMediaStatus(forceRefresh)", script)
        self.assertIn('credentials: "same-origin"', script)
        self.assertIn("if (isCameraMediaReady(card))", script)
        self.assertIn("data-media-profile-url=", template)
        self.assertIn("monitorProfileLayoutMap", template)
        self.assertIn("function scheduleMonitorProfileSwitch(gridSize)", script)
        self.assertIn("MONITOR_PROFILE_SWITCH_DEBOUNCE_MS = 1500", script)

    def test_seamless_transition_uses_make_before_break_and_double_buffer(self):
        project_root = Path(settings.BASE_DIR)
        manager = (
            project_root / "tools/mediamtx/start_camera_bridges_lab.ps1"
        ).read_text(encoding="utf-8")
        script = (project_root / "static/js/monitor.js").read_text(
            encoding="utf-8"
        )
        template = (
            project_root / "templates/dashboard/monitor.html"
        ).read_text(encoding="utf-8")

        self.assertIn("function Invoke-ProfileTransition", manager)
        self.assertIn("Test-MediaPathReady", manager)
        self.assertIn("Test-TransitionAcknowledged", manager)
        self.assertIn('Reason "layout_change_cleanup"', manager)
        self.assertIn('Reason "layout_change_timeout"', manager)
        self.assertIn("transition_timeout_current_stream_retained", manager)
        self.assertRegex(
            manager,
            r'Start-BridgeProcess[\s\S]+Test-MediaPathReady[\s\S]+'
            r'Test-TransitionAcknowledged[\s\S]+Stop-BridgeProcess',
        )
        self.assertIn('BridgeMode -ne "transcode"', manager)
        self.assertNotRegex(
            manager,
            r'RestartCount\s*\+=\s*1[\s\S]{0,300}layout_change',
        )
        self.assertEqual(template.count('data-player-role="current"'), 1)
        self.assertEqual(template.count('data-player-role="next"'), 1)
        self.assertIn("function prepareMonitorProfileTransition", script)
        self.assertIn("function acknowledgePreparedTransition", script)
        self.assertIn("resetNextWebRTCPlayers();", script)
        self.assertIn("item.camera.next_reader_count", script)
        self.assertRegex(
            script,
            r'currentPlayer\.dataset\.playerRole = "next";[\s\S]+'
            r'nextPlayer\.dataset\.playerRole = "current";[\s\S]+'
            r'fetch\(mediaTransitionAckUrl',
        )
        self.assertIn("MONITOR_PROFILE_TRANSITION_POLL_MS = 500", script)
        self.assertIn("data-media-transition-ack-url=", template)

    def test_grace_fallback_and_rapid_layout_debounce_are_preserved(self):
        script = (
            Path(settings.BASE_DIR) / "static/js/monitor.js"
        ).read_text(encoding="utf-8")

        self.assertIn("STREAM_IDLE_RELEASE_MS = 15000", script)
        self.assertIn("activateCameraFallback(card, player);", script)
        self.assertIn("MONITOR_PROFILE_SWITCH_DEBOUNCE_MS = 1500", script)
        self.assertIn("window.clearTimeout(monitorProfileSwitchTimer)", script)
        self.assertIn("replaced_by_newer_profile_request", (
            Path(settings.BASE_DIR)
            / "tools/mediamtx/start_camera_bridges_lab.ps1"
        ).read_text(encoding="utf-8"))

    def test_webrtc_load_clears_overlay_and_sets_online_state(self):
        script = (
            Path(settings.BASE_DIR) / "static/js/monitor.js"
        ).read_text(encoding="utf-8")

        self.assertIn("function markWebRTCPlayerLoaded(player)", script)
        self.assertIn('setCardState(card, "loaded");', script)
        self.assertIn('setStatusBadge(card, "ONLINE", "online");', script)
        self.assertIn("hideOverlay(card);", script)
        self.assertRegex(
            script,
            r'player\.addEventListener\("load", function \(\) \{\s*'
            r"markWebRTCPlayerLoaded\(player\);",
        )

    def test_mediamtx_powershell_scripts_are_ascii_only(self):
        tools_root = Path(settings.BASE_DIR) / "tools/mediamtx"

        for script_name in (
            "camera_bridge_codec.ps1",
            "camera_bridge_profiles.lab.psd1",
            "start_mediamtx_lab.ps1",
            "start_camera_bridge_lab.ps1",
            "start_camera_bridges_lab.ps1",
        ):
            script = (tools_root / script_name).read_text(encoding="utf-8")
            self.assertTrue(script.isascii(), script_name)

    def test_unified_grid_aspect_ratio_and_legacy_mosaic_fallback(self):
        project_root = Path(settings.BASE_DIR)
        stylesheet = (project_root / "static/css/monitor.css").read_text(
            encoding="utf-8"
        )
        script = (project_root / "static/js/monitor.js").read_text(
            encoding="utf-8"
        )
        template = (
            project_root / "templates/dashboard/monitor.html"
        ).read_text(encoding="utf-8")

        self.assertIn("aspect-ratio: 16 / 9", stylesheet)
        self.assertIn("object-fit: contain", stylesheet)
        self.assertIn("flex: 0 0 46px", stylesheet)
        self.assertIn('monitorMediaMode !== "mediamtx"', script)
        self.assertIn("activateMosaicStream();", script)
        self.assertIn("data-media-fallback", template)

    def test_reconnect_uses_backoff_and_controlled_fallback(self):
        script = (
            Path(settings.BASE_DIR) / "static/js/monitor.js"
        ).read_text(encoding="utf-8")

        self.assertIn("WEBRTC_RECONNECT_BASE_MS = 2000", script)
        self.assertIn("WEBRTC_RECONNECT_MAX_MS = 15000", script)
        self.assertIn("WEBRTC_MAX_RETRIES = 3", script)
        self.assertIn("STREAM_IDLE_RELEASE_MS = 15000", script)
        self.assertIn("activateCameraFallback(card, player);", script)
        self.assertIn("cancelScheduledStreamRelease(card);", script)
        self.assertIn("MEDIA_STATUS_REFRESH_MS = 5000", script)
        self.assertIn("function refreshMonitorMediaStatus()", script)
        self.assertIn("loadMonitorMediaStatus(true)", script)
        self.assertIn(
            'player.hidden = player.dataset.fallbackActive === "true";',
            script,
        )
        self.assertIn(
            "window.clearInterval(monitorMediaRefreshTimer)",
            script,
        )

    def test_bridge_manager_starts_isolated_camera_processes(self):
        tools_root = Path(settings.BASE_DIR) / "tools/mediamtx"
        manager = (
            tools_root / "start_camera_bridges_lab.ps1"
        ).read_text(encoding="utf-8")
        profiles = (
            tools_root / "camera_bridge_profiles.lab.psd1"
        ).read_text(encoding="utf-8")

        for camera_code, path_name in (
            ("CAM-001", "cam001"),
            ("CAM-002", "cam002"),
            ("CAM-003", "cam003"),
            ("CAM-004", "cam004"),
        ):
            self.assertIn(f'"{camera_code}"', profiles)
            self.assertIn(f'Path = "{path_name}"', profiles)
        self.assertIn('$requestedCodes -contains "ALL"', manager)
        self.assertIn("Import-PowerShellDataFile", manager)
        self.assertIn('"-SourceCodec", $Bridge.SourceCodec', manager)
        self.assertIn("Resolve-BridgeProfile", manager)
        self.assertIn("Start-Process", manager)
        self.assertIn("-PassThru", manager)
        self.assertIn("PID={4}", manager)
        self.assertIn("taskkill.exe /PID", manager)
        self.assertIn("[int]$MaxRestarts = 3", manager)
        self.assertIn("[int]$RestartBaseSeconds = 2", manager)
        self.assertIn("[math]::Pow", manager)
        self.assertIn("Bridge restart limit reached", manager)
        self.assertIn("Reason=layout_change", manager)
        self.assertRegex(
            manager,
            r'BridgeMode -ne "transcode"[\s\S]*Start-BridgeProcess',
        )

    def test_adaptive_profile_table_and_layout_mapping(self):
        profile_config = json.loads(
            (
                Path(settings.BASE_DIR) / "config/monitor_profiles.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(
            profile_config["layout_map"],
            {"1": "single", "4": "grid4", "9": "grid9", "16": "grid16"},
        )
        self.assertEqual(
            profile_config["profiles"],
            {
                "single": {"width": 1920, "height": 1080, "fps": 30},
                "grid4": {"width": 1280, "height": 720, "fps": 15},
                "grid9": {"width": 640, "height": 360, "fps": 12},
                "grid16": {"width": 480, "height": 270, "fps": 10},
            },
        )

    def test_bridge_status_preserves_exit_code_and_safe_last_error(self):
        bridge = (
            Path(settings.BASE_DIR)
            / "tools/mediamtx/start_camera_bridge_lab.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn('$statusRecord["ExitCode"] = $exitCode', bridge)
        self.assertIn('$statusRecord["LastError"] = $lastError', bridge)
        self.assertIn("ffmpeg_exit_code_$exitCode", bridge)
        self.assertIn("ProcessStartedAt", bridge)


@override_settings(
    KRTC_MEDIAMTX_ENABLED=True,
    KRTC_MONITOR_MEDIA_MODE="mediamtx",
    KRTC_MONITOR_MOSAIC_FALLBACK=True,
    KRTC_MEDIAMTX_API_BASE_URL="http://127.0.0.1:9997",
    KRTC_MEDIAMTX_PHASE1_CAMERA_CODES=(
        "CAM-001",
        "CAM-002",
        "CAM-003",
        "CAM-004",
    ),
)
class MonitorMediaDiagnosticTests(SimpleTestCase):
    def test_stale_pid_is_not_reported_as_running(self):
        with TemporaryDirectory() as temporary_directory:
            status_path = Path(temporary_directory) / "CAM-001.json"
            status_path.write_text(
                json.dumps(
                    {
                        "CameraCode": "CAM-001",
                        "SourceCodec": "H265",
                        "BridgeMode": "transcode",
                        "ProcessId": 1234,
                        "ProcessStartedAt": "2026-10-07T00:00:00+00:00",
                        "State": "running",
                        "ExitCode": None,
                        "LastError": "",
                        "TranscodeFps": 30,
                    }
                ),
                encoding="ascii",
            )
            with override_settings(
                KRTC_MEDIAMTX_BRIDGE_STATUS_DIR=temporary_directory
            ):
                with patch(
                    "apps.cameras.monitor_diagnostics."
                    "_process_identity_matches",
                    return_value=False,
                ):
                    statuses = _load_bridge_statuses()

        self.assertEqual(statuses[0]["state"], "stopped")
        self.assertEqual(
            statuses[0]["last_error"],
            "stale_process_identity",
        )

    @patch("apps.cameras.monitor_diagnostics._process_memory_bytes", return_value=1024)
    @patch("apps.cameras.monitor_diagnostics._ffmpeg_process_count", return_value=4)
    @patch("apps.cameras.monitor_diagnostics._load_bridge_statuses")
    @patch("apps.cameras.monitor_diagnostics._read_json")
    @patch(
        "apps.cameras.monitor_diagnostics.get_active_monitor_profile",
        return_value="grid4",
    )
    def test_diagnostic_reports_codec_mode_and_transcoding_count(
        self,
        _active_profile,
        read_json,
        load_statuses,
        _ffmpeg_count,
        _memory_bytes,
    ):
        load_statuses.return_value = [
            {
                "camera_code": "CAM-001",
                "source_codec": "H265",
                "bridge_mode": "transcode",
                "state": "running",
                "process_id": 101,
                "output_width": 1280,
                "output_height": 720,
                "output_fps": 15,
            },
            {
                "camera_code": "CAM-002",
                "source_codec": "H264",
                "bridge_mode": "copy",
                "state": "running",
                "process_id": 102,
                "output_width": 1920,
                "output_height": 1080,
                "output_fps": 30,
            },
        ]
        read_json.side_effect = [
            {
                "items": [
                    {"name": "cam001", "ready": True},
                    {"name": "cam002", "ready": True},
                ]
            },
            {"itemCount": 0, "items": []},
        ]

        transition = {
            "transition_id": "transition-001",
            "profile_transition_state": "preloading",
            "profile_transition_from": "single",
            "profile_transition_to": "grid4",
            "profile_transition_started_at": "2026-10-07T01:02:03Z",
            "profile_transition_camera_count": 2,
            "cameras": {
                "CAM-001": {
                    "active_path": "cam001",
                    "next_path": "cam001_b",
                    "transition_state": "preloading",
                },
                "CAM-002": {
                    "active_path": "cam002",
                    "next_path": None,
                    "transition_state": "idle",
                },
            },
            "last_error": "",
        }
        with patch(
            "apps.cameras.monitor_diagnostics.load_monitor_transition_state",
            return_value=transition,
        ):
            result = collect_monitor_media_diagnostics()

        self.assertEqual(result["transcoding_count"], 1)
        self.assertEqual(result["active_profile"], "grid4")
        self.assertEqual(result["bridges"][0]["source_codec"], "H265")
        self.assertEqual(result["bridges"][0]["requested_profile"], "grid4")
        self.assertEqual(result["bridges"][0]["actual_output"], "1280x720@15")
        self.assertEqual(result["bridges"][1]["actual_output"], "source-copy")
        self.assertEqual(result["paths"][0]["bridge_mode"], "transcode")
        self.assertEqual(result["paths"][1]["bridge_mode"], "copy")
        self.assertEqual(result["profile_transition_state"], "preloading")
        self.assertEqual(result["profile_transition_from"], "single")
        self.assertEqual(result["profile_transition_to"], "grid4")
        self.assertEqual(result["profile_transition_camera_count"], 2)
        self.assertEqual(result["paths"][0]["active_path"], "cam001")
        self.assertEqual(result["paths"][0]["next_path"], "cam001_b")

    @patch("apps.cameras.monitor_diagnostics._read_json")
    def test_path_readiness_reports_each_camera_independently(self, read_json):
        read_json.return_value = {
            "items": [
                {
                    "name": "cam001",
                    "ready": True,
                    "readers": [{"type": "webRTCSession"}],
                },
                {
                    "name": "cam001_b",
                    "ready": True,
                    "readers": [{"type": "webRTCSession"}],
                },
                {"name": "cam002", "ready": False},
                {"name": "cam004", "online": True},
            ]
        }
        transition = {
            "transition_id": "transition-001",
            "profile_transition_state": "preloading",
            "profile_transition_from": "grid4",
            "profile_transition_to": "grid9",
            "profile_transition_started_at": "2026-10-07T01:02:03Z",
            "profile_transition_camera_count": 1,
            "cameras": {
                "CAM-001": {
                    "active_path": "cam001",
                    "next_path": "cam001_b",
                    "transition_state": "preloading",
                },
            },
            "last_error": "",
        }

        with patch(
            "apps.cameras.monitor_diagnostics.load_monitor_transition_state",
            return_value=transition,
        ):
            result = collect_mediamtx_path_readiness()

        self.assertTrue(result["reachable"])
        self.assertEqual(
            result["paths"],
            {
                "CAM-001": True,
                "CAM-002": False,
                "CAM-003": False,
                "CAM-004": True,
            },
        )
        camera_transition = result["transition"]["cameras"]["CAM-001"]
        self.assertTrue(camera_transition["next_ready"])
        self.assertEqual(camera_transition["next_reader_count"], 1)
        self.assertIn("/cam001_b?", camera_transition["next_player_url"])
        self.assertEqual(
            result["path_details"]["CAM-001"],
            {
                "camera": "CAM-001",
                "path": "cam001",
                "ready": True,
                "reader_count": 1,
                "webrtc_reader_count": 1,
                "transition_state": "preloading",
            },
        )

    @patch(
        "apps.cameras.monitor_diagnostics._read_json",
        side_effect=OSError("offline"),
    )
    def test_path_readiness_failure_is_safe(self, _read_json):
        result = collect_mediamtx_path_readiness()

        self.assertFalse(result["reachable"])
        self.assertEqual(result["paths"], {})
        self.assertIn("mediamtx_unreachable", result["error"])

    @patch("apps.cameras.monitor_diagnostics._process_memory_bytes", return_value=1024)
    @patch("apps.cameras.monitor_diagnostics._ffmpeg_process_count", return_value=4)
    @patch("apps.cameras.monitor_diagnostics._read_json")
    def test_diagnostic_summarizes_paths_sessions_and_readers(
        self,
        read_json,
        _ffmpeg_count,
        _memory_bytes,
    ):
        read_json.side_effect = [
            {
                "items": [
                    {
                        "name": "cam001",
                        "online": True,
                        "readers": [{"type": "webRTCSession"}],
                        "inboundBytes": 100,
                        "outboundBytes": 80,
                    },
                    {
                        "name": "cam004",
                        "online": True,
                        "readers": [],
                        "inboundBytes": 200,
                        "outboundBytes": 120,
                    },
                ]
            },
            {"itemCount": 1, "items": [{"path": "cam001"}]},
        ]

        result = collect_monitor_media_diagnostics()

        self.assertTrue(result["mediamtx_reachable"])
        self.assertEqual(result["ready_path_count"], 2)
        self.assertEqual(result["webrtc_session_count"], 1)
        self.assertEqual(result["active_reader_count"], 1)
        self.assertEqual(result["active_visible_camera_count"], 1)
        self.assertEqual(result["ffmpeg_bridge_process_count"], 4)
        self.assertEqual(len(result["paths"]), 4)

    @patch("apps.cameras.monitor_diagnostics._process_memory_bytes", return_value=1024)
    @patch("apps.cameras.monitor_diagnostics._ffmpeg_process_count", return_value=0)
    @patch(
        "apps.cameras.monitor_diagnostics._read_json",
        side_effect=OSError("offline"),
    )
    def test_mediamtx_unavailable_is_reported_without_crash(
        self,
        _read_json,
        _ffmpeg_count,
        _memory_bytes,
    ):
        result = collect_monitor_media_diagnostics()

        self.assertFalse(result["mediamtx_reachable"])
        self.assertTrue(result["fallback_enabled"])
        self.assertIn("mediamtx_unreachable", result["error"])

    @patch(
        "apps.cameras.management.commands.diagnose_monitor_media."
        "collect_monitor_media_diagnostics"
    )
    def test_management_command_supports_json(self, collect):
        collect.return_value = {"monitor_media_mode": "mediamtx"}
        output = __import__("io").StringIO()

        call_command("diagnose_monitor_media", "--json", stdout=output)

        self.assertIn('"monitor_media_mode": "mediamtx"', output.getvalue())

    @patch(
        "apps.cameras.management.commands.diagnose_monitor_media."
        "collect_monitor_media_diagnostics"
    )
    def test_management_command_distinguishes_requested_and_actual_output(
        self,
        collect,
    ):
        collect.return_value = {
            "monitor_media_mode": "mediamtx",
            "active_profile": "grid4",
            "profile_transition_state": "idle",
            "profile_transition_from": "",
            "profile_transition_to": "",
            "profile_transition_started_at": "",
            "profile_transition_camera_count": 0,
            "mediamtx_reachable": True,
            "fallback_enabled": True,
            "path_count": 2,
            "ready_path_count": 2,
            "webrtc_session_count": 2,
            "active_reader_count": 2,
            "active_visible_camera_count": 2,
            "ffmpeg_bridge_process_count": 2,
            "transcoding_count": 1,
            "bridges": [
                {
                    "camera_code": "CAM-001",
                    "source_codec": "H265",
                    "requested_profile": "grid4",
                    "requested_width": 1280,
                    "requested_height": 720,
                    "requested_fps": 15,
                    "actual_bridge_mode": "transcode",
                    "actual_output": "1280x720@15",
                    "state": "running",
                    "process_id": 101,
                    "exit_code": None,
                    "last_error": "",
                },
                {
                    "camera_code": "CAM-002",
                    "source_codec": "H264",
                    "requested_profile": "grid4",
                    "requested_width": 1280,
                    "requested_height": 720,
                    "requested_fps": 15,
                    "actual_bridge_mode": "copy",
                    "actual_output": "source-copy",
                    "state": "running",
                    "process_id": 102,
                    "exit_code": None,
                    "last_error": "",
                },
            ],
            "paths": [],
            "error": "",
        }
        output = __import__("io").StringIO()

        call_command("diagnose_monitor_media", stdout=output)

        rendered = output.getvalue()
        self.assertIn("requested_profile=grid4", rendered)
        self.assertIn("actual_bridge_mode=transcode", rendered)
        self.assertIn("actual_output=1280x720@15", rendered)
        self.assertIn("actual_bridge_mode=copy", rendered)
        self.assertIn("actual_output=source-copy", rendered)
