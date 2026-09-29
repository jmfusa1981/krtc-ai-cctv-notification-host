from __future__ import annotations

import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.settings_app.forms import NtpSettingsForm
from apps.settings_app.services.ntp_time import (
    NTP_SYNC_TIMEOUT_SECONDS,
    NTP_TEST_TIMEOUT_SECONDS,
    SOURCE_ORDER,
    W32TM_EXECUTABLE,
    NtpConfiguration,
    NtpConfigurationError,
    NtpStatus,
    TimeOperationResult,
    WindowsTimeAdapter,
    check_time_sources,
    load_ntp_configuration,
    reset_ntp_settings,
    save_ntp_settings,
    synchronize_now,
    status_for_template,
    test_ntp_source,
    validate_ipv4_address,
)


class NtpAddressValidationTests(SimpleTestCase):
    def test_valid_ipv4_is_accepted(self):
        self.assertEqual(validate_ipv4_address("10.12.56.1"), "10.12.56.1")

    def test_malformed_ipv4_is_rejected(self):
        for value in ("10.12.56.999", "10.12.56", "not-an-ip"):
            with self.subTest(value=value):
                with self.assertRaises(NtpConfigurationError):
                    validate_ipv4_address(value)

    def test_url_port_path_and_shell_input_are_rejected(self):
        for value in (
            "http://10.12.56.1",
            "10.12.56.1:123",
            "10.12.56.1/path",
            "10.12.56.1 & whoami",
            "10.12.56.1;calc.exe",
        ):
            with self.subTest(value=value):
                with self.assertRaises(NtpConfigurationError):
                    validate_ipv4_address(value)

    def test_blank_optional_address_is_accepted(self):
        self.assertEqual(validate_ipv4_address(""), "")
        form = NtpSettingsForm(
            {
                "enabled": "on",
                "station_clock_lan1": "10.12.56.1",
                "station_clock_lan2": "",
                "occ_backup_clock_lan1": "",
                "occ_backup_clock_lan2": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)


class WindowsTimeAdapterTests(SimpleTestCase):
    def test_ntp_test_uses_stripchart_without_time_change(self):
        completed = subprocess.CompletedProcess(
            [],
            0,
            stdout="09:00:00, -00.0250000s\n09:00:01, +00.0100000s",
            stderr="",
        )
        runner = mock.Mock(return_value=completed)
        result = WindowsTimeAdapter(runner=runner).test_source("10.12.56.1")

        self.assertTrue(result.success)
        self.assertEqual(result.offset, "+00.0100000 秒")
        command = runner.call_args.args[0]
        self.assertEqual(
            command,
            [
                W32TM_EXECUTABLE,
                "/stripchart",
                "/computer:10.12.56.1",
                "/samples:3",
                "/dataonly",
            ],
        )
        self.assertNotIn("/config", command)
        self.assertNotIn("/resync", command)
        self.assertFalse(runner.call_args.kwargs["shell"])
        self.assertEqual(runner.call_args.kwargs["timeout"], NTP_TEST_TIMEOUT_SECONDS)

    def test_ntp_test_parses_traditional_chinese_offset_without_english_unit(self):
        completed = subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                "正在追蹤 10.12.56.1。\n"
                "12:49:40，-00.0250000 秒\n"
                "12:49:41，＋00.0100000 秒"
            ),
            stderr="",
        )

        result = WindowsTimeAdapter(runner=mock.Mock(return_value=completed)).test_source(
            "10.12.56.1"
        )

        self.assertTrue(result.success)
        self.assertEqual(result.offset, "+00.0100000 秒")

    def test_zero_exit_with_only_traditional_chinese_timeouts_is_unavailable(self):
        completed = subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                "正在追蹤 10.12.56.1 [10.12.56.1:123]。\n"
                "正在收集 3 樣本。\n"
                "13:58:58, 錯誤: 0x800705B4\n"
                "13:59:01, 錯誤: 0x800705B4\n"
                "13:59:04, 錯誤: 0x800705B4"
            ),
            stderr="",
        )

        result = WindowsTimeAdapter(runner=mock.Mock(return_value=completed)).test_source(
            "10.12.56.1"
        )

        self.assertFalse(result.success)
        self.assertIsNone(result.offset)
        self.assertEqual(result.failure_scope, "source")
        self.assertEqual(result.message, "時間來源無回應或未取得有效 NTP 樣本。")

    def test_mixed_timeout_and_valid_sample_is_available(self):
        completed = subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                "13:58:58, 錯誤: 0x800705B4\n"
                "13:59:01，+00.0125000 秒\n"
                "13:59:04, 錯誤: 0x800705B4"
            ),
            stderr="",
        )

        result = WindowsTimeAdapter(runner=mock.Mock(return_value=completed)).test_source(
            "10.12.56.1"
        )

        self.assertTrue(result.success)
        self.assertEqual(result.offset, "+00.0125000 秒")

    def test_ntp_test_normalizes_localized_decimal_separator(self):
        completed = subprocess.CompletedProcess(
            [],
            0,
            stdout="12:49:41, −00,0012500 秒",
            stderr="",
        )

        result = WindowsTimeAdapter(runner=mock.Mock(return_value=completed)).test_source(
            "10.12.56.1"
        )

        self.assertEqual(result.offset, "-00.0012500 秒")

    def test_sync_uses_only_allowlisted_config_and_resync_commands(self):
        runner = mock.Mock(
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout="configured", stderr=""),
                subprocess.CompletedProcess([], 0, stdout="resynced", stderr=""),
            ]
        )
        result = WindowsTimeAdapter(runner=runner).synchronize("10.12.56.2")

        self.assertTrue(result.success)
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(
            runner.call_args_list[0].args[0],
            [
                W32TM_EXECUTABLE,
                "/config",
                "/manualpeerlist:10.12.56.2,0x8",
                "/syncfromflags:manual",
                "/update",
            ],
        )
        self.assertEqual(
            runner.call_args_list[1].args[0],
            [W32TM_EXECUTABLE, "/resync", "/rediscover"],
        )
        for call in runner.call_args_list:
            self.assertFalse(call.kwargs["shell"])
            self.assertEqual(call.kwargs["timeout"], NTP_SYNC_TIMEOUT_SECONDS)

    def test_timeout_is_controlled(self):
        runner = mock.Mock(side_effect=subprocess.TimeoutExpired("w32tm", 15))
        result = WindowsTimeAdapter(runner=runner).test_source("10.12.56.1")
        self.assertFalse(result.success)
        self.assertIn("逾時", result.message)

    def test_nonzero_exit_is_controlled(self):
        runner = mock.Mock(
            return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="failed")
        )
        result = WindowsTimeAdapter(runner=runner).test_source("10.12.56.1")
        self.assertFalse(result.success)
        self.assertEqual(result.message, "Windows Time 操作失敗：failed")

    def test_permission_error_is_classified(self):
        runner = mock.Mock(
            return_value=subprocess.CompletedProcess(
                [],
                5,
                stdout="",
                stderr="Access is denied.",
            )
        )
        result = WindowsTimeAdapter(runner=runner).synchronize("10.12.56.1")
        self.assertFalse(result.success)
        self.assertTrue(result.permission_required)
        self.assertIn("系統管理員權限", result.message)
        self.assertEqual(runner.call_count, 1)

    def test_windows_time_service_failure_is_machine_level(self):
        runner = mock.Mock(
            return_value=subprocess.CompletedProcess(
                [],
                1,
                stdout="",
                stderr="The service has not been started. (0x80070426)",
            )
        )

        result = WindowsTimeAdapter(runner=runner).test_source("10.12.56.1")

        self.assertFalse(result.success)
        self.assertEqual(result.failure_scope, "machine")
        self.assertEqual(result.message, "Windows Time 服務目前無法使用。")

    def test_invalid_address_never_reaches_subprocess(self):
        runner = mock.Mock()
        with self.assertRaises(NtpConfigurationError):
            WindowsTimeAdapter(runner=runner).test_source("10.12.56.1 & whoami")
        runner.assert_not_called()


class NtpPresentationTests(SimpleTestCase):
    def test_utc_status_timestamps_are_presented_in_taipei_time(self):
        config = NtpConfiguration(
            status=NtpStatus(
                last_test_at="2026-09-09T04:49:41+00:00",
                last_sync_at="2026-09-09T05:01:02Z",
            )
        )

        status = status_for_template(config)

        self.assertEqual(status["last_test_at"], "2026-09-09 12:49:41")
        self.assertEqual(status["last_sync_at"], "2026-09-09 13:01:02")


class FakeTimeAdapter:
    def __init__(self, test_results, sync_result=None, sync_results=None):
        self.test_results = test_results
        self.sync_result = sync_result or TimeOperationResult(True, "同步成功。")
        self.sync_results = sync_results or {}
        self.test_calls = []
        self.sync_calls = []

    def test_source(self, address):
        self.test_calls.append(address)
        return self.test_results.get(
            address,
            TimeOperationResult(False, "來源無法使用。"),
        )

    def synchronize(self, address):
        self.sync_calls.append(address)
        return self.sync_results.get(address, self.sync_result)


class NtpConfigurationTestCase(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.config_root = root / "config"
        self.media_root = root / "media"
        self.settings_override = override_settings(
            KRTC_CONFIG_DIR=self.config_root,
            MEDIA_ROOT=self.media_root,
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.temporary_directory.cleanup()

    def save_sources(self, **overrides):
        sources = {
            "station_clock_lan1": "10.12.56.1",
            "station_clock_lan2": "10.12.56.2",
            "occ_backup_clock_lan1": "10.12.164.1",
            "occ_backup_clock_lan2": "10.12.164.2",
        }
        sources.update(overrides)
        return save_ntp_settings(enabled=True, sources=sources)


class NtpPersistenceTests(NtpConfigurationTestCase):
    def test_configuration_persists_and_reloads(self):
        saved = self.save_sources()
        loaded = load_ntp_configuration()

        self.assertEqual(loaded, saved)
        self.assertTrue((self.config_root / "ntp_settings.json").is_file())

    def test_existing_configuration_survives_atomic_write_failure(self):
        self.save_sources()
        path = self.config_root / "ntp_settings.json"
        original = path.read_bytes()

        with mock.patch(
            "apps.settings_app.services.ntp_time.os.replace",
            side_effect=OSError("write failed"),
        ):
            with self.assertRaises(OSError):
                save_ntp_settings(
                    enabled=False,
                    sources={key: "" for key, _label in SOURCE_ORDER},
                )

        self.assertEqual(path.read_bytes(), original)

    def test_restore_default_changes_only_ntp_configuration(self):
        self.save_sources()
        self.config_root.mkdir(parents=True, exist_ok=True)
        unrelated_config = self.config_root / "frontend_assets.json"
        unrelated_config.write_text('{"alert_sound_enabled": true}', encoding="utf-8")
        unrelated_media = self.media_root / "ui_assets" / "alert_sound" / "sound.wav"
        unrelated_media.parent.mkdir(parents=True, exist_ok=True)
        unrelated_media.write_bytes(b"unrelated")

        reset_ntp_settings()

        self.assertEqual(load_ntp_configuration().sources.station_clock_lan1, "")
        self.assertFalse(load_ntp_configuration().enabled)
        self.assertTrue(unrelated_config.is_file())
        self.assertTrue(unrelated_media.is_file())

    def test_source_priority_is_fixed(self):
        self.assertEqual(
            [key for key, _label in SOURCE_ORDER],
            [
                "station_clock_lan1",
                "station_clock_lan2",
                "occ_backup_clock_lan1",
                "occ_backup_clock_lan2",
            ],
        )


class NtpPriorityTests(NtpConfigurationTestCase):
    success = TimeOperationResult(True, "可用。", offset="0.01 秒")
    failure = TimeOperationResult(False, "無法使用。")

    def test_station_lan1_success_stops_traversal(self):
        self.save_sources()
        adapter = FakeTimeAdapter({"10.12.56.1": self.success})

        result = synchronize_now(adapter=adapter)

        self.assertTrue(result.success)
        self.assertEqual(adapter.test_calls, ["10.12.56.1"])
        self.assertEqual(adapter.sync_calls, ["10.12.56.1"])
        self.assertEqual(
            load_ntp_configuration().status.current_source,
            "station_clock_lan1",
        )

    def test_station_lan1_failure_falls_through_to_lan2(self):
        self.save_sources()
        adapter = FakeTimeAdapter(
            {"10.12.56.1": self.failure, "10.12.56.2": self.success}
        )

        synchronize_now(adapter=adapter)

        self.assertEqual(adapter.test_calls, ["10.12.56.1", "10.12.56.2"])
        self.assertEqual(adapter.sync_calls, ["10.12.56.2"])

    def test_source_specific_resync_failure_falls_through_to_next_source(self):
        self.save_sources()
        adapter = FakeTimeAdapter(
            {
                "10.12.56.1": self.success,
                "10.12.56.2": self.success,
            },
            sync_results={
                "10.12.56.1": TimeOperationResult(False, "來源校時失敗。"),
                "10.12.56.2": TimeOperationResult(True, "同步成功。"),
            },
        )

        result = synchronize_now(adapter=adapter)

        self.assertTrue(result.success)
        self.assertEqual(adapter.test_calls, ["10.12.56.1", "10.12.56.2"])
        self.assertEqual(adapter.sync_calls, ["10.12.56.1", "10.12.56.2"])
        self.assertEqual(
            load_ntp_configuration().status.current_source,
            "station_clock_lan2",
        )

    def test_machine_level_privilege_failure_stops_failover(self):
        self.save_sources()
        adapter = FakeTimeAdapter(
            {"10.12.56.1": self.success, "10.12.56.2": self.success},
            sync_result=TimeOperationResult(
                False,
                "Windows Time 操作需要系統管理員權限。",
                permission_required=True,
                failure_scope="machine",
            ),
        )

        result = synchronize_now(adapter=adapter)

        self.assertFalse(result.success)
        self.assertEqual(adapter.test_calls, ["10.12.56.1"])
        self.assertEqual(adapter.sync_calls, ["10.12.56.1"])

    def test_machine_level_probe_failure_stops_failover(self):
        self.save_sources()
        machine_failure = TimeOperationResult(
            False,
            "無法啟動 Windows Time 工具。",
            failure_scope="machine",
        )
        adapter = FakeTimeAdapter({"10.12.56.1": machine_failure})

        result = synchronize_now(adapter=adapter)

        self.assertFalse(result.success)
        self.assertEqual(adapter.test_calls, ["10.12.56.1"])
        self.assertEqual(adapter.sync_calls, [])

    def test_station_failures_fall_through_to_occ_lan1(self):
        self.save_sources()
        adapter = FakeTimeAdapter(
            {
                "10.12.56.1": self.failure,
                "10.12.56.2": self.failure,
                "10.12.164.1": self.success,
            }
        )

        synchronize_now(adapter=adapter)

        self.assertEqual(
            adapter.test_calls,
            ["10.12.56.1", "10.12.56.2", "10.12.164.1"],
        )
        self.assertEqual(adapter.sync_calls, ["10.12.164.1"])

    def test_occ_lan1_failure_falls_through_to_occ_lan2(self):
        self.save_sources(station_clock_lan1="", station_clock_lan2="")
        adapter = FakeTimeAdapter(
            {"10.12.164.1": self.failure, "10.12.164.2": self.success}
        )

        synchronize_now(adapter=adapter)

        self.assertEqual(adapter.test_calls, ["10.12.164.1", "10.12.164.2"])
        self.assertEqual(adapter.sync_calls, ["10.12.164.2"])

    def test_all_unavailable_returns_controlled_failure(self):
        self.save_sources()
        adapter = FakeTimeAdapter({})

        result = synchronize_now(adapter=adapter)

        self.assertFalse(result.success)
        self.assertEqual(adapter.sync_calls, [])
        self.assertEqual(load_ntp_configuration().status.current_status, "unavailable")

    def test_test_source_never_requests_synchronization(self):
        self.save_sources()
        adapter = FakeTimeAdapter({"10.12.56.1": self.success})

        result = test_ntp_source(
            "station_clock_lan1",
            "10.12.56.1",
            adapter=adapter,
        )

        self.assertTrue(result.success)
        self.assertEqual(adapter.test_calls, ["10.12.56.1"])
        self.assertEqual(adapter.sync_calls, [])

    def test_one_click_check_tests_sources_without_synchronization(self):
        self.save_sources(occ_backup_clock_lan2="")
        adapter = FakeTimeAdapter(
            {
                "10.12.56.1": self.success,
                "10.12.56.2": self.failure,
                "10.12.164.1": self.success,
            }
        )

        summary = check_time_sources(adapter=adapter)

        self.assertTrue(summary.success)
        self.assertEqual(summary.recommended_source, "station_clock_lan1")
        self.assertEqual(
            adapter.test_calls,
            ["10.12.56.1", "10.12.56.2", "10.12.164.1"],
        )
        self.assertEqual(adapter.sync_calls, [])
        self.assertEqual(summary.results[-1]["message"], "未設定")

    def test_one_click_check_rejects_all_zero_exit_timeout_sources(self):
        self.save_sources()
        completed = subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                "正在收集 3 樣本。\n"
                "13:58:58, 錯誤: 0x800705B4\n"
                "13:59:01, 錯誤: 0x800705B4\n"
                "13:59:04, 錯誤: 0x800705B4"
            ),
            stderr="",
        )
        adapter = WindowsTimeAdapter(runner=mock.Mock(return_value=completed))

        summary = check_time_sources(adapter=adapter)

        self.assertFalse(summary.success)
        self.assertIsNone(summary.recommended_source)
        config = load_ntp_configuration()
        self.assertEqual(config.status.current_status, "unavailable")
        self.assertTrue(
            all(
                result["state"] == "unavailable"
                for result in config.status.source_results.values()
            )
        )

    def test_sync_now_does_not_configure_zero_exit_timeout_source(self):
        self.save_sources(
            station_clock_lan2="",
            occ_backup_clock_lan1="",
            occ_backup_clock_lan2="",
        )
        completed = subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                "13:58:58, 錯誤: 0x800705B4\n"
                "13:59:01, 錯誤: 0x800705B4\n"
                "13:59:04, 錯誤: 0x800705B4"
            ),
            stderr="",
        )
        adapter = WindowsTimeAdapter(runner=mock.Mock(return_value=completed))

        with mock.patch.object(adapter, "synchronize", wraps=adapter.synchronize) as sync:
            result = synchronize_now(adapter=adapter)

        self.assertFalse(result.success)
        sync.assert_not_called()
        self.assertEqual(load_ntp_configuration().status.current_status, "unavailable")

    def test_disabled_setting_blocks_all_managed_operations(self):
        config = self.save_sources()
        save_ntp_settings(enabled=False, sources=asdict(config.sources))
        adapter = FakeTimeAdapter({"10.12.56.1": self.success})

        check_result = check_time_sources(adapter=adapter)
        test_result = test_ntp_source(
            "station_clock_lan1",
            "10.12.56.1",
            adapter=adapter,
        )
        sync_result = synchronize_now(adapter=adapter)

        self.assertFalse(check_result.success)
        self.assertFalse(test_result.success)
        self.assertFalse(sync_result.success)
        self.assertEqual(adapter.test_calls, [])
        self.assertEqual(adapter.sync_calls, [])
        disabled = load_ntp_configuration()
        self.assertEqual(disabled.sources.station_clock_lan1, "10.12.56.1")
        self.assertEqual(disabled.status.current_status, "disabled")

    def test_sync_failure_preserves_last_successful_sync(self):
        self.save_sources()
        first = FakeTimeAdapter({"10.12.56.1": self.success})
        synchronize_now(adapter=first)
        previous_sync = load_ntp_configuration().status.last_sync_at
        failed_sync = FakeTimeAdapter(
            {"10.12.56.1": self.success},
            sync_result=TimeOperationResult(
                False,
                "需要權限。",
                permission_required=True,
                failure_scope="machine",
            ),
        )

        result = synchronize_now(adapter=failed_sync)

        self.assertFalse(result.success)
        config = load_ntp_configuration()
        self.assertEqual(config.status.current_status, "permission_required")
        self.assertEqual(config.status.last_sync_at, previous_sync)


class NtpPermissionAndUiTests(NtpConfigurationTestCase):
    def setUp(self):
        super().setUp()
        administrator_group = Group.objects.get_or_create(name="Administrator")[0]
        maintainer_group = Group.objects.get_or_create(name="Maintainer")[0]
        operator_group = Group.objects.get_or_create(name="Operator")[0]
        self.administrator = User.objects.create_user("ntp-admin", password="test")
        self.administrator.groups.add(administrator_group)
        self.maintainer = User.objects.create_user("ntp-maintainer", password="test")
        self.maintainer.groups.add(maintainer_group)
        self.operator = User.objects.create_user("ntp-operator", password="test")
        self.operator.groups.add(operator_group)
        self.superuser = User.objects.create_superuser(
            "ntp-root",
            "root@example.com",
            "test",
        )

    def valid_payload(self):
        return {
            "enabled": "on",
            "station_clock_lan1": "10.12.56.1",
            "station_clock_lan2": "10.12.56.2",
            "occ_backup_clock_lan1": "10.12.164.1",
            "occ_backup_clock_lan2": "10.12.164.2",
        }

    def test_superuser_and_administrator_can_save_configuration(self):
        for user in (self.superuser, self.administrator):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.post(
                    reverse("settings_app:save_ntp_configuration"),
                    self.valid_payload(),
                )
                self.assertEqual(response.status_code, 302)
                self.assertTrue(load_ntp_configuration().enabled)
                reset_ntp_settings()

    def test_restricted_roles_cannot_change_or_sync_configuration(self):
        for user in (self.maintainer, self.operator):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                save_response = self.client.post(
                    reverse("settings_app:save_ntp_configuration"),
                    self.valid_payload(),
                )
                sync_response = self.client.post(reverse("settings_app:sync_ntp_now"))
                self.assertEqual(save_response.status_code, 404)
                self.assertEqual(sync_response.status_code, 404)
                self.assertFalse(load_ntp_configuration().enabled)

    @mock.patch("apps.settings_app.views.test_ntp_source")
    def test_test_button_passes_validated_source_to_adapter_service(self, service):
        service.return_value = TimeOperationResult(True, "時間來源可用。")
        self.client.force_login(self.administrator)
        payload = self.valid_payload()
        payload["source_key"] = "station_clock_lan2"

        response = self.client.post(reverse("settings_app:test_ntp_source"), payload)

        self.assertEqual(response.status_code, 302)
        service.assert_called_once_with("station_clock_lan2", "10.12.56.2")

    def test_general_settings_contains_simple_ntp_card(self):
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("settings_app:station_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "時間同步設定")
        self.assertContains(response, "本站次母鐘")
        self.assertContains(response, "OCC 備援母鐘設定")
        self.assertContains(response, "本站 LAN1 → 本站 LAN2 → OCC 備援")
        self.assertContains(response, "檢查時間來源")
        self.assertContains(response, "進階資訊")
        self.assertNotContains(response, 'type="radio"')
        self.assertContains(response, "登入頁面設定")
        self.assertContains(response, "事件警示音")
        content = response.content.decode("utf-8")
        self.assertLess(
            content.index('class="toggle ntp-enable-switch"'),
            content.index("啟用 PAO 時間同步管理"),
        )
        self.assertContains(response, "data-ntp-requires-enabled")

    @mock.patch("apps.settings_app.views.synchronize_now")
    def test_sync_now_permission_failure_is_controlled(self, service):
        service.return_value = TimeOperationResult(
            False,
            "Windows Time 操作需要系統管理員權限。",
            permission_required=True,
        )
        self.client.force_login(self.administrator)

        response = self.client.post(reverse("settings_app:sync_ntp_now"))

        self.assertEqual(response.status_code, 302)
        service.assert_called_once_with()

    @mock.patch("apps.settings_app.views.check_time_sources")
    def test_one_click_check_uses_saved_configuration_service(self, service):
        service.return_value = mock.Mock(success=True, message="時間來源檢查完成。")
        self.client.force_login(self.administrator)

        response = self.client.post(reverse("settings_app:check_ntp_sources"))

        self.assertEqual(response.status_code, 302)
        service.assert_called_once_with()
