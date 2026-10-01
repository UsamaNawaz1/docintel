from django.apps import AppConfig


class SyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "docintel.apps.sync"
    label = "sync"
