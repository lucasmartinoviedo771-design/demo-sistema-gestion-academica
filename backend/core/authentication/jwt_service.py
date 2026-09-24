"""
Servicio central de tokens JWT.
Maneja la generación y validación de tokens de Acceso y Refresh
utilizando el estándar HS256 y el SECRET_KEY de la aplicación.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


def _adapt_datetime_for_db(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if not getattr(settings, "USE_TZ", False) and dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def revoke_user_tokens(user: User) -> None:
    """
    Invalida todos los tokens JWT emitidos previamente para el usuario.
    Actualiza token_invalid_before en su UserProfile.
    """
    if not user:
        return
    from core.models import UserProfile

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.token_invalid_before = timezone.now()
    profile.save(update_fields=["token_invalid_before"])


def revoke_token_jti(jti: str, expires_at: datetime | None = None) -> None:
    """
    Registra un identificador único de token (jti) en la tabla de tokens revocados.
    """
    if not jti:
        return
    from core.models import RevokedToken

    expires_at = _adapt_datetime_for_db(expires_at)
    RevokedToken.objects.get_or_create(jti=jti, defaults={"expires_at": expires_at})


def is_token_revoked(payload: dict, user: User | None = None) -> bool:
    """
    Verifica si un token ha sido revocado, ya sea por su identificador jti,
    porque fue emitido antes de la fecha de invalidación del usuario,
    o porque corresponde al formato heredado previo a la implementación de jti/iat.
    """
    if not payload:
        return True

    jti = payload.get("jti")
    iat = payload.get("iat")

    # Política de transición: Exigir jti e iat. Tokens generados con el formato antiguo
    # carecen de estos campos y no soportan el mecanismo de revocación y rotación.
    if not jti or iat is None:
        return True

    from core.models import RevokedToken

    if RevokedToken.objects.filter(jti=jti).exists():
        return True

    if user is None:
        user_id = payload.get("user_id")
        if user_id:
            user = User.objects.filter(id=user_id).first()

    if user:
        profile = getattr(user, "profile", None)
        if profile and profile.token_invalid_before:
            if float(iat) < profile.token_invalid_before.timestamp():
                return True

    return False


class JWTService:
    """
    Motor de servicios para el ciclo de vida de JSON Web Tokens.
    """

    @staticmethod
    def create_access_token(user_id: int, original_admin_id: int | None = None) -> str:
        """
        Genera un token de acceso de corta duración (60 minutos).
        Destinado a ser enviado en cada petición protegida.
        """
        payload = {
            "user_id": user_id,
            "exp": datetime.now(UTC) + timedelta(minutes=60),
            "iat": datetime.now(UTC).timestamp(),
            "type": "access",
            "jti": str(uuid.uuid4()),
        }
        if original_admin_id is not None:
            payload["original_admin_id"] = original_admin_id
        return jwt.encode(payload, getattr(settings, "JWT_SECRET_KEY", settings.SECRET_KEY), algorithm="HS256")

    @staticmethod
    def create_refresh_token(user_id: int, original_admin_id: int | None = None) -> str:
        """
        Genera un token de actualización de larga duración (7 días).
        Permite obtener nuevos access tokens sin re-autenticar al usuario.
        """
        payload = {
            "user_id": user_id,
            "exp": datetime.now(UTC) + timedelta(days=7),
            "iat": datetime.now(UTC).timestamp(),
            "type": "refresh",
            "jti": str(uuid.uuid4()),
        }
        if original_admin_id is not None:
            payload["original_admin_id"] = original_admin_id
        return jwt.encode(payload, getattr(settings, "JWT_SECRET_KEY", settings.SECRET_KEY), algorithm="HS256")

    @staticmethod
    def create_password_reset_token(user) -> str:
        """
        Token de un solo uso para recuperación de contraseña. Incluye un
        fragmento del hash de la contraseña actual: si el usuario ya cambió
        la contraseña (con este link o por otra vía) antes de usarlo, el
        fragmento no coincide más y el token queda invalidado sin necesitar
        una tabla de tokens usados.
        """
        minutes = getattr(settings, "PASSWORD_RESET_TIMEOUT_MINUTES", 30)
        payload = {
            "user_id": user.id,
            "pwd_fragment": user.password[-16:],
            "exp": datetime.now(UTC) + timedelta(minutes=minutes),
            "iat": datetime.now(UTC).timestamp(),
            "type": "password_reset",
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(payload, getattr(settings, "JWT_SECRET_KEY", settings.SECRET_KEY), algorithm="HS256")

    @staticmethod
    def decode_token(token: str) -> dict | None:
        """
        Decodifica un token y valida su firma y expiración.
        Retorna el payload si es válido, de lo contrario None.
        """
        try:
            return jwt.decode(token, getattr(settings, "JWT_SECRET_KEY", settings.SECRET_KEY), algorithms=["HS256"])
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None

    @staticmethod
    def get_user_from_token(token: str):
        """
        Recupera una instancia de User activa a partir de un token de acceso.
        Realiza validaciones de tipo de token, integridad de base de datos y revocación.
        """
        payload = JWTService.decode_token(token)
        if not payload or payload.get("type") != "access":
            return None

        user_id = payload.get("user_id")
        if not user_id:
            return None

        try:
            user = User.objects.get(pk=user_id, is_active=True)
            if is_token_revoked(payload, user):
                return None
            return user
        except User.DoesNotExist:
            return None
