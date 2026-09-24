"""Utilidad compartida: inscripciones a materias vigentes de un estudiante en una carrera.

Se usa para impedir que un estudiante quede en un estado académico no activo
(baja, inactivo, suspendido, egresado) mientras sigue inscripto a materias de esa
misma carrera. Primero hay que darlo de baja en las materias, después cambiar el
estado de la carrera.
"""

from django.utils import timezone

from core.models.inscripciones import InscripcionMateriaEstudiante

# Estados de inscripción que representan una cursada vigente.
ESTADOS_INSCRIPCION_VIGENTE = [
    InscripcionMateriaEstudiante.Estado.CONFIRMADA,
    InscripcionMateriaEstudiante.Estado.PENDIENTE,
    InscripcionMateriaEstudiante.Estado.CONDICIONAL,
]


def inscripciones_vigentes(estudiante_id: int, profesorado_id: int, anio: int | None = None):
    """Inscripciones vigentes del estudiante a materias de ese profesorado en el año dado."""
    return (
        InscripcionMateriaEstudiante.objects.filter(
            estudiante_id=estudiante_id,
            anio=anio if anio is not None else timezone.now().year,
            materia__plan_de_estudio__profesorado_id=profesorado_id,
            estado__in=ESTADOS_INSCRIPCION_VIGENTE,
        )
        .select_related("materia")
        .order_by("materia__nombre")
    )
