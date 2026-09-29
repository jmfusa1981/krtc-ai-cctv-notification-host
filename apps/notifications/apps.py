from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"

    def ready(self):
        from .scheduler_runtime import start_scheduler_for_current_process

        start_scheduler_for_current_process()
