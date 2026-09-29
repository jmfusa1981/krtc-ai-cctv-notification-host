from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class V664DeviceDashboardUiTests(SimpleTestCase):
    def test_device_list_uses_parallel_blocks_instead_of_tabs(self):
        base = Path(settings.BASE_DIR)
        template = (base / "templates/dashboard/device_list.html").read_text(encoding="utf-8")
        css = (base / "static/css/device_list.css").read_text(encoding="utf-8")
        self.assertIn('class="device-list-grid"', template)
        self.assertIn("camera-list-block", template)
        self.assertIn("speaker-list-block", template)
        self.assertNotIn("data-device-tab", template)
        self.assertNotIn("data-device-panel", template)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", css)

    def test_inference_abnormal_style_keeps_blue_background(self):
        base = Path(settings.BASE_DIR)
        css = (base / "static/css/dashboard.css").read_text(encoding="utf-8")
        self.assertIn(".inference-host-metric.is-abnormal {", css)
        self.assertIn("background: transparent !important;", css)
        self.assertIn("color: #ffb4b4 !important;", css)

    def test_inference_connection_table_has_wider_error_column(self):
        base = Path(settings.BASE_DIR)
        css = (base / "static/css/station_settings.css").read_text(encoding="utf-8")
        self.assertIn("width: 31%;", css)
