from django.test import SimpleTestCase

from apps.cameras.rtsp_utils import build_authenticated_rtsp_url, safe_rtsp_url


class RtspAuthenticationHelperTests(SimpleTestCase):
    def test_injects_credentials(self):
        value = build_authenticated_rtsp_url(
            "rtsp://192.168.6.90/cam1/onvif-h264",
            "root",
            "secret",
        )
        self.assertEqual(
            value,
            "rtsp://root:secret@192.168.6.90/cam1/onvif-h264",
        )

    def test_encodes_special_characters(self):
        value = build_authenticated_rtsp_url(
            "rtsp://192.168.6.90:554/live",
            "user@example",
            "p@ss:word#1",
        )
        self.assertIn("user%40example:p%40ss%3Aword%231@", value)
        self.assertTrue(value.endswith("192.168.6.90:554/live"))

    def test_preserves_existing_credentials(self):
        raw = "rtsp://existing:credential@192.168.6.90/live"
        self.assertEqual(
            build_authenticated_rtsp_url(raw, "other", "other"),
            raw,
        )

    def test_no_username_returns_original(self):
        raw = "rtsp://192.168.6.90/live"
        self.assertEqual(build_authenticated_rtsp_url(raw, "", "secret"), raw)

    def test_non_rtsp_url_is_unchanged(self):
        raw = "http://192.168.6.90/live.mjpeg"
        self.assertEqual(build_authenticated_rtsp_url(raw, "root", "secret"), raw)

    def test_safe_url_removes_embedded_credentials(self):
        self.assertEqual(
            safe_rtsp_url("rtsp://root:secret@192.168.6.90:554/live"),
            "rtsp://192.168.6.90:554/live",
        )
