from __future__ import annotations

import io
import json
import tempfile
import wave
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.settings_app.forms import AlertSoundSettingsForm, LoginBackgroundUploadForm
from apps.settings_app.models import UIConfiguration
from apps.settings_app.services.frontend_assets import (
    ALERT_SOUND_DIR,
    LOGIN_BACKGROUND_DIR,
    MAX_ASSET_BYTES,
    activate_login_background,
    alert_sound_status,
    load_alert_sound_configuration,
    reset_alert_sound,
    reset_login_background,
    resolve_alert_sound_url,
    resolve_login_background_url,
    save_alert_sound,
    validate_alert_sound,
    validate_login_background,
)


def _image_upload(extension: str, *, size=(320, 180), name=None):
    formats = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}
    content = io.BytesIO()
    Image.new("RGB", size, (16, 80, 140)).save(content, format=formats[extension])
    return SimpleUploadedFile(
        name or f"background.{extension}",
        content.getvalue(),
        content_type=f"image/{extension}",
    )


def _wav_upload(name="alert.wav"):
    content = io.BytesIO()
    with wave.open(content, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 800)
    return SimpleUploadedFile(name, content.getvalue(), content_type="audio/wav")


def _mp3_upload(name="alert.mp3"):
    frame = b"\xff\xfb\x90\x64" + (b"\x00" * 413)
    return SimpleUploadedFile(name, frame, content_type="audio/mpeg")


def _ogg_upload(name="alert.ogg"):
    packet = b"OpusHead" + (b"\x00" * 11)
    page = b"OggS" + bytes((0, 2)) + (b"\x00" * 20) + bytes((1, len(packet))) + packet
    return SimpleUploadedFile(name, page, content_type="audio/ogg")


class FrontendAssetTestCase(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.media_root = root / "media"
        self.config_root = root / "config"
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_root,
            MEDIA_URL="/media/",
            KRTC_CONFIG_DIR=self.config_root,
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.temporary_directory.cleanup()


class LoginBackgroundValidationTests(FrontendAssetTestCase):
    def test_supported_image_formats_are_accepted(self):
        for extension in ("jpg", "jpeg", "png", "webp"):
            with self.subTest(extension=extension):
                form = LoginBackgroundUploadForm(
                    files={"login_background": _image_upload(extension)}
                )
                self.assertTrue(form.is_valid(), form.errors)

    def test_fake_image_renamed_jpg_is_rejected(self):
        form = LoginBackgroundUploadForm(
            files={"login_background": SimpleUploadedFile("fake.jpg", b"not an image")}
        )
        self.assertFalse(form.is_valid())

    def test_unsupported_image_extension_is_rejected(self):
        form = LoginBackgroundUploadForm(
            files={"login_background": SimpleUploadedFile("image.svg", b"<svg></svg>")}
        )
        self.assertFalse(form.is_valid())

    def test_corrupt_image_is_rejected(self):
        valid = _image_upload("png").read()
        form = LoginBackgroundUploadForm(
            files={"login_background": SimpleUploadedFile("broken.png", valid[:20])}
        )
        self.assertFalse(form.is_valid())

    def test_oversized_image_is_rejected(self):
        upload = SimpleUploadedFile("large.png", b"x" * (MAX_ASSET_BYTES + 1))
        form = LoginBackgroundUploadForm(files={"login_background": upload})
        self.assertFalse(form.is_valid())

    def test_non_recommended_dimensions_are_accepted(self):
        form = LoginBackgroundUploadForm(
            files={"login_background": _image_upload("png", size=(123, 456))}
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_safe_generated_name_ignores_path_traversal_filename(self):
        asset = validate_login_background(
            _image_upload("png", name="../../惡意;背景.png")
        )
        config = activate_login_background(asset)
        name = config.login_background.name

        self.assertEqual(Path(name).parent.as_posix(), LOGIN_BACKGROUND_DIR)
        self.assertRegex(Path(name).stem, r"^[0-9a-f]{32}$")
        self.assertTrue((self.media_root / name).is_file())


class LoginBackgroundLifecycleTests(FrontendAssetTestCase):
    @override_settings(DEBUG=False)
    def test_valid_custom_background_is_rendered_on_login(self):
        config = activate_login_background(validate_login_background(_image_upload("jpg")))

        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/media/ui/login/")
        public_response = self.client.get(config.login_background.url)
        self.assertEqual(public_response.status_code, 200)
        public_response.close()

    def test_missing_custom_background_falls_back_to_default(self):
        config = UIConfiguration.load()
        config.login_background_enabled = True
        config.login_background = "ui/login/missing.jpg"
        config.save()

        self.assertEqual(resolve_login_background_url(config), "")
        response = self.client.get(reverse("login"))
        self.assertContains(response, "radial-gradient")

    def test_corrupt_stored_background_falls_back_to_default(self):
        path = self.media_root / "ui" / "login" / "broken.jpg"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"broken")
        config = UIConfiguration.load()
        config.login_background_enabled = True
        config.login_background = "ui/login/broken.jpg"
        config.save()

        self.assertEqual(resolve_login_background_url(config), "")

    def test_reset_restores_default_and_removes_managed_file(self):
        config = activate_login_background(validate_login_background(_image_upload("png")))
        stored_path = self.media_root / config.login_background.name

        reset_login_background()

        config.refresh_from_db()
        self.assertFalse(config.login_background_enabled)
        self.assertFalse(config.login_background)
        self.assertFalse(stored_path.exists())

    def test_replacement_removes_previous_managed_background(self):
        first = activate_login_background(validate_login_background(_image_upload("jpg")))
        first_path = self.media_root / first.login_background.name

        second = activate_login_background(validate_login_background(_image_upload("png")))

        self.assertFalse(first_path.exists())
        self.assertTrue((self.media_root / second.login_background.name).is_file())

    def test_reset_never_deletes_non_managed_builtin_file(self):
        builtin = self.media_root / "builtin-default.jpg"
        builtin.parent.mkdir(parents=True, exist_ok=True)
        builtin.write_bytes(b"built in")
        config = UIConfiguration.load()
        config.login_background_enabled = True
        config.login_background = "builtin-default.jpg"
        config.save()

        reset_login_background()

        self.assertTrue(builtin.exists())


class AlertSoundValidationTests(FrontendAssetTestCase):
    def test_supported_audio_formats_are_accepted(self):
        for upload in (_wav_upload(), _mp3_upload(), _ogg_upload()):
            with self.subTest(extension=Path(upload.name).suffix):
                form = AlertSoundSettingsForm(files={"alert_sound": upload})
                self.assertTrue(form.is_valid(), form.errors)

    def test_unsupported_audio_extension_is_rejected(self):
        form = AlertSoundSettingsForm(
            files={"alert_sound": SimpleUploadedFile("alert.exe", b"MZ")}
        )
        self.assertFalse(form.is_valid())

    def test_fake_mp3_and_corrupt_audio_are_rejected(self):
        for upload in (
            SimpleUploadedFile("fake.mp3", b"not audio"),
            SimpleUploadedFile("broken.wav", b"RIFF broken"),
            SimpleUploadedFile("broken.ogg", b"OggS broken"),
        ):
            with self.subTest(name=upload.name):
                form = AlertSoundSettingsForm(files={"alert_sound": upload})
                self.assertFalse(form.is_valid())

    def test_oversized_audio_is_rejected(self):
        form = AlertSoundSettingsForm(
            files={"alert_sound": SimpleUploadedFile("large.mp3", b"x" * (MAX_ASSET_BYTES + 1))}
        )
        self.assertFalse(form.is_valid())

    def test_safe_generated_sound_name_and_storage_location(self):
        config = save_alert_sound(validate_alert_sound(_wav_upload("../alert.wav")), enabled=True)

        self.assertEqual(Path(config.name).parent.as_posix(), ALERT_SOUND_DIR)
        self.assertRegex(Path(config.name).stem, r"^[0-9a-f]{32}$")
        self.assertTrue((self.media_root / config.name).is_file())


class AlertSoundLifecycleTests(FrontendAssetTestCase):
    def test_custom_enabled_resolves_custom_source(self):
        config = save_alert_sound(validate_alert_sound(_wav_upload()), enabled=True)

        self.assertEqual(resolve_alert_sound_url(), f"/media/{config.name}")

    def test_custom_disabled_resolves_builtin_source(self):
        save_alert_sound(validate_alert_sound(_wav_upload()), enabled=False)
        self.assertEqual(resolve_alert_sound_url(), "")

    def test_missing_custom_file_falls_back_to_builtin_source(self):
        self.config_root.mkdir(parents=True)
        (self.config_root / "frontend_assets.json").write_text(
            json.dumps(
                {
                    "alert_sound_enabled": True,
                    "alert_sound": "ui_assets/alert_sound/missing.wav",
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(resolve_alert_sound_url(), "")

    def test_reset_restores_builtin_and_removes_managed_sound(self):
        config = save_alert_sound(validate_alert_sound(_wav_upload()), enabled=True)
        stored_path = self.media_root / config.name

        reset_alert_sound()

        self.assertEqual(load_alert_sound_configuration().name, "")
        self.assertEqual(resolve_alert_sound_url(), "")
        self.assertFalse(stored_path.exists())

    @mock.patch("apps.settings_app.services.frontend_assets.default_storage.delete", side_effect=OSError)
    def test_delete_failure_still_restores_builtin_source(self, _delete):
        save_alert_sound(validate_alert_sound(_wav_upload()), enabled=True)

        reset_alert_sound()

        self.assertEqual(resolve_alert_sound_url(), "")


class FrontendAssetPermissionAndUiTests(FrontendAssetTestCase):
    def setUp(self):
        super().setUp()
        self.administrator_group = Group.objects.get_or_create(name="Administrator")[0]
        self.maintainer_group = Group.objects.get_or_create(name="Maintainer")[0]
        self.operator_group = Group.objects.get_or_create(name="Operator")[0]
        self.administrator = User.objects.create_user("asset-admin", password="test")
        self.administrator.groups.add(self.administrator_group)
        self.maintainer = User.objects.create_user("asset-maintainer", password="test")
        self.maintainer.groups.add(self.maintainer_group)
        self.operator = User.objects.create_user("asset-operator", password="test")
        self.operator.groups.add(self.operator_group)
        self.superuser = User.objects.create_superuser("asset-root", "root@example.com", "test")

    def test_administrator_and_superuser_can_change_background(self):
        for user in (self.administrator, self.superuser):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.post(
                    reverse("settings_app:save_login_background"),
                    {"login_background": _image_upload("png")},
                )
                self.assertEqual(response.status_code, 302)
                self.assertTrue(UIConfiguration.load().login_background_enabled)
                reset_login_background()

    def test_unauthorized_roles_cannot_change_assets(self):
        for user in (self.maintainer, self.operator):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                sound_response = self.client.post(
                    reverse("settings_app:save_event_alert_sound"),
                    {"alert_sound_enabled": "on", "alert_sound": _wav_upload()},
                )
                background_response = self.client.post(
                    reverse("settings_app:save_login_background"),
                    {"login_background": _image_upload("png")},
                )
                self.assertEqual(sound_response.status_code, 404)
                self.assertEqual(background_response.status_code, 404)
                self.assertFalse(alert_sound_status()["has_custom"])
                self.assertFalse(UIConfiguration.load().login_background_enabled)

    def test_anonymous_and_csrf_missing_requests_cannot_change_assets(self):
        anonymous_response = self.client.post(
            reverse("settings_app:save_login_background"),
            {"login_background": _image_upload("png")},
        )
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn(reverse("login"), anonymous_response.url)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.administrator)
        csrf_response = csrf_client.post(
            reverse("settings_app:save_event_alert_sound"),
            {"alert_sound_enabled": "on", "alert_sound": _wav_upload()},
        )
        self.assertEqual(csrf_response.status_code, 404)
        self.assertFalse(alert_sound_status()["has_custom"])
        self.assertFalse(UIConfiguration.load().login_background_enabled)

    def test_invalid_upload_does_not_replace_active_assets(self):
        self.client.force_login(self.administrator)
        background = activate_login_background(
            validate_login_background(_image_upload("jpg"))
        )
        sound = save_alert_sound(validate_alert_sound(_wav_upload()), enabled=True)

        background_response = self.client.post(
            reverse("settings_app:save_login_background"),
            {"login_background": SimpleUploadedFile("fake.jpg", b"not an image")},
        )
        sound_response = self.client.post(
            reverse("settings_app:save_event_alert_sound"),
            {
                "alert_sound_enabled": "on",
                "alert_sound": SimpleUploadedFile("fake.mp3", b"not audio"),
            },
        )

        self.assertEqual(background_response.status_code, 302)
        self.assertEqual(sound_response.status_code, 302)
        self.assertEqual(
            UIConfiguration.load().login_background.name,
            background.login_background.name,
        )
        self.assertEqual(load_alert_sound_configuration().name, sound.name)

    def test_administrator_and_superuser_can_change_alert_sound(self):
        for user in (self.administrator, self.superuser):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.post(
                    reverse("settings_app:save_event_alert_sound"),
                    {"alert_sound_enabled": "on", "alert_sound": _wav_upload()},
                )
                self.assertEqual(response.status_code, 302)
                self.assertTrue(alert_sound_status()["enabled"])
                reset_alert_sound()

    def test_settings_navigation_order_and_general_sections(self):
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("settings_app:station_settings"))
        html = response.content.decode("utf-8")
        labels = ["本站設定", "連線主機", "本站設備", "廣播設定", "執行記錄", "一般設定", "備份與還原"]

        positions = [html.index(f">{label}</button>") for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertContains(response, "登入頁面設定")
        self.assertContains(response, "事件警示音")

    def test_dashboard_receives_only_resolved_sound_source(self):
        self.client.force_login(self.administrator)
        config = save_alert_sound(validate_alert_sound(_wav_upload()), enabled=True)

        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.context["event_alert_sound_url"], f"/media/{config.name}")
        self.assertContains(response, "data-event-alert-sound-url")
