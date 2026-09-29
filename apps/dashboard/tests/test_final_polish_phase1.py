from datetime import datetime, timezone as datetime_timezone
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.cameras.models import Camera
from apps.events.models import Event


class EventSnapshotFilterTests(TestCase):
    """驗證事件快照完整計數、日期範圍與固定分頁契約。"""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "snapshot-reviewer",
            password="test-pass",
        )
        self.client.force_login(self.user)
        self.camera = Camera.objects.create(
            camera_code="CAM-KEYWORD",
            name="Keyword Camera",
            area="North Platform",
        )
        self.url = reverse("dashboard:event_snapshot_list")
        self.snapshot_url_patcher = patch(
            "apps.dashboard.views.local_snapshot_url",
            side_effect=lambda event: f"/media/{event.snapshot.name}",
        )
        self.snapshot_url_patcher.start()
        self.addCleanup(self.snapshot_url_patcher.stop)

    def create_snapshot_events(self, count, created_at, event_type="other"):
        events = Event.objects.bulk_create(
            [
                Event(
                    camera=self.camera,
                    event_type=event_type,
                    snapshot=f"event_snapshots/snapshot-{created_at.timestamp()}-{index}.jpg",
                    detected_at=created_at,
                )
                for index in range(count)
            ]
        )
        Event.objects.filter(pk__in=[event.pk for event in events]).update(
            created_at=created_at
        )
        return events

    def test_true_count_over_200_and_fifty_item_pagination(self):
        created_at = datetime(2026, 9, 1, 4, 0, tzinfo=datetime_timezone.utc)
        self.create_snapshot_events(205, created_at)

        first_page = self.client.get(
            self.url,
            {
                "q": "CAM-KEYWORD",
                "start_date": "2026-09-01",
                "end_date": "2026-09-01",
            },
        )
        second_page = self.client.get(
            self.url,
            {
                "start_date": "2026-09-01",
                "end_date": "2026-09-01",
                "q": "CAM-KEYWORD",
                "page": "2",
            },
        )

        self.assertEqual(first_page.context["snapshot_count"], 205)
        self.assertEqual(len(first_page.context["snapshot_events"]), 50)
        self.assertEqual(second_page.context["page_obj"].number, 2)
        self.assertEqual(len(second_page.context["snapshot_events"]), 50)
        self.assertContains(first_page, "q=CAM-KEYWORD")
        self.assertContains(first_page, "start_date=2026-09-01")
        self.assertContains(first_page, "end_date=2026-09-01")

    def test_keyword_and_individual_date_filters(self):
        september_first = datetime(2026, 9, 1, 4, 0, tzinfo=datetime_timezone.utc)
        september_second = datetime(2026, 9, 2, 4, 0, tzinfo=datetime_timezone.utc)
        self.create_snapshot_events(1, september_first, "fire_detected")
        self.create_snapshot_events(1, september_second, "other")

        keyword_response = self.client.get(
            self.url,
            {"q": "火災"},
        )
        start_response = self.client.get(
            self.url,
            {"start_date": "2026-09-02"},
        )
        end_response = self.client.get(
            self.url,
            {"end_date": "2026-09-01"},
        )

        self.assertEqual(keyword_response.context["snapshot_count"], 1)
        self.assertEqual(start_response.context["snapshot_count"], 1)
        self.assertEqual(end_response.context["snapshot_count"], 1)

    def test_combined_keyword_and_same_day_range(self):
        same_day = datetime(2026, 9, 3, 8, 0, tzinfo=datetime_timezone.utc)
        next_day = datetime(2026, 9, 4, 8, 0, tzinfo=datetime_timezone.utc)
        self.create_snapshot_events(2, same_day, "fire_detected")
        self.create_snapshot_events(1, next_day, "fire_detected")

        response = self.client.get(
            self.url,
            {
                "q": "CAM-KEYWORD",
                "start_date": "2026-09-03",
                "end_date": "2026-09-03",
            },
        )

        self.assertEqual(response.context["snapshot_count"], 2)
        self.assertEqual(response.context["snapshot_keyword"], "CAM-KEYWORD")
        self.assertContains(response, 'value="CAM-KEYWORD"')

    def test_invalid_reverse_range_returns_clear_error(self):
        response = self.client.get(
            self.url,
            {"start_date": "2026-09-04", "end_date": "2026-09-03"},
        )

        self.assertEqual(response.context["snapshot_count"], 0)
        self.assertContains(response, "開始日期不得晚於結束日期。")

    def test_asia_taipei_boundaries_are_start_inclusive_end_exclusive(self):
        before_start = datetime(2026, 8, 31, 15, 59, 59, tzinfo=datetime_timezone.utc)
        at_start = datetime(2026, 8, 31, 16, 0, tzinfo=datetime_timezone.utc)
        before_end = datetime(2026, 9, 1, 15, 59, 59, tzinfo=datetime_timezone.utc)
        at_end = datetime(2026, 9, 1, 16, 0, tzinfo=datetime_timezone.utc)
        for moment in (before_start, at_start, before_end, at_end):
            self.create_snapshot_events(1, moment)

        response = self.client.get(
            self.url,
            {"start_date": "2026-09-01", "end_date": "2026-09-01"},
        )

        timestamps = {event.created_at for event in response.context["snapshot_events"]}
        self.assertEqual(response.context["snapshot_count"], 2)
        self.assertIn(at_start, timestamps)
        self.assertIn(before_end, timestamps)
        self.assertNotIn(before_start, timestamps)
        self.assertNotIn(at_end, timestamps)


class LandscapeOnlyContractTests(SimpleTestCase):
    """驗證所有公開畫面只保留橫式runtime且沒有方向切換控制。"""

    def test_portrait_controls_are_not_rendered(self):
        template_paths = (
            "templates/registration/login.html",
            "templates/dashboard/monitor.html",
            "templates/dashboard/includes/system_header.html",
        )
        for relative_path in template_paths:
            source = (Path(settings.BASE_DIR) / relative_path).read_text(
                encoding="utf-8"
            )
            self.assertNotIn("data-display-mode-toggle", source)
            self.assertNotIn('data-display-mode-option="portrait"', source)

    def test_runtime_normalizes_storage_to_landscape_without_detection(self):
        source = (
            Path(settings.BASE_DIR) / "static/js/display_mode.js"
        ).read_text(encoding="utf-8")

        self.assertIn('root.dataset.displayMode = "landscape"', source)
        self.assertIn('localStorage.setItem(storageKey, "landscape")', source)
        self.assertNotIn("portrait", source)
        self.assertNotIn("matchMedia", source)
        self.assertNotIn("orientationchange", source)
        self.assertNotIn("screen.orientation", source)

    def test_monitor_grid_and_mosaic_contract_remains_available(self):
        template = (
            Path(settings.BASE_DIR) / "templates/dashboard/monitor.html"
        ).read_text(encoding="utf-8")
        script = (
            Path(settings.BASE_DIR) / "static/js/monitor.js"
        ).read_text(encoding="utf-8")

        for grid_size in ("1", "4", "9", "16"):
            self.assertIn(f'data-grid="{grid_size}"', template)
        self.assertEqual(template.count('id="monitorMosaicStream"'), 1)
        self.assertIn("moveSidebarCameraToMosaicSlot", script)
