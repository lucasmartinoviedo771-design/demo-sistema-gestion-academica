import logging

import requests
from django.conf import settings
from django.core.cache import cache
from ninja.errors import HttpError

from core.client_ip import get_client_ip

logger = logging.getLogger(__name__)


def client_ip(request) -> str:
    """Alias del resolvedor central. Ver core/client_ip.py."""
    return get_client_ip(request)


def check_rate_limit(request) -> None:
    limit = getattr(settings, "PREINS_RATE_LIMIT_PER_HOUR", 0)
    if not limit:
        return
    ip = client_ip(request) or "unknown"
    cache_key = f"preins:rate:{ip}"
    added = cache.add(cache_key, 1, timeout=3600)
    if added:
        return
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=3600)
        count = 1
    if count > limit:
        raise HttpError(
            429,
            "Demasiadas preinscripciones desde tu red. Intentá nuevamente más tarde.",
        )


def check_recovery_rate_limit(request, dni: str | None = None) -> None:
    """Limita los intentos de recuperación por IP para evitar enumeración y fuerza bruta."""
    ip = client_ip(request) or "unknown"
    limit = getattr(settings, "PREINS_RECOVERY_RATE_LIMIT", 10)  # 10 intentos por hora por IP
    cache_key = f"preins:recovery:{ip}"
    added = cache.add(cache_key, 1, timeout=3600)
    if not added:
        try:
            count = cache.incr(cache_key)
        except ValueError:
            cache.set(cache_key, 1, timeout=3600)
            count = 1
        if count > limit:
            raise HttpError(
                429,
                "Demasiados intentos de recuperación desde tu red. Intentá nuevamente más tarde.",
            )


def verify_recaptcha(token: str | None, remote_ip: str) -> bool:
    secret = getattr(settings, "RECAPTCHA_SECRET_KEY", "")
    if not secret:
        return True
    if not token:
        logger.warning("reCAPTCHA: token ausente desde IP %s — solicitud rechazada (fail-closed)", remote_ip)
        return False
    try:
        response = requests.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={
                "secret": secret,
                "response": token,
                "remoteip": remote_ip,
            },
            timeout=5,
        )
        data = response.json()
    except requests.RequestException as exc:
        # F22: Ante falla de conexión o timeout con Google, no permitir bypass (fail-closed)
        logger.warning("No se pudo verificar reCAPTCHA: %s — se rechaza la solicitud (fail-closed)", exc)
        return False
    if not data.get("success"):
        logger.info("reCAPTCHA rechazado: %s", data)
        return False
    score = data.get("score")
    min_score = getattr(settings, "RECAPTCHA_MIN_SCORE", 0.1)
    if score is not None and score < min_score:
        logger.info("reCAPTCHA score bajo (%s)", score)
        return False
    return True
