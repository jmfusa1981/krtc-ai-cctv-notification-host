from django.urls import path

from . import views


app_name = "events"

urlpatterns = [
    path("trigger/", views.ai_event_trigger_api, name="ai_event_trigger_api"),
]