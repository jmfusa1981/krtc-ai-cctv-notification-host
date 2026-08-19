from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("status/", views.status),
    path("version/", views.version),
    path("inference-hosts/", views.inference_hosts),
    path("devices/", views.devices),
    path("events/", views.events),
    path("configuration/", views.configuration),
    path("configuration/apply/", views.configuration_apply),
]
