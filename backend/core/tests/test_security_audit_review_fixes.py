import datetime
import io
from unittest.mock import patch

import pytest
import requests
from django.contrib.auth.models import Group, User
from django.test import RequestFactory
from ninja.errors import HttpError

from apps.estudiantes.api.actas_orales import guardar_acta_oral, obtener_acta_oral
from apps.estudiantes.schemas import ActaOralSchema
from apps.preinscriptions.services.rate_limiting import verify_recaptcha
from apps.preinscriptions.upload_utils import _pdf_has_javascript
from core.auth_ninja import JWTAuth
from core.authentication.jwt_service import JWTService, is_token_revoked
from core.models import (
    Docente,
    Estudiante,
    InscripcionMesa,
    Materia,
    MesaActaOral,
    MesaExamen,
    Persona,
    PlanDeEstudio,
    Profesorado,
    StaffAsignacion,
)
from core.permissions import can, get_user_roles


# ------------------------------------------------------------------------------
# F12: Autorización y respuestas de actas orales
# ------------------------------------------------------------------------------
@pytest.mark.django_db
def test_f12_guardar_acta_oral_bedel_otra_carrera_403():
    """Un bedel de otra carrera recibe 403 al intentar guardar un acta oral."""
    carrera_1 = Profesorado.objects.create(nombre="Carrera 1", duracion_anios=4)
    carrera_2 = Profesorado.objects.create(nombre="Carrera 2", duracion_anios=4)

    plan_1 = PlanDeEstudio.objects.create(resolucion="Res 1", profesorado=carrera_1, anio_inicio=2020)
    materia_1 = Materia.objects.create(nombre="Materia 1", anio_cursada=1, plan_de_estudio=plan_1)

    p_doc = Persona.objects.create(nombre="Doc", apellido="Pres", dni="11111111")
    doc_pres = Docente.objects.create(persona=p_doc)

    mesa = MesaExamen.objects.create(
        materia=materia_1,
        docente_presidente=doc_pres,
        fecha=datetime.date(2026, 11, 20),
        hora_desde=datetime.time(9, 0),
    )

    p_est = Persona.objects.create(nombre="Est", apellido="Uno", dni="22222222")
    user_est = User.objects.create_user(username="22222222", password="pwd")
    estudiante = Estudiante.objects.create(persona=p_est, user=user_est)

    insc = InscripcionMesa.objects.create(mesa=mesa, estudiante=estudiante)

    # Bedel asignado únicamente a Carrera 2
    user_bedel = User.objects.create_user(username="bedel_c2", password="pwd")
    group_bedel, _ = Group.objects.get_or_create(name="bedel")
    user_bedel.groups.add(group_bedel)
    StaffAsignacion.objects.create(user=user_bedel, profesorado=carrera_2, rol="bedel")

    factory = RequestFactory()
    req = factory.post(f"/api/carga-notas/mesas/{mesa.id}/oral-actas/{insc.id}")
    req.user = user_bedel

    payload = ActaOralSchema(
        fecha=datetime.date(2026, 11, 20),
        nota_final="8",
    )

    status_code, resp = guardar_acta_oral(req, mesa.id, insc.id, payload)
    assert status_code == 403
    assert resp.ok is False
    assert "No tienes permisos" in resp.message
    # Verificar que no se creó el acta
    assert not MesaActaOral.objects.filter(inscripcion=insc).exists()


@pytest.mark.django_db
def test_f12_guardar_acta_oral_acta_cerrada_solo_secretaria():
    """Un acta oral cerrada no puede ser modificada por un bedel o docente; requiere secretaría/admin."""
    carrera = Profesorado.objects.create(nombre="Carrera Test", duracion_anios=4)
    plan = PlanDeEstudio.objects.create(resolucion="Res T", profesorado=carrera, anio_inicio=2020)
    materia = Materia.objects.create(nombre="Materia Test", anio_cursada=1, plan_de_estudio=plan)

    p_doc = Persona.objects.create(nombre="Doc", apellido="Pres", dni="11111112")
    doc_pres = Docente.objects.create(persona=p_doc)
    user_doc = User.objects.create_user(username="11111112", password="pwd")
    group_doc, _ = Group.objects.get_or_create(name="docente")
    user_doc.groups.add(group_doc)

    mesa = MesaExamen.objects.create(
        materia=materia,
        docente_presidente=doc_pres,
        fecha=datetime.date(2026, 11, 20),
        hora_desde=datetime.time(9, 0),
    )

    p_est = Persona.objects.create(nombre="Est", apellido="Dos", dni="22222223")
    user_est = User.objects.create_user(username="22222223", password="pwd")
    estudiante = Estudiante.objects.create(persona=p_est, user=user_est)

    insc = InscripcionMesa.objects.create(mesa=mesa, estudiante=estudiante)

    # Acta ya cerrada con CONFORME
    acta = MesaActaOral.objects.create(
        inscripcion=insc,
        mesa=mesa,
        fecha=datetime.date(2026, 11, 20),
        nota_final="7",
        estado_conformidad=MesaActaOral.EstadoConformidad.CONFORME,
    )

    factory = RequestFactory()
    req = factory.post(f"/api/carga-notas/mesas/{mesa.id}/oral-actas/{insc.id}")
    req.user = user_doc

    payload = ActaOralSchema(
        fecha=datetime.date(2026, 11, 20),
        nota_final="9",
    )

    # El docente presidente intenta modificarla
    status_code, resp = guardar_acta_oral(req, mesa.id, insc.id, payload)
    assert status_code == 403
    assert "No puede modificarse sin autorización expresa de Secretaría" in resp.message
    acta.refresh_from_db()
    assert acta.nota_final == "7"

    # Ahora un usuario de Secretaría
    user_sec = User.objects.create_user(username="sec_user", password="pwd")
    group_sec, _ = Group.objects.get_or_create(name="secretaria")
    user_sec.groups.add(group_sec)
    req.user = user_sec

    status_code, resp = guardar_acta_oral(req, mesa.id, insc.id, payload)
    assert status_code == 200
    acta.refresh_from_db()
    assert acta.nota_final == "9"


# ------------------------------------------------------------------------------
# F13: Herencia de permisos de bedel_secretaria
# ------------------------------------------------------------------------------
@pytest.mark.django_db
def test_f13_bedel_secretaria_no_hereda_rol_bedel():
    """bedel_secretaria no debe heredar el rol bedel ni permisos no otorgados explícitamente."""
    user = User.objects.create_user(username="bedel_sec_user", password="pwd")
    group, _ = Group.objects.get_or_create(name="bedel_secretaria")
    user.groups.add(group)

    roles = get_user_roles(user)
    assert "bedel_secretaria" in roles
    # No debe contener "bedel"
    assert "bedel" not in roles

    # Comprobar capacidades efectivas:
    # bedel_secretaria puede ver analíticos y editar estudiantes
    assert can(user, "ver_analiticos") is True
    assert can(user, "editar_estudiantes") is True

    # Pero NO debe tener capacidades exclusivas de bedel como editar_estructura o gestionar_analiticos
    assert can(user, "editar_estructura") is False
    assert can(user, "gestionar_analiticos") is False
    assert can(user, "gestionar_equivalencias") is False


# ------------------------------------------------------------------------------
# F14: Protección CSRF en sesiones Django
# ------------------------------------------------------------------------------
@pytest.mark.django_db
def test_f14_django_session_auth_requires_csrf_on_post():
    """Petición mutante con usuario autenticado por sesión Django requiere CSRF."""
    user = User.objects.create_user(username="session_user", password="pwd")
    factory = RequestFactory()

    # POST sin token CSRF
    req = factory.post("/api/algun-endpoint")
    req.user = user  # Simula sesión Django activa en request

    auth = JWTAuth()
    with pytest.raises(Exception) as exc:
        auth(req)
    assert "CSRF" in str(exc.value)


# ------------------------------------------------------------------------------
# F15: Transición de tokens antiguos
# ------------------------------------------------------------------------------
@pytest.mark.django_db
def test_f15_legacy_tokens_without_jti_or_iat_are_rejected():
    """Un token sin jti o sin iat (formato antiguo) debe considerarse revocado/inválido."""
    payload_legacy_no_jti = {
        "user_id": 1,
        "type": "access",
        "iat": datetime.datetime.now(datetime.UTC).timestamp(),
    }
    assert is_token_revoked(payload_legacy_no_jti) is True

    payload_legacy_no_iat = {
        "user_id": 1,
        "type": "access",
        "jti": "some-uuid",
    }
    assert is_token_revoked(payload_legacy_no_iat) is True

    payload_modern_valid = {
        "user_id": 1,
        "type": "access",
        "jti": "valid-uuid",
        "iat": datetime.datetime.now(datetime.UTC).timestamp(),
    }
    assert is_token_revoked(payload_modern_valid) is False


# ------------------------------------------------------------------------------
# F20: Recorrido de acciones JavaScript anidadas en /AA
# ------------------------------------------------------------------------------
def test_f20_pdf_javascript_in_nested_event_action():
    """Detección de JavaScript dentro de diccionarios de eventos (/O, /C, etc.) en /AA."""
    import pypdf.generic as g

    # Simular una acción JavaScript anidada bajo el evento /O (Page Open) de un /AA
    js_action = g.DictionaryObject(
        {
            g.NameObject("/S"): g.NameObject("/JavaScript"),
            g.NameObject("/JS"): g.TextStringObject("app.alert('XSS-nested');"),
        }
    )

    aa_dict = g.DictionaryObject(
        {
            g.NameObject("/O"): js_action,
        }
    )

    page_dict = g.DictionaryObject(
        {
            g.NameObject("/Type"): g.NameObject("/Page"),
            g.NameObject("/AA"): aa_dict,
        }
    )

    assert _pdf_has_javascript(page_dict) is True


# ------------------------------------------------------------------------------
# F22: CAPTCHA fail-closed en error de conexión
# ------------------------------------------------------------------------------
def test_f22_verify_recaptcha_fail_closed_on_network_error(settings):
    """Ante error de conexión o timeout con Google, verify_recaptcha retorna False (fail-closed)."""
    settings.RECAPTCHA_SECRET_KEY = "configured-secret"

    with patch("requests.post", side_effect=requests.Timeout("Connection timed out")):
        result = verify_recaptcha("some-token", "192.168.1.100")
        assert result is False

    with patch("requests.post", side_effect=requests.ConnectionError("Failed to connect")):
        result = verify_recaptcha("some-token", "192.168.1.100")
        assert result is False


def test_f20_pdf_incomplete_inspection_fails_closed():
    """F20: Exceder la profundidad máxima o fallar al resolver objeto provoca rechazo (fail-closed)."""
    import pypdf.generic as g

    # 1. Crear un árbol con profundidad excesiva (> 35)
    current = g.DictionaryObject()
    root = current
    for i in range(40):
        child = g.DictionaryObject()
        current[g.NameObject(f"/Sub{i}")] = child
        current = child

    with pytest.raises(ValueError) as exc:
        _pdf_has_javascript(root)
    assert "profundidad máxima" in str(exc.value)

    # 2. Objeto con fallo de resolución de objeto indirecto
    class BrokenIndirect(g.PdfObject):
        def get_object(self):
            raise RuntimeError("Stream corrupted")

    broken_dict = g.DictionaryObject(
        {
            g.NameObject("/Corrupted"): BrokenIndirect(),
        }
    )

    with pytest.raises(ValueError) as exc:
        _pdf_has_javascript(broken_dict)
    assert "No se pudo resolver" in str(exc.value)
