import datetime
import io

import pytest
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from ninja.errors import HttpError

from apps.common.security_utils import sanitize_formula_injection, sanitize_row
from apps.docentes.services.docente_service import DocenteService
from apps.preinscriptions.services.rate_limiting import (
    check_recovery_rate_limit,
    verify_recaptcha,
)
from apps.preinscriptions.upload_utils import _pdf_has_javascript, _validate_pdf
from core.models import Docente, Estudiante, Persona, Preinscripcion, Profesorado
from core.models.mensajeria import validate_attachment


@pytest.mark.django_db
def test_f17_docente_serialization_privacy():
    """F17: serialize_docente oculta PII y credenciales a no-administradores."""
    persona = Persona.objects.create(
        nombre="Carlos",
        apellido="Docente",
        dni="30111222",
        email="carlos@test.edu.ar",
        telefono="1122334455",
        cuil="20-30111222-3",
        fecha_nacimiento=datetime.date(1985, 5, 12),
    )
    docente = Docente.objects.create(persona=persona)
    user, _, _ = DocenteService.ensure_user_for_docente(docente)

    # Vista para usuario común (ej. estudiante o sin permisos de gestión)
    out_public = DocenteService.serialize_docente(docente, is_admin=False)
    assert out_public.nombre == docente.nombre
    assert out_public.apellido == docente.apellido
    assert out_public.email == "carlos@test.edu.ar"
    assert out_public.dni == ""
    assert out_public.telefono is None
    assert out_public.cuil is None
    assert out_public.fecha_nacimiento is None
    assert out_public.usuario is None
    assert out_public.temp_password is None

    # Vista para administrador
    out_admin = DocenteService.serialize_docente(docente, temp_password="secret-temp-pass", is_admin=True)
    assert out_admin.dni == "30111222"
    assert out_admin.telefono == "1122334455"
    assert out_admin.cuil == "20-30111222-3"
    assert out_admin.fecha_nacimiento == datetime.date(1985, 5, 12)
    assert out_admin.usuario == user.username
    assert out_admin.temp_password == "secret-temp-pass"


@pytest.mark.django_db
def test_f18_mensajeria_roles_and_territoriality():
    """F18: Bloqueo de mensajes por rol a usuarios no autorizados y validación de carreras."""
    from apps.mensajeria.api import create_conversation_view
    from apps.mensajeria.schemas import ConversationCreateIn

    student_user = User.objects.create_user(username="student_user", password="pwd")
    student_group, _ = Group.objects.get_or_create(name="estudiante")
    student_user.groups.add(student_group)

    factory = RequestFactory()
    req = factory.post("/api/mensajeria/conversaciones")
    req.user = student_user

    # Estudiante intenta mandar mensaje masivo por rol
    payload = ConversationCreateIn(
        subject="Spam masivo",
        body="Hola a todos",
        roles=["estudiante"],
    )

    with pytest.raises(HttpError) as exc_info:
        create_conversation_view(req, payload)
    assert exc_info.value.status_code == 403


def test_f19_attachment_validation():
    """F19: Validación estricta de adjuntos en mensajería."""

    class FakeFile:
        def __init__(self, name, content, size=None):
            self.name = name
            self.content = content
            self.size = size if size is not None else len(content)
            self._io = io.BytesIO(content)

        def seek(self, pos):
            return self._io.seek(pos)

        def read(self, *args):
            return self._io.read(*args)

    # 1. Extensión ejecutable prohibida
    exe_file = FakeFile("malware.exe", b"MZ\x90\x00\x03")
    with pytest.raises(ValidationError) as exc:
        validate_attachment(exe_file)
    assert "Extensión no permitida" in str(exc.value)

    # 2. Archivo mayor a 2 MB
    big_pdf = FakeFile("big.pdf", b"%PDF-1.4" + b"A" * (3 * 1024 * 1024), size=3 * 1024 * 1024)
    with pytest.raises(ValidationError) as exc:
        validate_attachment(big_pdf)
    assert "supera el límite" in str(exc.value)

    # 3. Archivo con extensión .pdf pero sin magic header %PDF-
    fake_pdf = FakeFile("fake.pdf", b"<html>evil</html>")
    with pytest.raises(ValidationError) as exc:
        validate_attachment(fake_pdf)
    assert "no es un documento PDF válido" in str(exc.value)


def test_f20_pdf_javascript_detection():
    """F20: Detección profunda de JavaScript embebido en PDFs."""
    import pypdf.generic as g

    # Simular estructura de pypdf con /JS en diccionario de acción
    action_dict = g.DictionaryObject(
        {
            g.NameObject("/S"): g.NameObject("/JavaScript"),
            g.NameObject("/JS"): g.TextStringObject("app.alert('XSS');"),
        }
    )
    assert _pdf_has_javascript(action_dict) is True

    # Simular página con anotación que contiene acción JS
    page_dict = g.DictionaryObject(
        {
            g.NameObject("/Type"): g.NameObject("/Page"),
            g.NameObject("/Annots"): g.ArrayObject([action_dict]),
        }
    )
    assert _pdf_has_javascript(page_dict) is True

    # Estructura limpia
    clean_dict = g.DictionaryObject(
        {
            g.NameObject("/Type"): g.NameObject("/Page"),
            g.NameObject("/Contents"): g.ArrayObject([]),
        }
    )
    assert _pdf_has_javascript(clean_dict) is False


def test_f21_formula_injection_sanitization():
    """F21: Sanitización de caracteres de inicio de fórmula (=, +, -, @, \\t, \\r)."""
    assert sanitize_formula_injection("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert sanitize_formula_injection("+12345") == "'+12345"
    assert sanitize_formula_injection("-100") == "'-100"
    assert sanitize_formula_injection("@SUM(A1:B2)") == "'@SUM(A1:B2)"
    assert sanitize_formula_injection("\tcmd") == "'\tcmd"
    assert sanitize_formula_injection("\rcmd") == "'\rcmd"

    # Tipos numéricos o seguros no se alteran
    assert sanitize_formula_injection(42) == 42
    assert sanitize_formula_injection(3.14) == 3.14
    assert sanitize_formula_injection(None) is None
    assert sanitize_formula_injection("Normal text") == "Normal text"

    row = ["=1+1", "Texto", 99]
    assert sanitize_row(row) == ["'=1+1", "Texto", 99]


@pytest.mark.django_db
def test_f22_recaptcha_fail_closed(settings):
    """F22: verify_recaptcha falla cerrado si no hay token y existe secret configurado."""
    settings.RECAPTCHA_SECRET_KEY = "dummy-secret-key"
    assert verify_recaptcha(token=None, remote_ip="192.168.1.1") is False
    assert verify_recaptcha(token="", remote_ip="192.168.1.1") is False

    # Si no hay secret configurado (ej. desarrollo local), permite
    settings.RECAPTCHA_SECRET_KEY = ""
    assert verify_recaptcha(token=None, remote_ip="192.168.1.1") is True


@pytest.mark.django_db
def test_f22_recuperar_preinscripcion_uniform_error():
    """F22: recuperar_preinscripcion retorna error idéntico (400) tanto para DNI no encontrado como fecha errónea."""
    from apps.preinscriptions.api import recuperar_preinscripcion
    from apps.preinscriptions.schemas import RecuperarPreinscripcionIn

    carrera = Profesorado.objects.create(nombre="Profesorado Test", duracion_anios=4)
    persona = Persona.objects.create(
        nombre="Ana",
        apellido="García",
        dni="40999888",
        fecha_nacimiento=datetime.date(2000, 1, 15),
    )
    user_alumno = User.objects.create_user(username="alumno_40999888", password="pwd")
    alumno = Estudiante.objects.create(persona=persona, user=user_alumno)
    Preinscripcion.objects.create(
        alumno=alumno,
        carrera=carrera,
        anio=2026,
        codigo="TEST-1234",
        activa=True,
    )

    factory = RequestFactory()
    req = factory.post("/api/preinscripciones/recuperar")

    # Caso 1: DNI inexistente
    payload_inexistente = RecuperarPreinscripcionIn(
        dni="00000000",
        carrera_id=carrera.id,
        fecha_nacimiento=datetime.date(2000, 1, 15),
    )
    status_1, resp_1 = recuperar_preinscripcion(req, payload_inexistente)
    assert status_1 == 400
    assert resp_1.ok is False
    assert resp_1.message == "Los datos ingresados no coinciden con ninguna preinscripción activa."

    # Caso 2: DNI existente pero fecha incorrecta
    payload_fecha_erronea = RecuperarPreinscripcionIn(
        dni="40999888",
        carrera_id=carrera.id,
        fecha_nacimiento=datetime.date(1990, 5, 20),
    )
    status_2, resp_2 = recuperar_preinscripcion(req, payload_fecha_erronea)
    assert status_2 == 400
    assert resp_2.ok is False
    assert resp_2.message == "Los datos ingresados no coinciden con ninguna preinscripción activa."

    # Ambos devuelven exactamente la misma respuesta impidiendo enumeración
    assert resp_1.message == resp_2.message
