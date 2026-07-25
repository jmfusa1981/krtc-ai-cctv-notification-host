from django.urls import path

from .views import (
    dashboard_home,
    dashboard_live_state_api,
    device_list,
    event_snapshot_list,
    monitor_wall,
)


app_name = "dashboard"

urlpatterns = [
    path("", dashboard_home, name="home"),
    path("devices/", device_list, name="device_list"),
    path("snapshots/", event_snapshot_list, name="event_snapshot_list"),
    path("monitor/", monitor_wall, name="monitor"),
    path(
        "api/live-state/",
        dashboard_live_state_api,
        name="dashboard_live_state_api",
    ),
]
