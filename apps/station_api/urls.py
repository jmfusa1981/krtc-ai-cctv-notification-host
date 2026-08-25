from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("status/", views.status),
    path("version/", views.version),
    path("inference-hosts/", views.inference_hosts),
    path("devices/", views.devices),
    path("device-faults/", views.device_faults),
    path("device-fault-changes/", views.device_fault_changes),
    path("device-fault-catalog/", views.device_fault_catalog),
    path("audit-log-changes/", views.audit_log_changes),
    path("events/", views.events),
    path("configuration/", views.configuration),
    path("configuration/apply/", views.configuration_apply),
]
