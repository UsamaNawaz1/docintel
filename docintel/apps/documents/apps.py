from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "docintel.apps.documents"
    label = "documents"

    def ready(self) -> None:
        # Registration is a side effect of import. Importing here, not at
        # module import of models, avoids an app-loading cycle.
        from docintel.apps.documents import importers as _importers

        del _importers
