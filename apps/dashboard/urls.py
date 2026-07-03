from django.urls import path

from .views import dashboard_home, monitor_wall


urlpatterns = [
    path("", dashboard_home, name="dashboard_home"),
    path("monitor/", monitor_wall, name="dashboard_monitor"),
]