import pytest
import secrets
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def auth_context(monkeypatch):
    from app.config import settings
    from app.core.auth import clear_login_failures, hash_password

    password = secrets.token_urlsafe(24)
    session_secret = secrets.token_urlsafe(48)
    wrong_password = secrets.token_urlsafe(24)
    monkeypatch.setattr(settings, "AUTH_PASSWORD_HASH", hash_password(password))
    monkeypatch.setattr(settings, "AUTH_SESSION_SECRET", session_secret)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    clear_login_failures("testclient")

    from app.main import app

    return TestClient(app, follow_redirects=False), password, session_secret, wrong_password


def test_password_hash_verifies_without_storing_plaintext():
    from app.core.auth import hash_password, verify_password

    password = secrets.token_urlsafe(24)
    encoded = hash_password(password)
    assert encoded.startswith("scrypt$")
    assert password not in encoded
    assert verify_password(password, encoded)
    assert not verify_password(secrets.token_urlsafe(24), encoded)


@pytest.mark.parametrize("malformed_component", ["!!!!", "a"])
def test_malformed_password_hash_base64_is_rejected(malformed_component):
    from app.core.auth import AuthConfigurationError, hash_password, validate_auth_configuration

    encoded = hash_password(secrets.token_urlsafe(24))
    _, salt, digest = encoded.split("$")
    malformed_hashes = (
        f"scrypt${malformed_component}${digest}",
        f"scrypt${salt}${malformed_component}",
    )

    for malformed_hash in malformed_hashes:
        with pytest.raises(AuthConfigurationError):
            validate_auth_configuration(malformed_hash, secrets.token_urlsafe(48))


def test_signed_sessions_expire_and_reject_tampering():
    from app.core.auth import (
        SESSION_TTL_SECONDS,
        create_session_token,
        is_valid_session_token,
    )

    session_secret = secrets.token_urlsafe(48)
    token = create_session_token(session_secret, now=1000)
    assert is_valid_session_token(token, session_secret, now=1001)
    assert not is_valid_session_token(token, session_secret, now=1000 + SESSION_TTL_SECONDS)
    assert not is_valid_session_token(token + "x", session_secret, now=1001)


@pytest.mark.parametrize("malformed_signature", ["!!!!", "a"])
def test_malformed_session_token_base64_is_rejected(malformed_signature):
    from app.core.auth import create_session_token, is_valid_session_token

    session_secret = secrets.token_urlsafe(48)
    token = create_session_token(session_secret, now=1000)
    body = token.rsplit(".", 1)[0]

    assert not is_valid_session_token(
        f"{body}.{malformed_signature}",
        session_secret,
        now=1001,
    )


def test_protected_routes_require_login_and_health_is_minimal(auth_context):
    auth_client, _, _, _ = auth_context
    dashboard = auth_client.get("/")
    assert dashboard.status_code == 303
    assert dashboard.headers["location"] == "/login"
    assert auth_client.get("/api/signals/market-status").status_code == 401
    assert auth_client.get("/docs").status_code == 401

    health = auth_client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_login_sets_http_only_cookie_and_unlocks_dashboard(auth_context):
    auth_client, password, _, _ = auth_context
    response = auth_client.post(
        "/api/auth/login",
        json={"password": password},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "secure" not in cookie
    assert password not in response.text

    assert auth_client.get("/").status_code == 200
    assert auth_client.get("/api/signals/market-status").status_code == 200


def test_invalid_login_origin_and_logout_do_not_grant_access(auth_context):
    auth_client, password, _, wrong_password = auth_context
    invalid = auth_client.post(
        "/api/auth/login",
        json={"password": wrong_password},
        headers={"Origin": "http://testserver"},
    )
    assert invalid.status_code == 401
    assert invalid.json() == {"detail": "Invalid credentials."}
    assert password not in invalid.text

    cross_origin = auth_client.post(
        "/api/auth/login",
        json={"password": password},
        headers={"Origin": "https://attacker.example"},
    )
    assert cross_origin.status_code == 403

    login = auth_client.post(
        "/api/auth/login",
        json={"password": password},
        headers={"Origin": "http://testserver"},
    )
    assert login.status_code == 200
    logout = auth_client.post(
        "/api/auth/logout",
        headers={"Origin": "http://testserver"},
    )
    assert logout.status_code == 200
    assert auth_client.get("/api/signals/market-status").status_code == 401


def test_websocket_requires_same_origin_authenticated_session(auth_context):
    auth_client, password, _, _ = auth_context
    with pytest.raises(WebSocketDisconnect):
        with auth_client.websocket_connect(
            "/api/signals/ws",
            headers={"Origin": "http://testserver"},
        ):
            pass

    login = auth_client.post(
        "/api/auth/login",
        json={"password": password},
        headers={"Origin": "http://testserver"},
    )
    assert login.status_code == 200

    with auth_client.websocket_connect(
        "/api/signals/ws",
        headers={"Origin": "http://testserver"},
    ) as websocket:
        websocket.close()


def test_missing_auth_configuration_fails_closed(auth_context, monkeypatch):
    from app.config import settings

    auth_client, password, session_secret, _ = auth_context
    monkeypatch.setattr(settings, "AUTH_SESSION_SECRET", None)
    assert auth_client.get("/api/signals/market-status").status_code == 503
    assert auth_client.get("/health").json() == {"status": "ok"}

    login = auth_client.post(
        "/api/auth/login",
        json={"password": password},
        headers={"Origin": "http://testserver"},
    )
    assert login.status_code == 503
    assert session_secret not in login.text

    with pytest.raises(
        RuntimeError,
        match="AUTH_PASSWORD_HASH and AUTH_SESSION_SECRET",
    ):
        with TestClient(auth_client.app):
            pass


def test_production_session_cookie_is_secure(auth_context, monkeypatch):
    from app.config import settings

    auth_client, password, _, _ = auth_context
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    response = auth_client.post(
        "/api/auth/login",
        json={"password": password},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_login_is_rate_limited(auth_context):
    auth_client, password, _, wrong_password = auth_context
    for _ in range(5):
        response = auth_client.post(
            "/api/auth/login",
            json={"password": wrong_password},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 401

    limited = auth_client.post(
        "/api/auth/login",
        json={"password": wrong_password},
        headers={"Origin": "http://testserver"},
    )
    assert limited.status_code == 429
    assert password not in limited.text
