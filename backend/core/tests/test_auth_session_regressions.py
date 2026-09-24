from datetime import UTC, datetime, timezone
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, User
from django.middleware.csrf import get_token
from django.test import Client, RequestFactory

from core.authentication.jwt_service import JWTService, is_token_revoked, revoke_user_tokens


def user(name, role=None):
    account = User.objects.create_user(username=name, password="Synthetic-Test!48620")
    if role:
        account.groups.add(Group.objects.get_or_create(name=role)[0])
    return account


def post(client, path, body):
    return client.post(path, body, content_type="application/json")


def csrf_headers(client):
    req = RequestFactory().get("/")
    token = get_token(req)
    client.cookies["csrftoken"] = req.META["CSRF_COOKIE"]
    return {"HTTP_X_CSRFTOKEN": token}


pytestmark = pytest.mark.django_db


def test_fresh_browser_login_then_legitimate_write():
    u = user("fresh-admin", "admin")
    c = Client(enforce_csrf_checks=True)
    r = post(c, "/api/auth/login/", {"login": u.username, "password": "Synthetic-Test!48620"})
    assert r.status_code == 200
    c.get("/api/auth/profile/")
    headers = {}
    if "csrftoken" in c.cookies:
        headers["HTTP_X_CSRFTOKEN"] = c.cookies["csrftoken"].value
    r = c.post(
        "/api/auth/change-password/",
        {"current_password": "Synthetic-Test!48620", "new_password": "New-Synthetic!758493"},
        content_type="application/json",
        **headers,
    )
    assert r.status_code == 200, r.content


def test_session_logout_ends_session():
    u = user("session-admin", "admin")
    c = Client(enforce_csrf_checks=True)
    c.force_login(u)
    r = c.post("/api/auth/logout/", {}, content_type="application/json", **csrf_headers(c))
    assert r.status_code == 200
    assert c.get("/api/auth/profile/").status_code == 401


def test_new_token_after_revocation_same_second_is_valid(settings):
    settings.USE_TZ = True
    u = user("revoked-user")
    instant = datetime(2026, 9, 20, 12, 0, 0, 500000, tzinfo=UTC)
    with patch("core.authentication.jwt_service.timezone.now", return_value=instant):
        revoke_user_tokens(u)
    with patch("core.authentication.jwt_service.datetime") as dt:
        dt.now.return_value = instant
        token = JWTService.create_access_token(u.id)
    import jwt
    from django.conf import settings

    payload = jwt.decode(
        token,
        getattr(settings, "JWT_SECRET_KEY", settings.SECRET_KEY),
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert not is_token_revoked(payload, u)


def test_cookie_refresh_rejects_untrusted_origin_without_csrf():
    u = user("refresh-user")
    c = Client(enforce_csrf_checks=True)
    from django.conf import settings

    c.cookies[settings.JWT_REFRESH_COOKIE_NAME] = JWTService.create_refresh_token(u.id)
    r = c.post(
        "/api/auth/refresh/", {}, content_type="application/json", HTTP_ORIGIN="https://untrusted.example.invalid"
    )
    assert r.status_code == 403, r.content


def test_cookie_write_with_valid_csrf_succeeds():
    u = user("csrf-valid", "admin")
    c = Client(enforce_csrf_checks=True)
    c.cookies["jwt_access_token"] = JWTService.create_access_token(u.id)
    req = RequestFactory().get("/")
    masked = get_token(req)
    c.cookies["csrftoken"] = req.META["CSRF_COOKIE"]
    r = c.post(
        "/api/auth/change-password/",
        {"current_password": "Synthetic-Test!48620", "new_password": "New-Synthetic!758493"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=masked,
    )
    assert r.status_code == 200, r.content


def test_plain_pdf_still_accepted():
    import io

    from pypdf import PdfWriter

    from apps.preinscriptions.upload_utils import _validate_pdf

    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    f = io.BytesIO()
    w.write(f)
    f.seek(0)
    assert _validate_pdf(f) == (True, None)


def test_cookie_refresh_valid_csrf_and_rotation():
    from django.conf import settings

    account = user("refresh-valid")
    client = Client(enforce_csrf_checks=True)
    old = JWTService.create_refresh_token(account.id)
    client.cookies[settings.JWT_REFRESH_COOKIE_NAME] = old
    response = client.post("/api/auth/refresh/", {}, content_type="application/json", **csrf_headers(client))
    assert response.status_code == 200
    assert response.json()["refresh"] != old
    response = post(Client(), "/api/auth/refresh/", {"refresh": old})
    assert response.status_code == 401


def test_old_token_same_second_remains_revoked(settings):
    settings.USE_TZ = True
    account = user("old-token")
    issued = datetime(2026, 9, 20, 12, 0, 0, 100000, tzinfo=UTC)
    cutoff = issued.replace(microsecond=500000)
    with patch("core.authentication.jwt_service.datetime") as dt:
        dt.now.return_value = issued
        token = JWTService.create_access_token(account.id)
    with patch("core.authentication.jwt_service.timezone.now", return_value=cutoff):
        revoke_user_tokens(account)
    import jwt
    from django.conf import settings as conf

    decoded = jwt.decode(
        token,
        getattr(conf, "JWT_SECRET_KEY", conf.SECRET_KEY),
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert is_token_revoked(decoded, account)
