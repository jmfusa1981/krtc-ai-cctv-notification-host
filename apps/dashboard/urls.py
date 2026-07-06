from django.urls import path

from .views import dashboard_home, monitor_wall


app_name = "dashboard"

urlpatterns = [
    path("", dashboard_home, name="home"),
    path("monitor/", monitor_wall, name="monitor"),
]