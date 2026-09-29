from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.settings_app.forms import AudioFileForm, SpeakerDeviceForm
from apps.settings_app.views import MANAGEMENT_REGISTRY


class V665UiConsistencyTests(SimpleTestCase):
    def test_audio_file_labels_and_choices_are_localized(self):
        form = AudioFileForm()
        self.assertEqual(form.fields["audio_code"].label, "音檔代碼")
        self.assertEqual(form.fields["name"].label, "音檔名稱")
        self.assertEqual(form.fields["audio_type"].label, "音檔類型")
        self.assertEqual(form.fields["file"].label, "音檔檔案")
        self.assertEqual(form.fields["duration_seconds"].label, "音檔長度（秒）")
        self.assertEqual(form.fields["message_text"].label, "廣播文字內容")
        self.assertEqual(form.fields["is_active"].label, "是否啟用")
        self.assertEqual(form.fields["description"].label, "說明")
        labels = dict(form.fields["audio_type"].choices)
        self.assertEqual(labels["alert"], "警示")
        self.assertEqual(labels["guidance"], "引導")
        self.assertEqual(labels["warning"], "警告")
        self.assertEqual(labels["test"], "測試")
        self.assertEqual(labels["other"], "其他")

    def test_speaker_uses_full_page_management_registry(self):
        config = MANAGEMENT_REGISTRY["speaker-device"]
        self.assertEqual(config["title"], "廣播喇叭")
        self.assertEqual(config["tab"], "devices")
        form = SpeakerDeviceForm()
        labels = dict(form.fields["deployment_state"].choices)
        self.assertEqual(labels["planned"], "未部署")
        self.assertEqual(labels["deployed"], "已部署")
        self.assertEqual(labels["maintenance"], "維護中")
        self.assertEqual(labels["retired"], "已退役")

    def test_station_settings_uses_page_links_not_speaker_modal(self):
        text = (Path(settings.BASE_DIR) / "templates/settings_app/station_settings.html").read_text(encoding="utf-8")
        self.assertIn("manage_new' 'speaker-device", text)
        self.assertIn("manage_edit' 'speaker-device", text)
        self.assertNotIn('id="speaker-modal"', text)
        self.assertNotIn('id="speaker-add-button"', text)

    def test_audio_file_picker_and_button_styles_are_present(self):
        template = (Path(settings.BASE_DIR) / "templates/settings_app/manage_object.html").read_text(encoding="utf-8")
        css = (Path(settings.BASE_DIR) / "static/css/station_settings.css").read_text(encoding="utf-8")
        self.assertIn("localized-file-picker", template)
        self.assertIn("選擇檔案", template)
        self.assertIn("尚未選擇檔案", template)
        self.assertIn("panel-action-group a.primary-button", css)
        self.assertIn("management-form-actions > a.test-button", css)

    def test_dashboard_inference_title_remains_white(self):
        css = (Path(settings.BASE_DIR) / "static/css/dashboard.css").read_text(encoding="utf-8")
        self.assertIn("KRTC V6.6.5 - keep inference metric title white", css)
        self.assertIn(".inference-host-metric.is-abnormal > span", css)
        self.assertIn("color: #ffffff !important;", css)
