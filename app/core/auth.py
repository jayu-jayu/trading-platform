"""Single-password session authentication helpers."""
import base64
import binascii
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque


SESSION_COOKIE_NAME = "trading_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_KEY_LENGTH = 32
LOGIN_ATTEMPT_WINDOW_SECONDS = 15 * 60
MAX_LOGIN_FAILURES_PER_WINDOW = 5

_login_failures: dict[str, deque[float]] = defaultdict(deque)
_login_failure_lock = threading.Lock()


class AuthConfigurationError(ValueError):
    """Raised when required authentication settings are missing or invalid."""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _parse_password_hash(encoded: str) -> tuple[bytes, bytes]:
    try:
        algorithm, salt_text, digest_text = encoded.split("$")
        salt = _b64decode(salt_text)
        digest = _b64decode(digest_text)
    except (ValueError, UnicodeEncodeError, binascii.Error):
        raise AuthConfigurationError(
            "AUTH_PASSWORD_HASH must be a valid scrypt hash."
        ) from None

    if algorithm != "scrypt" or len(salt) != 16 or len(digest) != SCRYPT_KEY_LENGTH:
        raise AuthConfigurationError("AUTH_PASSWORD_HASH must be a valid scrypt hash.")
    return salt, digest


def validate_auth_configuration(
    password_hash: str | None,
    session_secret: str | None,
) -> None:
    if not password_hash or not session_secret:
        raise AuthConfigurationError(
            "AUTH_PASSWORD_HASH and AUTH_SESSION_SECRET must be configured."
        )
    _parse_password_hash(password_hash)
    if len(session_secret.encode("utf-8")) < 32:
        raise AuthConfigurationError(
            "AUTH_SESSION_SECRET must contain at least 32 bytes."
        )


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_KEY_LENGTH,
    )
    return f"scrypt${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded_hash: str) -> bool:
    salt, expected = _parse_password_hash(encoded_hash)
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_KEY_LENGTH,
    )
    return hmac.compare_digest(actual, expected)


def create_session_token(session_secret: str, now: int | None = None) -> str:
    expires_at = (now if now is not None else int(time.time())) + SESSION_TTL_SECONDS
    body = f"{expires_at}.{secrets.token_urlsafe(24)}"
    signature = hmac.new(
        session_secret.encode("utf-8"),
        body.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{body}.{_b64encode(signature)}"


def is_valid_session_token(
    token: str | None,
    session_secret: str,
    now: int | None = None,
) -> bool:
    if not token or len(token) > 256:
        return False
    try:
        expires_text, nonce, signature_text = token.split(".")
        expires_at = int(expires_text)
        supplied_signature = _b64decode(signature_text)
    except (ValueError, UnicodeEncodeError, binascii.Error):
        return False

    current_time = now if now is not None else int(time.time())
    if not nonce or expires_at <= current_time:
        return False

    body = f"{expires_text}.{nonce}"
    try:
        expected_signature = hmac.new(
            session_secret.encode("utf-8"),
            body.encode("ascii"),
            hashlib.sha256,
        ).digest()
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(supplied_signature, expected_signature)


def is_same_origin(origin: str | None, host: str | None) -> bool:
    if not origin or not host:
        return False
    try:
        from urllib.parse import urlsplit

        parsed = urlsplit(origin)
        return (
            parsed.scheme in ("http", "https")
            and parsed.netloc.casefold() == host.casefold()
            and not parsed.username
            and not parsed.password
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def login_attempt_allowed(client_key: str, now: float | None = None) -> bool:
    current_time = now if now is not None else time.monotonic()
    cutoff = current_time - LOGIN_ATTEMPT_WINDOW_SECONDS
    with _login_failure_lock:
        for key in list(_login_failures):
            attempts = _login_failures[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts:
                del _login_failures[key]

        if client_key not in _login_failures and len(_login_failures) >= 1024:
            client_key = "__overflow__"
        return len(_login_failures[client_key]) < MAX_LOGIN_FAILURES_PER_WINDOW


def record_login_failure(client_key: str, now: float | None = None) -> None:
    current_time = now if now is not None else time.monotonic()
    with _login_failure_lock:
        if client_key not in _login_failures and len(_login_failures) >= 1024:
            client_key = "__overflow__"
        _login_failures[client_key].append(current_time)


def clear_login_failures(client_key: str) -> None:
    with _login_failure_lock:
        _login_failures.pop(client_key, None)
