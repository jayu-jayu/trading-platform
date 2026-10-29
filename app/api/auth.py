"""Login and logout endpoints for the single-user dashboard."""
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.core.auth import (
    AuthConfigurationError,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    clear_login_failures,
    create_session_token,
    login_attempt_allowed,
    record_login_failure,
    validate_auth_configuration,
    verify_password,
)


router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/login")
async def login(request: Request, response: Response):
    try:
        validate_auth_configuration(
            settings.AUTH_PASSWORD_HASH,
            settings.AUTH_SESSION_SECRET,
        )
    except AuthConfigurationError:
        return JSONResponse(
            status_code=503,
            content={"detail": "Authentication is unavailable."},
            headers={"Cache-Control": "no-store"},
        )
    assert settings.AUTH_PASSWORD_HASH is not None
    assert settings.AUTH_SESSION_SECRET is not None

    client_key = request.client.host if request.client else "unknown"
    if not login_attempt_allowed(client_key):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many sign-in attempts. Try again later."},
            headers={"Cache-Control": "no-store"},
        )

    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid request."},
            headers={"Cache-Control": "no-store"},
        )

    password = payload.get("password") if isinstance(payload, dict) else None
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid request."},
            headers={"Cache-Control": "no-store"},
        )

    try:
        valid = await run_in_threadpool(
            verify_password,
            password,
            settings.AUTH_PASSWORD_HASH,
        )
    except AuthConfigurationError:
        return JSONResponse(
            status_code=503,
            content={"detail": "Authentication is unavailable."},
            headers={"Cache-Control": "no-store"},
        )

    if not valid:
        record_login_failure(client_key)
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid credentials."},
            headers={"Cache-Control": "no-store"},
        )

    clear_login_failures(client_key)
    session_token = create_session_token(settings.AUTH_SESSION_SECRET)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.ENVIRONMENT.casefold() != "development",
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.ENVIRONMENT.casefold() != "development",
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": False}
