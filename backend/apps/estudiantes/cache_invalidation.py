"""
Invalidación del caché de Redis ante cambios en Persona/Estudiante/Docente.

Persona es la única fuente de verdad de nombre/apellido/email (ver CLAUDE.md,
decisión P-1). Un par de endpoints cachean listados que incluyen nombre y
apellido con TTL largo (15 min y 1 hora) sin invalidar ese caché al editar la
Persona o el Estudiante subyacente, así que una corrección de nombre podía
tardar hasta una hora en reflejarse ahí. Esto conecta esos dos casos al mismo
patrón de invalidación por señales que ya usa apps/metrics.
"""

import logging

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

# Prefijos de cache_key tal como los arma cada vista:
# - curso_intro_api.py: f"ci_pendientes_u{...}_p{...}_act{...}_conf{...}_anio{...}"
# - primera_carga/services/utils.py: f"reg_metadata_u{...}_a{...}"
PATRONES = ("ci_pendientes_*", "reg_metadata_*")


def invalidar() -> int:
    """Borra las entradas de caché con nombre/apellido de Persona/Estudiante."""
    borradas = 0
    delete_pattern = getattr(cache, "delete_pattern", None)
    if delete_pattern is None:
        return 0

    for patron in PATRONES:
        try:
            borradas += delete_pattern(patron) or 0
        except Exception:  # noqa: BLE001
            logger.warning("No se pudo invalidar el cache de %s", patron, exc_info=True)
    return borradas


def _conectar():
    """Registra las señales. Se llama desde EstudiantesConfig.ready()."""
    from core.models import Estudiante, Persona

    for modelo in (Persona, Estudiante):
        _registrar(modelo)


def _registrar(modelo) -> None:
    """Conecta post_save y post_delete de un modelo a la invalidación."""
    uid = f"estudiantes_cache_{modelo._meta.label_lower}"

    @receiver(post_save, sender=modelo, weak=False, dispatch_uid=uid + "_save")
    @receiver(post_delete, sender=modelo, weak=False, dispatch_uid=uid + "_delete")
    def _handler(sender, instance, **kwargs):  # noqa: ARG001
        invalidar()
