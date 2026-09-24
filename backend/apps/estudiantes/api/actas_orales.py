from datetime import date

from django.http import HttpResponse
from django.template.loader import render_to_string
from ninja import Body, Router, Schema
from ninja.errors import HttpError

from apps.common.api_schemas import ApiResponse
from apps.estudiantes.schemas import (
    ActaOralListItemSchema,
    ActaOralSchema,
)
from core.auth_ninja import JWTAuth
from core.models import BorradorActaOral, InscripcionMesa, MesaActaOral, MesaExamen

# ==============================================================================
# LOGIC & ENDPOINTS
# ==============================================================================

router = Router(tags=["carga_notas"])


def _get_inscripcion_mesa_or_404(mesa_id: int, inscripcion_id: int) -> InscripcionMesa:
    inscripcion = (
        InscripcionMesa.objects.select_related(
            "mesa__materia__plan_de_estudio__profesorado",
            "estudiante__persona",
            "estudiante__user",
        )
        .filter(id=inscripcion_id, mesa_id=mesa_id)
        .first()
    )
    if not inscripcion:
        raise HttpError(404, "La inscripcion indicada no pertenece a la mesa seleccionada.")
    return inscripcion


def _check_acta_oral_access(user, inscripcion, allow_estudiante: bool = True) -> bool:
    """Valida si el usuario tiene permiso para acceder a los datos del acta oral."""
    if not user or not user.is_authenticated:
        return False

    from apps.estudiantes.api.helpers.user_utils import _resolve_docente_from_user
    from core.permissions import allowed_profesorados, get_user_roles

    roles = get_user_roles(user)

    # 1. Estudiante titular
    if allow_estudiante:
        est = getattr(inscripcion, "estudiante", None)
        est_dni = getattr(getattr(est, "persona", None), "dni", "") or getattr(est, "dni", "")
        if est_dni and est_dni == getattr(user, "username", ""):
            return True
        if est and getattr(est, "user_id", None) == user.id:
            return True

    # Si es estudiante y no es el titular, denegado — pero solo cuando
    # "estudiante" es el único rol relevante que tiene. Alguien con doble rol
    # (ej. un docente que también cursa una carrera, como Cazón: docente +
    # estudiante) no debe quedar bloqueado acá antes de que se evalúe su
    # rol docente más abajo — si no, un presidente de mesa con perfil de
    # estudiante no podía ni ver su propia acta oral ya cargada.
    otros_roles_relevantes = roles & {
        "admin",
        "secretaria",
        "docente",
        "bedel",
        "coordinador",
        "jefa_aaee",
        "bedel_secretaria",
    }
    if ("estudiante" in roles or "estudiantes" in roles) and not otros_roles_relevantes:
        return False

    # 2. Superusuario, Administrador o Secretaría (acceso institucional total)
    if user.is_superuser or (roles & {"admin", "secretaria"}):
        return True

    mesa = inscripcion.mesa
    carrera_id = None
    if mesa and mesa.materia and mesa.materia.plan_de_estudio:
        carrera_id = mesa.materia.plan_de_estudio.profesorado_id

    # 3. Tribunal docente (Presidente o Vocales de la mesa)
    if "docente" in roles:
        doc = _resolve_docente_from_user(user)
        if doc and mesa and doc.id in (mesa.docente_presidente_id, mesa.docente_vocal1_id, mesa.docente_vocal2_id):
            return True

    # 4. Staff con alcance de carrera (Bedeles, Coordinadores)
    if roles & {"bedel", "coordinador", "jefa_aaee", "bedel_secretaria"}:
        allowed = allowed_profesorados(user)
        if allowed is None or (carrera_id and carrera_id in allowed):
            return True

    return False


def _check_acta_oral_print_access(user) -> bool:
    """
    Valida si el usuario puede LISTAR/IMPRIMIR (descargar PDF) las actas
    orales de una mesa — a diferencia de _check_acta_oral_access (que
    habilita al tribunal a ver/editar su propia carga), esto es
    deliberadamente más restrictivo: solo admin, secretaría y títulos.
    Ni el tribunal docente ni bedel/coordinador pueden imprimir desde acá.
    """
    if not user or not user.is_authenticated:
        return False
    from core.permissions import get_user_roles

    roles = get_user_roles(user)
    return bool(user.is_superuser or (roles & {"admin", "secretaria", "titulos"}))


def _check_mesa_actas_access(user, mesa) -> bool:
    """Valida si el usuario puede listar/imprimir las actas de una mesa (ver _check_acta_oral_print_access)."""
    return _check_acta_oral_print_access(user)


from datetime import timedelta

from django.utils import timezone

from apps.estudiantes.schemas import (
    ActaOralPendienteConformidadSchema,
    ResponderConformidadPayload,
)

# Plazo que tiene CADA estudiante para prestar conformidad, contado desde que se
# guarda su propia acta (notificado_en es por acta, no por mesa).
PLAZO_CONFORMIDAD = timedelta(minutes=10)


def vencer_actas_orales_expiradas(actas, ahora=None) -> int:
    """
    Cierra por timeout las actas orales PENDIENTE cuyo plazo ya venció.

    El vencimiento es lazy: no hay proceso de fondo que lo aplique, así que se
    resuelve cada vez que alguien consulta las pendientes o intenta cerrar la
    planilla. Devuelve cuántas se cerraron.
    """
    ahora = ahora or timezone.now()
    cerradas = 0
    for acta in actas:
        if acta.estado_conformidad != MesaActaOral.EstadoConformidad.PENDIENTE:
            continue
        if not acta.notificado_en:
            # Fallback en caso excepcional: se arranca el plazo ahora.
            acta.notificado_en = ahora
            acta.save(update_fields=["notificado_en"])
            continue
        vencimiento = acta.notificado_en + PLAZO_CONFORMIDAD
        if (vencimiento - ahora).total_seconds() <= 0:
            acta.estado_conformidad = MesaActaOral.EstadoConformidad.TIMEOUT
            acta.respondido_en = vencimiento
            acta.save(update_fields=["estado_conformidad", "respondido_en", "updated_at"])
            cerradas += 1
    return cerradas


@router.get(
    "/mesas/{mesa_id}/oral-actas/{inscripcion_id}",
    response={200: ActaOralSchema, 400: ApiResponse, 403: ApiResponse, 404: ApiResponse},
    auth=JWTAuth(),
)
def obtener_acta_oral(request, mesa_id: int, inscripcion_id: int):
    try:
        inscripcion = _get_inscripcion_mesa_or_404(mesa_id, inscripcion_id)
    except HttpError as exc:
        return exc.status_code, ApiResponse(ok=False, message=str(exc))

    if not _check_acta_oral_access(request.user, inscripcion, allow_estudiante=True):
        return 403, ApiResponse(ok=False, message="No tienes permisos para consultar esta acta oral.")

    acta: MesaActaOral | None = getattr(inscripcion, "acta_oral", None)
    if not acta:
        return 404, ApiResponse(ok=False, message="Acta oral no registrada para el estudiante.")

    return ActaOralSchema(
        acta_numero=acta.acta_numero or None,
        folio_numero=acta.folio_numero or None,
        fecha=acta.fecha,
        curso=acta.curso or None,
        nota_final=acta.nota_final or None,
        observaciones=acta.observaciones or None,
        temas_estudiante=acta.temas_alumno or [],
        temas_docente=acta.temas_docente or [],
        estado_conformidad=acta.estado_conformidad,
        notificado_en=acta.notificado_en.isoformat() if acta.notificado_en else None,
        respondido_en=acta.respondido_en.isoformat() if acta.respondido_en else None,
        observaciones_estudiante=acta.observaciones_estudiante or None,
    )


def _check_acta_oral_write_access(user, inscripcion) -> tuple[bool, bool]:
    """
    Determina si el usuario puede cargar/modificar el acta oral de esta
    inscripcion. Devuelve (puede_escribir, es_admin_global) — el segundo
    valor lo usan los llamadores para decisiones adicionales (ej. reabrir
    un acta ya cerrada).
    """
    from apps.estudiantes.api.helpers.user_utils import _resolve_docente_from_user
    from core.permissions import allowed_profesorados, get_user_roles

    mesa = inscripcion.mesa
    carrera_id = None
    if mesa and mesa.materia and mesa.materia.plan_de_estudio:
        carrera_id = mesa.materia.plan_de_estudio.profesorado_id

    roles = get_user_roles(user)
    is_global_admin = user.is_superuser or bool(roles & {"admin", "secretaria"})

    can_write = False
    if is_global_admin:
        can_write = True
    elif "docente" in roles:
        docente_actual = _resolve_docente_from_user(user)
        if docente_actual and mesa.docente_presidente_id == docente_actual.id:
            can_write = True
    elif roles & {"bedel", "coordinador", "jefa_aaee", "bedel_secretaria"}:
        allowed = allowed_profesorados(user)
        if allowed is None or (carrera_id and carrera_id in allowed):
            can_write = True

    return can_write, is_global_admin


@router.post(
    "/mesas/{mesa_id}/oral-actas/{inscripcion_id}",
    response={200: ApiResponse, 400: ApiResponse, 403: ApiResponse, 404: ApiResponse},
    auth=JWTAuth(),
)
def guardar_acta_oral(request, mesa_id: int, inscripcion_id: int, payload: ActaOralSchema = Body(...)):
    try:
        inscripcion = _get_inscripcion_mesa_or_404(mesa_id, inscripcion_id)
    except HttpError as exc:
        return exc.status_code, ApiResponse(ok=False, message=str(exc))

    if inscripcion.estudiante.dni == getattr(request.user, "username", ""):
        return 403, ApiResponse(ok=False, message="No tienes permitido cargar o modificar tus propias actas orales.")

    can_write, is_global_admin = _check_acta_oral_write_access(request.user, inscripcion)
    if not can_write:
        return 403, ApiResponse(
            ok=False, message="No tienes permisos para cargar o modificar actas orales de esta mesa."
        )

    temas_estudiante = [
        {"tema": item.tema, "score": item.score} for item in (payload.temas_estudiante or []) if item.tema
    ]
    temas_docente = [{"tema": item.tema, "score": item.score} for item in (payload.temas_docente or []) if item.tema]

    acta_existente = MesaActaOral.objects.filter(inscripcion=inscripcion).first()
    ahora = timezone.now()

    nueva_nota = payload.nota_final or ""
    nuevas_obs = payload.observaciones or ""

    # Si el acta ya existe y está cerrada (CON, DIS, TIM), eso manda antes
    # que cualquier otra validación: solo Administración/Secretaría puede
    # tocarla, sin importar si el payload que mandan está bien formado o no.
    # Antes esto se chequeaba después de validar nota/temas, así que un
    # docente ajeno podía mandar un payload "inválido" (sin temas) contra un
    # acta cerrada y recibía 400 en vez del 403 real de "no autorizado".
    if acta_existente:
        acta_esta_cerrada = acta_existente.estado_conformidad != MesaActaOral.EstadoConformidad.PENDIENTE
        if acta_esta_cerrada and not is_global_admin:
            return 403, ApiResponse(
                ok=False,
                message="El acta oral ya se encuentra cerrada y asentada. No puede modificarse sin autorización expresa de Secretaría.",
            )

    # No permitir generar/notificar un acta sin nota: si queda en blanco, el
    # plazo de 10 minutos para conformidad del estudiante la cierra igual por
    # timeout, dejando un acta "cerrada" sin contenido que ningún docente
    # puede corregir después (solo Secretaría) — se corta el problema acá,
    # antes de que se dispare el plazo.
    if not nueva_nota.strip():
        return 400, ApiResponse(
            ok=False,
            message="Debe cargar la nota final antes de generar el acta oral.",
        )

    # Además de la nota, exigimos que al menos uno de los dos bloques de
    # temas (elegidos por el estudiante o sugeridos por el docente) tenga
    # contenido real — evita un acta "aprobada a ciegas" sin ningún tema
    # de examen registrado en ninguno de los dos lados. No aplica a
    # Administración/Secretaría: ya tienen permiso para todo, y esta
    # validación existe para la carga normal del docente, no para que
    # Secretaría quede trabada corrigiendo un acta que ya está cerrada.
    if not is_global_admin and not temas_estudiante and not temas_docente:
        return 400, ApiResponse(
            ok=False,
            message="Debe cargar al menos un tema (elegido por el estudiante o sugerido por el docente) antes de generar el acta oral.",
        )

    if not acta_existente:
        # Creación inicial
        MesaActaOral.objects.create(
            inscripcion=inscripcion,
            mesa=inscripcion.mesa,
            acta_numero=payload.acta_numero or "",
            folio_numero=payload.folio_numero or "",
            fecha=payload.fecha,
            curso=payload.curso or "",
            nota_final=nueva_nota,
            observaciones=nuevas_obs,
            temas_alumno=temas_estudiante,
            temas_docente=temas_docente,
            estado_conformidad=MesaActaOral.EstadoConformidad.PENDIENTE,
            notificado_en=ahora,
            respondido_en=None,
            observaciones_estudiante="",
        )
    else:
        # El chequeo de "acta cerrada -> solo admin/secretaría" ya se hizo
        # más arriba, antes de validar nota/temas.
        # Edición: verificar si cambió contenido sustancial (nota, observaciones o temas_docente)
        cambio_sustancial = (
            (acta_existente.nota_final != nueva_nota)
            or (acta_existente.observaciones != nuevas_obs)
            or (acta_existente.temas_docente != temas_docente)
        )

        update_defaults = {
            "mesa": inscripcion.mesa,
            "acta_numero": payload.acta_numero or "",
            "folio_numero": payload.folio_numero or "",
            "fecha": payload.fecha,
            "curso": payload.curso or "",
            "nota_final": nueva_nota,
            "observaciones": nuevas_obs,
            "temas_alumno": temas_estudiante,
            "temas_docente": temas_docente,
        }

        # Si Secretaría/Admin modifica un acta cerrada con cambios sustanciales, se reabre la conformidad
        if cambio_sustancial or not acta_existente.notificado_en:
            update_defaults["estado_conformidad"] = MesaActaOral.EstadoConformidad.PENDIENTE
            update_defaults["notificado_en"] = ahora
            update_defaults["respondido_en"] = None
            update_defaults["observaciones_estudiante"] = ""

        for key, val in update_defaults.items():
            setattr(acta_existente, key, val)
        acta_existente.save()

    # El acta oral ya quedó asentada: el borrador provisorio (si existía)
    # queda obsoleto. No se borra, se desactiva.
    BorradorActaOral.objects.filter(inscripcion=inscripcion, activo=True).update(activo=False)

    # Se escribe la nota del acta oral en el campo "Examen oral" del acta
    # final de este estudiante, para que ambas queden sincronizadas — así
    # no depende de que alguien la tipee dos veces, y la validación de
    # "si tiene nota oral en el acta final, debe tener el acta oral
    # cargada" se cumple sola para quien pasa por este flujo.
    _sync_examen_oral_en_acta_final(inscripcion, nueva_nota)

    return 200, ApiResponse(ok=True, message="Acta oral guardada correctamente.")


def _sync_examen_oral_en_acta_final(inscripcion, nota_final: str) -> None:
    """Escribe la nota del acta oral en el campo examen_oral del acta final del estudiante, si existe una."""
    import re

    from core.models import ActaExamen, ActaExamenEstudiante

    mesa = inscripcion.mesa
    acta = ActaExamen.objects.filter(materia_id=mesa.materia_id, fecha=mesa.fecha, tipo=mesa.modalidad).first()
    if not acta:
        return

    dni = getattr(getattr(inscripcion.estudiante, "persona", None), "dni", None)
    if not dni:
        return

    match = re.match(r"\s*(\d+)", nota_final or "")
    valor = match.group(1) if match else (nota_final or "")

    ActaExamenEstudiante.objects.filter(acta=acta, dni=dni).update(examen_oral=valor)


def _csv_temas_a_lineas(temas) -> str:
    """Serializa una lista de {tema, score} a texto plano "tema|score" por línea."""
    lineas = []
    for item in temas or []:
        tema = (item.tema or "").replace("|", "/").replace("\n", " ") if hasattr(item, "tema") else ""
        score = (item.score or "") if hasattr(item, "score") else ""
        if tema:
            lineas.append(f"{tema}|{score}")
    return "\n".join(lineas)


def _csv_lineas_a_temas(csv_text: str) -> list[dict]:
    """Parsea el texto plano "tema|score" por línea de vuelta a lista de dicts."""
    temas = []
    for linea in (csv_text or "").splitlines():
        if not linea.strip():
            continue
        partes = linea.split("|", 1)
        tema = partes[0].strip()
        score = partes[1].strip() if len(partes) > 1 else ""
        if tema:
            temas.append({"tema": tema, "score": score or None})
    return temas


@router.get(
    "/mesas/{mesa_id}/oral-actas/{inscripcion_id}/borrador",
    response={200: ActaOralSchema, 403: ApiResponse, 404: ApiResponse},
    auth=JWTAuth(),
)
def obtener_borrador_acta_oral(request, mesa_id: int, inscripcion_id: int):
    """Recupera el último avance guardado (aún no generado) del acta oral, si existe."""
    try:
        inscripcion = _get_inscripcion_mesa_or_404(mesa_id, inscripcion_id)
    except HttpError as exc:
        return exc.status_code, ApiResponse(ok=False, message=str(exc))

    can_write, _ = _check_acta_oral_write_access(request.user, inscripcion)
    if not can_write:
        return 403, ApiResponse(ok=False, message="No tienes permisos para consultar este borrador.")

    borrador = BorradorActaOral.objects.filter(inscripcion=inscripcion, activo=True).first()
    if not borrador:
        return 404, ApiResponse(ok=False, message="No hay borrador guardado para este estudiante.")

    return ActaOralSchema(
        acta_numero=borrador.acta_numero or None,
        folio_numero=borrador.folio_numero or None,
        fecha=borrador.fecha or None,
        curso=borrador.curso or None,
        nota_final=borrador.nota_final or None,
        observaciones=borrador.observaciones or None,
        temas_estudiante=_csv_lineas_a_temas(borrador.temas_alumno_csv),
        temas_docente=_csv_lineas_a_temas(borrador.temas_docente_csv),
    )


@router.post(
    "/mesas/{mesa_id}/oral-actas/{inscripcion_id}/borrador",
    response={200: ApiResponse, 403: ApiResponse, 404: ApiResponse},
    auth=JWTAuth(),
)
def guardar_borrador_acta_oral(request, mesa_id: int, inscripcion_id: int, payload: ActaOralSchema = Body(...)):
    """
    Guarda el avance del acta oral SIN generarla ni disparar el plazo de
    conformidad del estudiante — a diferencia de guardar_acta_oral, esto no
    valida que esté completa (puede guardarse a medio cargar) y se puede
    llamar tantas veces como haga falta mientras el docente va y viene entre
    mesas.
    """
    try:
        inscripcion = _get_inscripcion_mesa_or_404(mesa_id, inscripcion_id)
    except HttpError as exc:
        return exc.status_code, ApiResponse(ok=False, message=str(exc))

    can_write, _ = _check_acta_oral_write_access(request.user, inscripcion)
    if not can_write:
        return 403, ApiResponse(ok=False, message="No tienes permisos para guardar este borrador.")

    BorradorActaOral.objects.update_or_create(
        inscripcion=inscripcion,
        defaults={
            "mesa_id": mesa_id,
            "acta_numero": payload.acta_numero or "",
            "folio_numero": payload.folio_numero or "",
            "fecha": payload.fecha.isoformat() if payload.fecha else "",
            "curso": payload.curso or "",
            "nota_final": payload.nota_final or "",
            "observaciones": payload.observaciones or "",
            "temas_alumno_csv": _csv_temas_a_lineas(payload.temas_estudiante),
            "temas_docente_csv": _csv_temas_a_lineas(payload.temas_docente),
            "activo": True,
            "guardado_por": request.user,
        },
    )

    return 200, ApiResponse(ok=True, message="Avance guardado.")


@router.get(
    "/conformidad/pendientes",
    response={200: list[ActaOralPendienteConformidadSchema], 400: ApiResponse},
    auth=JWTAuth(),
)
def listar_actas_pendientes_conformidad(request):
    """
    Lista las actas orales pendientes de conformidad para el estudiante autenticado.
    Aplica cierre lazy de aquellas que hayan superado los 10 minutos.
    """
    user = request.user
    dni = getattr(user, "username", "")
    if not dni:
        return []

    ahora = timezone.now()
    diez_minutos = PLAZO_CONFORMIDAD

    actas_pendientes = (
        MesaActaOral.objects.filter(
            inscripcion__estudiante__persona__dni=dni,
            estado_conformidad=MesaActaOral.EstadoConformidad.PENDIENTE,
        )
        .select_related(
            "mesa__materia__plan_de_estudio__profesorado",
            "mesa__docente_presidente__persona",
            "mesa__docente_vocal1__persona",
            "mesa__docente_vocal2__persona",
            "inscripcion",
        )
        .order_by("notificado_en")
    )

    resultados: list[ActaOralPendienteConformidadSchema] = []

    for acta in actas_pendientes:
        if not acta.notificado_en:
            # Fallback en caso excepcional
            acta.notificado_en = ahora
            acta.save(update_fields=["notificado_en"])

        vencimiento = acta.notificado_en + diez_minutos
        segundos_restantes = int((vencimiento - ahora).total_seconds())

        if segundos_restantes <= 0:
            # Cierre lazy automático por timeout
            acta.estado_conformidad = MesaActaOral.EstadoConformidad.TIMEOUT
            acta.respondido_en = vencimiento
            acta.save(update_fields=["estado_conformidad", "respondido_en", "updated_at"])
            continue

        mesa = acta.mesa
        materia = mesa.materia
        profesorado = materia.plan_de_estudio.profesorado if materia and materia.plan_de_estudio else None

        tribunal = []
        for doc in [mesa.docente_presidente, mesa.docente_vocal1, mesa.docente_vocal2]:
            if doc and doc.persona:
                tribunal.append(f"{doc.persona.apellido}, {doc.persona.nombre}")

        resultados.append(
            ActaOralPendienteConformidadSchema(
                acta_id=acta.id,
                inscripcion_id=acta.inscripcion_id,
                mesa_id=acta.mesa_id,
                materia_nombre=materia.nombre if materia else "Materia",
                profesorado_nombre=profesorado.nombre if profesorado else "",
                fecha=acta.fecha,
                curso=acta.curso or mesa.codigo or None,
                tribunal=tribunal,
                nota_final=acta.nota_final or None,
                observaciones_docente=acta.observaciones or None,
                temas_estudiante=acta.temas_alumno or [],
                temas_docente=acta.temas_docente or [],
                notificado_en=acta.notificado_en.isoformat(),
                segundos_restantes=segundos_restantes,
            )
        )

    return resultados


@router.post(
    "/conformidad/{acta_id}/responder",
    response={200: ApiResponse, 400: ApiResponse, 403: ApiResponse, 404: ApiResponse},
    auth=JWTAuth(),
)
def responder_conformidad_acta_oral(request, acta_id: int, payload: ResponderConformidadPayload = Body(...)):
    """
    Registra la conformidad o disconformidad del estudiante sobre un acta oral.
    Valida autoritariamente contra la hora del servidor (máx 10 minutos).
    """
    user = request.user
    dni = getattr(user, "username", "")

    acta = MesaActaOral.objects.select_related("inscripcion__estudiante__persona").filter(id=acta_id).first()

    if not acta:
        return 404, ApiResponse(ok=False, message="Acta oral no encontrada.")

    if acta.inscripcion.estudiante.persona.dni != dni:
        return 403, ApiResponse(ok=False, message="No tienes permisos para responder sobre esta acta oral.")

    if acta.estado_conformidad != MesaActaOral.EstadoConformidad.PENDIENTE:
        return 400, ApiResponse(
            ok=False,
            message="El acta oral ya se encuentra cerrada y no admite modificaciones de conformidad.",
        )

    ahora = timezone.now()
    diez_minutos = timedelta(minutes=10)
    vencimiento = (acta.notificado_en or acta.created_at) + diez_minutos

    if ahora > vencimiento:
        # Expiró la ventana de 10 minutos: se cierra como TIMEOUT
        acta.estado_conformidad = MesaActaOral.EstadoConformidad.TIMEOUT
        acta.respondido_en = vencimiento
        acta.save(update_fields=["estado_conformidad", "respondido_en", "updated_at"])
        return 400, ApiResponse(
            ok=False,
            message="La ventana de 10 minutos ha expirado. El acta quedó notificada y sin objeción por tiempo cumplido.",
        )

    # Respuesta válida dentro de los 10 minutos
    if payload.conformidad == "CON":
        acta.estado_conformidad = MesaActaOral.EstadoConformidad.CONFORME
        acta.observaciones_estudiante = ""
    elif payload.conformidad == "DIS":
        acta.estado_conformidad = MesaActaOral.EstadoConformidad.DISCONFORME
        acta.observaciones_estudiante = payload.observaciones or ""
    else:
        return 400, ApiResponse(ok=False, message="Opción de conformidad no válida.")

    acta.respondido_en = ahora
    acta.save(update_fields=["estado_conformidad", "respondido_en", "observaciones_estudiante", "updated_at"])

    return ApiResponse(ok=True, message="Conformidad registrada exitosamente.")


@router.get(
    "/mesas/{mesa_id}/oral-actas",
    response={200: list[ActaOralListItemSchema], 400: ApiResponse, 403: ApiResponse, 404: ApiResponse},
    auth=JWTAuth(),
)
def listar_actas_orales(request, mesa_id: int):
    mesa = MesaExamen.objects.select_related("materia__plan_de_estudio__profesorado").filter(id=mesa_id).first()
    if not mesa:
        return 404, ApiResponse(ok=False, message="Mesa no encontrada.")

    if not _check_mesa_actas_access(request.user, mesa):
        return 403, ApiResponse(ok=False, message="No tienes permisos para listar las actas de esta mesa.")

    actas = (
        MesaActaOral.objects.filter(mesa_id=mesa_id)
        .select_related("inscripcion__estudiante__persona")
        .order_by(
            "inscripcion__estudiante__persona__apellido",
            "inscripcion__estudiante__persona__nombre",
        )
    )

    payload: list[ActaOralListItemSchema] = []
    for acta in actas:
        estudiante = acta.inscripcion.estudiante
        full_name = f"{estudiante.apellido}, {estudiante.nombre}".strip(", ") or f"DNI {estudiante.dni}"
        payload.append(
            ActaOralListItemSchema(
                inscripcion_id=acta.inscripcion_id,
                estudiante=full_name,
                dni=estudiante.dni,
                acta_numero=acta.acta_numero or None,
                folio_numero=acta.folio_numero or None,
                fecha=acta.fecha,
                curso=acta.curso or None,
                nota_final=acta.nota_final or None,
            )
        )

    return payload


@router.get(
    "/mesas/{mesa_id}/oral-actas/{inscripcion_id}/pdf",
    auth=JWTAuth(),
)
def descargar_acta_oral_pdf(request, mesa_id: int, inscripcion_id: int):
    import os

    from django.conf import settings
    from weasyprint import HTML

    try:
        inscripcion = _get_inscripcion_mesa_or_404(mesa_id, inscripcion_id)
    except HttpError as exc:
        return exc.status_code, ApiResponse(ok=False, message=str(exc))

    # Imprimir/descargar el PDF es más restrictivo que ver/editar el acta:
    # solo admin, secretaría y títulos (además del propio estudiante
    # titular, si en el futuro se habilita esa descarga desde su portal).
    est = getattr(inscripcion, "estudiante", None)
    est_dni = getattr(getattr(est, "persona", None), "dni", "") or getattr(est, "dni", "")
    es_propio_estudiante = bool(est_dni) and est_dni == getattr(request.user, "username", "")
    if not es_propio_estudiante and not _check_acta_oral_print_access(request.user):
        return HttpResponse("No tienes permisos para descargar esta acta oral.", status=403)

    acta: MesaActaOral | None = getattr(inscripcion, "acta_oral", None)
    if not acta:
        return HttpResponse("Acta oral no registrada.", status=404)

    mesa = inscripcion.mesa
    materia = mesa.materia
    profesorado = materia.plan_de_estudio.profesorado if materia and materia.plan_de_estudio else None
    estudiante = inscripcion.estudiante
    est_nombre = f"{estudiante.apellido}, {estudiante.nombre}".strip(", ") or f"DNI {estudiante.dni}"

    pres = mesa.docente_presidente
    voc1 = mesa.docente_vocal1
    voc2 = mesa.docente_vocal2

    def docente_nombre(d):
        if not d:
            return ""
        return f"{d.persona.apellido.upper()}, {d.persona.nombre}" if d.persona else ""

    logo_left = os.path.join(settings.BASE_DIR, "static/logos/escudo_ministerio_tdf.png")
    logo_right = os.path.join(settings.BASE_DIR, "static/logos/logo_ipes.jpg")

    fecha_str = acta.fecha.strftime("%d/%m/%Y") if acta.fecha else ""

    context = {
        "logo_left_path": logo_left,
        "logo_right_path": logo_right,
        "acta_numero": acta.acta_numero or "",
        "folio_numero": acta.folio_numero or "",
        "fecha": fecha_str,
        "carrera": profesorado.nombre if profesorado else "",
        "unidad_curricular": materia.nombre if materia else "",
        "curso": mesa.codigo or acta.curso or "",
        "estudiante": f"{est_nombre} - DNI {estudiante.dni}",
        "tribunal": {
            "presidente": docente_nombre(pres),
            "vocal1": docente_nombre(voc1),
            "vocal2": docente_nombre(voc2),
        },
        "temas_estudiante": acta.temas_alumno or [],
        "temas_docente": acta.temas_docente or [],
        "nota_final": acta.nota_final or "",
        "observaciones": acta.observaciones or "",
    }

    html_string = render_to_string("core/acta_oral_pdf.html", context)
    response = HttpResponse(content_type="application/pdf")
    safe_name = est_nombre.replace(" ", "_").replace(",", "")
    response["Content-Disposition"] = f'attachment; filename="acta_oral_{safe_name}.pdf"'

    from apps.preinscriptions.views_pdf import safe_weasyprint_url_fetcher

    HTML(string=html_string, url_fetcher=safe_weasyprint_url_fetcher, base_url=request.build_absolute_uri()).write_pdf(
        response
    )
    return response
