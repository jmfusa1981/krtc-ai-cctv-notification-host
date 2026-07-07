from django.urls import path

from .views import dashboard_home, dashboard_live_state_api, monitor_wall


app_name = "dashboard"

urlpatterns = [
    path("", dashboard_home, name="home"),
    path("monitor/", monitor_wall, name="monitor"),
    path(
        "api/live-state/",
        dashboard_live_state_api,
        name="dashboard_live_state_api",
    ),
]