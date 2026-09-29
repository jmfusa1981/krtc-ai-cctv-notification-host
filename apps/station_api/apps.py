from django.apps import AppConfig


class StationApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.station_api"

    def ready(self):
        from .service_watchdog import start_service_watchdog_for_current_process

        start_service_watchdog_for_current_process()

