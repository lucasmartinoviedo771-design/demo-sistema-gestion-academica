from django.apps import AppConfig


class EstudiantesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.estudiantes"

    def ready(self):
        """Conecta la invalidación del cache de listados que incluyen nombre/apellido."""
        from apps.estudiantes.cache_invalidation import _conectar

        _conectar()
