from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.settings_app.forms import CameraForm, InferenceHostForm, SpeakerDeviceForm


class V664LocalizationTests(SimpleTestCase):
    def test_inference_host_form_labels_are_localized(self):
        form = InferenceHostForm()
        self.assertEqual(form.fields["host_code"].label, "推論主機代碼")
        self.assertEqual(form.fields["station_code"].label, "站碼")
        self.assertEqual(form.fields["ip_address"].label, "IP 位址")
        self.assertEqual(form.fields["websocket_auth_mode"].label, "WebSocket 驗證模式")
        self.assertEqual(dict(form.fields["host_type"].widget.choices)["physical"], "實體主機")
        self.assertEqual(dict(form.fields["websocket_auth_mode"].widget.choices)["none"], "無驗證")

    def test_camera_form_labels_and_status_choices_are_localized(self):
        form = CameraForm()
        self.assertEqual(form.fields["camera_code"].label, "攝影機代碼")
        self.assertEqual(form.fields["status"].label, "連線狀態")
        choices = dict(form.fields["status"].choices)
        self.assertEqual(choices["online"], "線上")
        self.assertEqual(choices["offline"], "離線")
        self.assertEqual(choices["maintenance"], "維護中")
        self.assertEqual(choices["error"], "異常")

    def test_speaker_form_labels_are_localized(self):
        form = SpeakerDeviceForm()
        self.assertEqual(form.fields["speaker_code"].label, "喇叭代碼")
        self.assertEqual(form.fields["port"].label, "SIP 連接埠")
        self.assertEqual(form.fields["username"].label, "SIP 使用者名稱")

    def test_broadcast_ui_has_chinese_schedule_validation_and_log_statuses(self):
        base = Path(settings.BASE_DIR)
        template = (base / "templates/dashboard/station_broadcast.html").read_text(encoding="utf-8")
        script = (base / "static/js/station_broadcast.js").read_text(encoding="utf-8")
        self.assertIn('id="broadcastScheduleForm"', template)
        self.assertIn("novalidate", template)
        for label in ["待處理", "播放中", "成功", "失敗", "略過"]:
            self.assertIn(label, template)
        for message in ["請輸入排程名稱。", "請設定單次執行時間。", "請選擇預錄音檔。", "請至少選擇一台播放 Speaker。"]:
            self.assertIn(message, script)

    def test_speaker_management_form_uses_localized_labels(self):
        form = SpeakerDeviceForm()
        self.assertEqual(form.fields["speaker_code"].label, "喇叭代碼")
        self.assertEqual(form.fields["ip_address"].label, "IP 位址")
        self.assertEqual(form.fields["port"].label, "SIP 連接埠")
        self.assertEqual(form.fields["username"].label, "SIP 使用者名稱")
        self.assertEqual(form.fields["preferred_codec"].label, "音訊編碼（Codec）")
