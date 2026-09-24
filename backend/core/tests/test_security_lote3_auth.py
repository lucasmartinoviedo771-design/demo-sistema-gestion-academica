"""
Suite de pruebas de seguridad para Lote 3: Autenticación, Sesiones y CSRF (F13, F14, F15).

Verifica:
- F13: Normalización de bedel_secretaria a rol limitado por carreras en StaffAsignacion.
- F14: Protección CSRF obligatoria en JWTAuth cuando la sesión proviene de cookies HttpOnly.
- F15: Revocación inmediata de tokens en logout, cambio de clave, reseteo administrativo y rotación de refresh tokens.
"""

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.test import RequestFactory

from apps.common.errors import AppError
from apps.management.api.staff import ForceResetPasswordIn, force_reset_password
from apps.management.auth_api import ChangePasswordIn, RefreshIn, change_password, logout, refresh_token
from core.auth_ninja import JWTAuth
from core.authentication.jwt_service import JWTService
from core.models import Profesorado, RevokedToken, StaffAsignacion, UserProfile
from core.permissions import (
    _LIMITED_ROLES,
    _UNRESTRICTED_ROLES,
    CAPABILITIES,
    allowed_profesorados,
    ensure_profesorado_access,
)


@pytest.fixture
def users_lote3(db):
    g_bedel_sec, _ = Group.objects.get_or_create(name="bedel_secretaria")
    g_admin, _ = Group.objects.get_or_create(name="admin")

    u_bedel_sec = User.objects.create_user(username="bedel_sec_user", password="Password123!")
    u_bedel_sec.groups.add(g_bedel_sec)
    UserProfile.objects.create(user=u_bedel_sec)

    u_admin = User.objects.create_superuser(username="admin_lote3", password="Password123!")
    u_admin.groups.add(g_admin)
    UserProfile.objects.create(user=u_admin)

    u_regular = User.objects.create_user(username="regular_user", password="Password123!")
    UserProfile.objects.create(user=u_regular)

    p_a = Profesorado.objects.create(nombre="Profesorado A", duracion_anios=4)
    p_b = Profesorado.objects.create(nombre="Profesorado B", duracion_anios=4)

    return {
        "bedel_sec": u_bedel_sec,
        "admin": u_admin,
        "regular": u_regular,
        "prof_a": p_a,
        "prof_b": p_b,
    }


# ═══════════════════════════════════════════════════════════════════
# F13: NORMALIZACIÓN DE BEDEL_SECRETARIA
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_f13_bedel_secretaria_en_roles_limitados():
    """bedel_secretaria debe ser un rol limitado y NO figurar en roles globales/irrestrictos."""
    assert "bedel_secretaria" in _LIMITED_ROLES
    assert "bedel_secretaria" not in _UNRESTRICTED_ROLES


@pytest.mark.django_db
def test_f13_bedel_secretaria_capabilities_operativas():
    """bedel_secretaria debe tener capacidades operativas pero NO directivas (gestionar_staff, asignar_roles)."""
    assert "bedel_secretaria" in CAPABILITIES["editar_estudiantes"]
    assert "bedel_secretaria" in CAPABILITIES["resetear_password_estudiante"]
    assert "bedel_secretaria" in CAPABILITIES["editar_documentacion"]
    assert "bedel_secretaria" in CAPABILITIES["asistencia_estudiantes_editar"]

    # NO debe tener capacidades de administración de personal
    assert "bedel_secretaria" not in CAPABILITIES["gestionar_staff"]
    assert "bedel_secretaria" not in CAPABILITIES["asignar_roles"]


@pytest.mark.django_db
def test_f13_bedel_secretaria_acotado_a_carreras_asignadas(users_lote3):
    """bedel_secretaria debe poder operar SOLAMENTE sobre sus carreras asignadas en StaffAsignacion."""
    user = users_lote3["bedel_sec"]
    p_a = users_lote3["prof_a"]
    p_b = users_lote3["prof_b"]

    StaffAsignacion.objects.create(user=user, profesorado=p_a, rol=StaffAsignacion.Rol.BEDEL)

    # allowed_profesorados debe devolver solo el ID de p_a, no None
    allowed = allowed_profesorados(user)
    assert allowed == {p_a.id}

    # Carrera asignada debe pasar
    ensure_profesorado_access(user, p_a.id)

    # Carrera NO asignada debe ser rechazada con 403 Forbidden
    with pytest.raises(AppError) as exc_info:
        ensure_profesorado_access(user, p_b.id)
    assert exc_info.value.status_code == 403


@pytest.mark.django_db
def test_f13_bedel_secretaria_sin_asignacion_bloqueado(users_lote3):
    """bedel_secretaria sin asignaciones explícitas debe tener alcance vacío."""
    user = users_lote3["bedel_sec"]
    p_a = users_lote3["prof_a"]

    allowed = allowed_profesorados(user)
    assert allowed == set()

    with pytest.raises(AppError) as exc_info:
        ensure_profesorado_access(user, p_a.id)
    assert exc_info.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# F14: PROTECCIÓN CSRF EN COOKIE AUTH
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_f14_jwt_auth_cookie_requiere_csrf_en_post(users_lote3):
    """Petición mutante con JWT en cookie sin CSRF token debe fallar con 403 Forbidden."""
    user = users_lote3["regular"]
    token = JWTService.create_access_token(user.id)

    rf = RequestFactory()
    req = rf.post("/api/estudiantes/update", HTTP_HOST="localhost")
    req.COOKIES[settings.JWT_ACCESS_COOKIE_NAME] = token

    auth = JWTAuth()
    with pytest.raises(AppError) as exc_info:
        auth(req)
    assert exc_info.value.status_code == 403
    assert "CSRF" in exc_info.value.message


@pytest.mark.django_db
def test_f14_jwt_auth_cookie_con_csrf_valido_autorizado(users_lote3):
    """Petición mutante con JWT en cookie y token CSRF válido debe autorizarse."""
    user = users_lote3["regular"]
    token = JWTService.create_access_token(user.id)

    rf = RequestFactory()
    req_get = rf.get("/api/test", HTTP_HOST="localhost")
    mw = CsrfViewMiddleware(lambda r: None)
    mw.process_request(req_get)
    csrf_token = get_token(req_get)

    req_post = rf.post("/api/estudiantes/update", HTTP_HOST="localhost", HTTP_X_CSRFTOKEN=csrf_token)
    req_post.COOKIES[settings.JWT_ACCESS_COOKIE_NAME] = token
    req_post.COOKIES[settings.CSRF_COOKIE_NAME] = csrf_token

    auth = JWTAuth()
    authenticated_user = auth(req_post)
    assert authenticated_user == user


@pytest.mark.django_db
def test_f14_jwt_auth_bearer_no_requiere_csrf(users_lote3):
    """Petición mutante con Authorization Bearer token no requiere validación CSRF."""
    user = users_lote3["regular"]
    token = JWTService.create_access_token(user.id)

    rf = RequestFactory()
    req_post = rf.post(
        "/api/estudiantes/update",
        HTTP_HOST="localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    auth = JWTAuth()
    authenticated_user = auth(req_post)
    assert authenticated_user == user


# ═══════════════════════════════════════════════════════════════════
# F15: REVOCACIÓN DE SESIONES Y ROTACIÓN DE TOKENS
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_f15_logout_revoca_tokens(users_lote3):
    """Cerrar sesión debe revocar el token emitido previamente."""
    user = users_lote3["regular"]
    token = JWTService.create_access_token(user.id)

    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    client.get("/api/auth/profile/")
    response = client.post(
        "/api/auth/logout/",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200
    rf = RequestFactory()

    # El token previo ahora debe ser rechazado por JWTAuth
    req_next = rf.get("/api/perfil", HTTP_HOST="localhost", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert JWTAuth()(req_next) is None


@pytest.mark.django_db
def test_f15_cambio_clave_revoca_tokens_anteriores(users_lote3):
    """Cambiar la contraseña debe revocar todos los tokens emitidos con anterioridad."""
    user = users_lote3["regular"]
    token_anterior = JWTService.create_access_token(user.id)

    rf = RequestFactory()
    req = rf.post("/api/auth/change-password/", HTTP_HOST="localhost", HTTP_AUTHORIZATION=f"Bearer {token_anterior}")
    req.user = user

    payload = ChangePasswordIn(current_password="Password123!", new_password="NewSecurePassword456!")
    change_password(req, payload)

    # El token anterior a la modificación debe ser rechazado
    req_check = rf.get("/api/perfil", HTTP_HOST="localhost", HTTP_AUTHORIZATION=f"Bearer {token_anterior}")
    assert JWTAuth()(req_check) is None

    # Un nuevo token emitido después del cambio (con iat posterior) debe funcionar
    import time

    time.sleep(1.05)
    nuevo_token = JWTService.create_access_token(user.id)
    req_nuevo = rf.get("/api/perfil", HTTP_HOST="localhost", HTTP_AUTHORIZATION=f"Bearer {nuevo_token}")
    assert JWTAuth()(req_nuevo) == user


@pytest.mark.django_db
def test_f15_reseteo_administrativo_revoca_tokens_anteriores(users_lote3):
    """El reseteo de clave por un administrador debe revocar los tokens previos de la víctima."""
    user = users_lote3["regular"]
    admin = users_lote3["admin"]
    token_victima = JWTService.create_access_token(user.id)

    rf = RequestFactory()
    req = rf.post("/api/management/staff/force-password-reset", HTTP_HOST="localhost")
    req.user = admin

    payload = ForceResetPasswordIn(
        username=user.username,
        email="victima@demo.invalid",
        new_password="AdminAssignedPassword789!",
    )
    status, _ = force_reset_password(req, payload)
    assert status == 200

    # Token de la víctima debe quedar revocado
    req_victima = rf.get("/api/perfil", HTTP_HOST="localhost", HTTP_AUTHORIZATION=f"Bearer {token_victima}")
    assert JWTAuth()(req_victima) is None


@pytest.mark.django_db
def test_f15_rotacion_refresh_token_anti_reuso(users_lote3):
    """Un refresh token solo puede usarse UNA vez; al consumirse, su reutilización debe ser rechazada."""
    user = users_lote3["regular"]
    refresh_1 = JWTService.create_refresh_token(user.id)

    rf = RequestFactory()
    req = rf.post("/api/auth/refresh/", HTTP_HOST="localhost")

    # Primer uso del refresh token -> exitoso
    res = refresh_token(req, payload=RefreshIn(refresh=refresh_1))
    assert res.status_code == 200

    # Segundo uso del MISMO refresh token -> rechazado con 401
    with pytest.raises(AppError) as exc_info:
        refresh_token(req, payload=RefreshIn(refresh=refresh_1))
    assert exc_info.value.status_code == 401
    assert "revocado" in exc_info.value.message.lower() or "inválido" in exc_info.value.message.lower()
