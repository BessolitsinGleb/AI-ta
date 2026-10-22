"""Пароли (bcrypt) и токены (JWT): access, refresh, подтверждение почты, сброс пароля."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings

log = logging.getLogger("amba.security")
ALGO = "HS256"

_secret = settings.jwt_secret
if not _secret:
    _secret = secrets.token_urlsafe(48)
    log.warning("JWT_SECRET не задан — сгенерирован временный: после перезапуска все сессии сбросятся")


def hash_password(password: str) -> str:
    # bcrypt учитывает только первые 72 байта — заранее сворачиваем длинные пароли в sha256.
    pw = password.encode()
    if len(pw) > 72:
        pw = hashlib.sha256(pw).hexdigest().encode()
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    pw = password.encode()
    if len(pw) > 72:
        pw = hashlib.sha256(pw).hexdigest().encode()
    try:
        return bcrypt.checkpw(pw, hashed.encode())
    except ValueError:
        return False


DUMMY_HASH = hash_password(secrets.token_hex(8))  # для выравнивания времени ответа при несуществующей почте


def _encode(payload: dict, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({**payload, "iat": now, "exp": now + ttl}, _secret, algorithm=ALGO)


def decode(token: str, purpose: str) -> dict:
    """Проверяет подпись, срок и назначение. Бросает jwt.PyJWTError."""
    data = jwt.decode(token, _secret, algorithms=[ALGO], options={"require": ["exp", "iat", "sub", "typ"]})
    if data.get("typ") != purpose:
        raise jwt.InvalidTokenError("wrong token type")
    return data


def access_token(user_id: str, token_version: int) -> str:
    return _encode({"sub": user_id, "typ": "access", "tv": token_version}, timedelta(minutes=settings.access_ttl_min))


def refresh_token(user_id: str, jti: str) -> str:
    return _encode({"sub": user_id, "typ": "refresh", "jti": jti}, timedelta(days=settings.refresh_ttl_days))


def verify_email_token(user_id: str, email: str) -> str:
    return _encode({"sub": user_id, "typ": "verify", "email": email}, timedelta(hours=24))


def reset_token(user_id: str, token_version: int) -> str:
    # tv делает ссылку одноразовой: после смены пароля token_version растёт и ссылка перестаёт работать.
    return _encode({"sub": user_id, "typ": "reset", "tv": token_version}, timedelta(hours=1))
