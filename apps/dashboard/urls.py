from .developer_entry import developer_entry
from django.urls import path

from .event_records import (
    event_record_list,
    export_event_records_csv,
    export_event_records_excel,
)
from .system_logs import system_log_list
from .views import (
    dashboard_home,
    dashboard_live_state_api,
    device_list,
    event_snapshot_list,
    monitor_wall,
    station_broadcast_console,
)


app_name = "dashboard"

urlpatterns = [
    path("developer-entry/", developer_entry, name="developer_entry"),
    path("", dashboard_home, name="home"),
    path("devices/", device_list, name="device_list"),
    path("snapshots/", event_snapshot_list, name="event_snapshot_list"),
    path("records/", event_record_list, name="event_record_list"),
    path("system-log/", system_log_list, name="system_log_list"),
    path(
        "records/export/csv/",
        export_event_records_csv,
        name="export_event_records_csv",
    ),
    path(
        "records/export/excel/",
        export_event_records_excel,
        name="export_event_records_excel",
    ),
    path("broadcast/", station_broadcast_console, name="station_broadcast"),
    path("monitor/", monitor_wall, name="monitor"),
    path(
        "api/live-state/",
        dashboard_live_state_api,
        name="dashboard_live_state_api",
    ),
]
