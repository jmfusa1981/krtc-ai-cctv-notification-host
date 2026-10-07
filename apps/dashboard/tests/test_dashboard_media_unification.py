from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.cameras.models import Camera
from apps.events.models import Event


class DashboardMediaFrontendContractTests(SimpleTestCase):
    """驗證Dashboard與Monitor共用MediaMTX播放生命週期契約。"""

    def setUp(self):
        base_dir = Path(settings.BASE_DIR)
        self.dashboard_script = (
            base_dir / "static/js/dashboard.js"
        ).read_text(encoding="utf-8")
        self.shared_script = (
            base_dir / "static/js/mediamtx_player.js"
        ).read_text(encoding="utf-8")
        self.dashboard_template = (
            base_dir / "templates/dashboard/index.html"
        ).read_text(encoding="utf-8")
        self.monitor_template = (
            base_dir / "templates/dashboard/monitor.html"
        ).read_text(encoding="utf-8")

    def test_dashboard_and_monitor_load_shared_player_before_page_script(self):
        for template, page_script in (
            (self.dashboard_template, "js/dashboard.js"),
            (self.monitor_template, "js/monitor.js"),
        ):
            self.assertIn("js/mediamtx_player.js", template)
            self.assertLess(
                template.index("js/mediamtx_player.js"),
                template.index(page_script),
            )

    def test_live_view_prefers_webrtc_and_keeps_mjpeg_as_fallback(self):
        self.assertIn("camera.browser_playback", self.dashboard_script)
        self.assertIn("prepareDashboardWebRTC", self.dashboard_script)
        self.assertIn("prepareDashboardMjpeg", self.dashboard_script)
        self.assertIn("isDashboardPathReady", self.dashboard_script)
        self.assertIn("/api/cameras/${camera.id}/stream/", self.dashboard_script)

    def test_camera_switch_uses_two_layers_and_releases_previous_source(self):
        self.assertIn('data-dashboard-live-layer="a"', self.dashboard_script)
        self.assertIn('data-dashboard-live-layer="b"', self.dashboard_script)
        self.assertIn("commitDashboardLayer", self.dashboard_script)
        self.assertIn("releaseDashboardLayer(previousLayer)", self.dashboard_script)
        self.assertIn("releaseDashboardLiveView", self.dashboard_script)

    def test_iframe_load_waits_for_stable_new_webrtc_reader(self):
        self.assertIn("verifyDashboardWebRTCPlayable", self.dashboard_script)
        self.assertIn("baselineReaderCount + 1", self.dashboard_script)
        self.assertIn("DASHBOARD_WEBRTC_STABLE_SAMPLES", self.dashboard_script)
        self.assertIn("detail.ready === true && hasNewReader", self.dashboard_script)
        self.assertNotIn(
            "player.onload = function () {\n            commitDashboardLayer",
            self.dashboard_script,
        )

    def test_webrtc_recovery_and_fallback_do_not_leave_thumbnail_streams(self):
        self.assertIn("reconcileDashboardLiveMedia", self.dashboard_script)
        self.assertIn("DASHBOARD_MEDIA_STATUS_REFRESH_MS", self.dashboard_script)
        self.assertNotIn("data-dashboard-camera-stream", self.dashboard_script)
        self.assertIn("releaseMjpeg", self.shared_script)
        self.assertIn("releaseWebRTC", self.shared_script)

    def test_camera_cards_restore_mediamtx_webrtc_previews(self):
        self.assertIn("data-dashboard-preview-player", self.dashboard_script)
        self.assertIn('data-player-url="${escapeHtml(playback.url)}"', self.dashboard_script)
        self.assertIn("activateDashboardPreview", self.dashboard_script)
        self.assertIn(
            "window.KRTCMediaPlayer.activateWebRTC(player, playback.url)",
            self.dashboard_script,
        )

    def test_preview_does_not_use_mjpeg_fallback(self):
        preview_section = self.dashboard_script[
            self.dashboard_script.index("async function activateDashboardPreview"):
            self.dashboard_script.index("function observeDashboardPreviews")
        ]
        self.assertNotIn("activateMjpeg", preview_section)
        self.assertNotIn("camera.stream_url", preview_section)
        self.assertIn("即時預覽暫時無法使用", preview_section)

    def test_preview_only_activates_visible_cards_and_releases_hidden_cards(self):
        self.assertIn("new IntersectionObserver", self.dashboard_script)
        self.assertIn("dashboardVisiblePreviewCards.add(card)", self.dashboard_script)
        self.assertIn("dashboardVisiblePreviewCards.delete(card)", self.dashboard_script)
        self.assertIn(
            'releaseDashboardPreview(card, "idle", "即時預覽待命")',
            self.dashboard_script,
        )

    def test_preview_waits_for_path_reader_and_has_finite_timeout(self):
        self.assertIn("verifyDashboardPreviewPlayable", self.dashboard_script)
        self.assertIn("baselineReaderCount + 1", self.dashboard_script)
        self.assertIn("DASHBOARD_PREVIEW_READY_TIMEOUT_MS", self.dashboard_script)
        self.assertIn("即時預覽連線逾時", self.dashboard_script)

    def test_camera_refresh_and_navigation_release_preview_sessions(self):
        render_section = self.dashboard_script[
            self.dashboard_script.index("function renderCameraGrid"):
            self.dashboard_script.index("function stopInferenceHostDetailRotation")
        ]
        self.assertLess(
            render_section.index("releaseAllDashboardPreviews()"),
            render_section.index('cameraGrid.innerHTML = ""'),
        )
        pagehide_section = self.dashboard_script[
            self.dashboard_script.index('window.addEventListener("pagehide"'):
            self.dashboard_script.index('window.addEventListener("pageshow"')
        ]
        self.assertIn("releaseAllDashboardPreviews()", pagehide_section)
        self.assertIn("releaseWebRTC(player)", self.dashboard_script)

    def test_unchanged_camera_refresh_does_not_duplicate_preview_players(self):
        render_section = self.dashboard_script[
            self.dashboard_script.index("function renderCameraGrid"):
            self.dashboard_script.index("function stopInferenceHostDetailRotation")
        ]
        self.assertLess(
            render_section.index("if (newSignature === cameraSignature)"),
            render_section.index("releaseAllDashboardPreviews()"),
        )
        self.assertIn("previewActiveWebrtcCount", self.dashboard_script)
        self.assertIn("previewVisibleCount", self.dashboard_script)
        self.assertIn("button.dataset.previewCamera = code", self.dashboard_script)

    def test_preview_restoration_preserves_selected_camera_card_state(self):
        self.assertIn("updateCameraSelectionClasses()", self.dashboard_script)
        self.assertIn("selected-event-camera-card", self.dashboard_script)
        self.assertIn("data-camera-card", self.dashboard_script)

    def test_media_diagnostics_expose_safe_runtime_state(self):
        for diagnostic in (
            "mediaCamera",
            "mediaPath",
            "mediaPathReady",
            "mediaReaderCount",
            "mediaMode",
            "mediaTransitionState",
        ):
            self.assertIn(diagnostic, self.dashboard_script)
        self.assertIn("payload.path_details", self.dashboard_script)

    def test_event_snapshot_remains_a_static_image(self):
        self.assertIn(
            'renderImageMedia(\n                event.snapshot_url,',
            self.dashboard_script,
        )
        self.assertIn('id="primaryEventMedia"', self.dashboard_script)
        self.assertNotIn("event.snapshot_url,\n                camera.browser_playback", self.dashboard_script)


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
class DashboardMediaApiTests(TestCase):
    """驗證Dashboard API提供安全且一致的四路WebRTC映射。"""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "dashboard-media-user",
            password="test-pass",
        )
        self.cameras = []
        for index in range(1, 5):
            camera = Camera.objects.create(
                camera_code=f"CAM-{index:03d}",
                name=f"Camera {index}",
                area="Lab",
                rtsp_url=f"rtsp://operator:secret@camera-{index}/cam1/h264",
                username="operator",
                password="secret",
                status="online",
                is_online=True,
                is_active=True,
            )
            Event.objects.create(camera=camera, event_type="other")
            self.cameras.append(camera)
        self.client.force_login(self.user)

    def test_live_state_maps_all_four_cameras_to_safe_mediamtx_paths(self):
        response = self.client.get(reverse("dashboard:dashboard_live_state_api"))

        self.assertEqual(response.status_code, 200)
        cameras = {
            item["camera_code"]: item
            for item in response.json()["cameras"]
        }
        self.assertEqual(set(cameras), {f"CAM-{index:03d}" for index in range(1, 5)})
        for index in range(1, 5):
            code = f"CAM-{index:03d}"
            playback = cameras[code]["browser_playback"]
            self.assertTrue(playback["available"])
            self.assertEqual(playback["path"], f"cam{index:03d}")
            self.assertIn(f"/cam{index:03d}?", playback["url"])
            self.assertEqual(
                cameras[code]["stream_url"],
                f"/api/cameras/{self.cameras[index - 1].id}/stream/",
            )
        content = response.content.decode("utf-8")
        self.assertNotIn("operator", content)
        self.assertNotIn("secret", content)

    def test_dashboard_renders_media_status_and_shared_player_contract(self):
        response = self.client.get(reverse("dashboard:home"))

        self.assertContains(response, "data-dashboard-media-status-url=")
        self.assertContains(response, "js/mediamtx_player.js")
        self.assertContains(response, "js/dashboard.js")
