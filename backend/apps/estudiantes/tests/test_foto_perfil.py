import io

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from core.models import Estudiante, EstudianteCarrera, Persona, Profesorado, StaffAsignacion

User = get_user_model()
pytestmark = pytest.mark.django_db


def _crear_imagen_valida_jpeg() -> bytes:
    buffer = io.BytesIO()
    img = Image.new("RGB", (120, 120), color="blue")
    img.save(buffer, format="JPEG")
    buffer.seek(0)
    return buffer.read()


@pytest.fixture
def datos_prueba(client):
    # Profesorado
    carrera = Profesorado.objects.create(nombre="Profesorado de Historia", duracion_anios=4)

    # Grupos
    grp_est, _ = Group.objects.get_or_create(name="estudiante")
    grp_bedel, _ = Group.objects.get_or_create(name="bedel")

    # 1. Estudiante
    p_est = Persona.objects.create(dni="90000001", nombre="Lucía", apellido="Alvarez")
    u_est = User.objects.create_user(username="90000001", password="password123")
    u_est.groups.add(grp_est)
    est = Estudiante.objects.create(persona=p_est, user=u_est, legajo="LEG-9001")
    est.carreras.add(carrera)

    # 2. Bedel con permiso sobre la carrera
    p_bedel = Persona.objects.create(dni="70000001", nombre="Carlos", apellido="Bedel")
    u_bedel = User.objects.create_user(username="bedel1", password="password123")
    u_bedel.groups.add(grp_bedel)
    StaffAsignacion.objects.create(user=u_bedel, rol="bedel", profesorado=carrera)

    # 3. Usuario sin permisos
    u_ajeno = User.objects.create_user(username="ajeno", password="password123")

    return {
        "carrera": carrera,
        "estudiante": est,
        "user_est": u_est,
        "persona_est": p_est,
        "user_bedel": u_bedel,
        "user_ajeno": u_ajeno,
    }


def test_estudiante_actualiza_su_propia_foto(client, datos_prueba):
    data = datos_prueba
    client.force_login(data["user_est"])

    img_bytes = _crear_imagen_valida_jpeg()
    file_upload = SimpleUploadedFile("foto_perfil.jpg", img_bytes, content_type="image/jpeg")

    resp = client.post(
        "/api/estudiantes/perfil/foto",
        {"file": file_upload},
        HTTP_X_ACTIVE_ROLE="estudiante",
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verificar que se guardó en la persona
    data["persona_est"].refresh_from_db()
    assert bool(data["persona_est"].foto) is True
    assert "90000001" in data["persona_est"].foto.name


def test_bedel_actualiza_foto_de_estudiante(client, datos_prueba):
    data = datos_prueba
    client.force_login(data["user_bedel"])

    img_bytes = _crear_imagen_valida_jpeg()
    file_upload = SimpleUploadedFile("foto_nueva.jpg", img_bytes, content_type="image/jpeg")

    resp = client.post(
        f"/api/estudiantes/admin/estudiantes/{data['persona_est'].dni}/foto",
        {"file": file_upload},
        HTTP_X_ACTIVE_ROLE="bedel",
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "actualizada" in resp.json()["message"].lower()

    data["persona_est"].refresh_from_db()
    assert bool(data["persona_est"].foto) is True


def test_bedel_elimina_foto_de_estudiante(client, datos_prueba):
    data = datos_prueba
    # Primero asignamos una foto
    img_bytes = _crear_imagen_valida_jpeg()
    file_upload = SimpleUploadedFile("foto.jpg", img_bytes, content_type="image/jpeg")
    client.force_login(data["user_bedel"])
    client.post(
        f"/api/estudiantes/admin/estudiantes/{data['persona_est'].dni}/foto",
        {"file": file_upload},
        HTTP_X_ACTIVE_ROLE="bedel",
    )
    data["persona_est"].refresh_from_db()
    assert bool(data["persona_est"].foto) is True

    # Ahora la eliminamos
    resp = client.delete(
        f"/api/estudiantes/admin/estudiantes/{data['persona_est'].dni}/foto",
        HTTP_X_ACTIVE_ROLE="bedel",
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    data["persona_est"].refresh_from_db()
    assert bool(data["persona_est"].foto) is False


def test_usuario_sin_permisos_es_rechazado(client, datos_prueba):
    data = datos_prueba
    client.force_login(data["user_ajeno"])

    img_bytes = _crear_imagen_valida_jpeg()
    file_upload = SimpleUploadedFile("foto.jpg", img_bytes, content_type="image/jpeg")

    resp = client.post(
        f"/api/estudiantes/admin/estudiantes/{data['persona_est'].dni}/foto",
        {"file": file_upload},
    )
    assert resp.status_code in (401, 403)


def test_archivo_invalido_es_rechazado(client, datos_prueba):
    data = datos_prueba
    client.force_login(data["user_bedel"])

    # Archivo falso con extensión jpg pero contenido de texto
    fake_file = SimpleUploadedFile("malicioso.jpg", b"esto no es una imagen real", content_type="image/jpeg")

    resp = client.post(
        f"/api/estudiantes/admin/estudiantes/{data['persona_est'].dni}/foto",
        {"file": fake_file},
        HTTP_X_ACTIVE_ROLE="bedel",
    )
    assert resp.status_code == 400
    assert resp.json()["ok"] is False
