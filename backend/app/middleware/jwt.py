"""JWT helpers (issue + verify) used by the auth middleware and a small test route."""
from __future__ import annotations

import time

import jwt

from ..config import settings


def issue_token(subject: str, roles: list[str], ttl_minutes: int | None = None) -> str:
    ttl = ttl_minutes or settings.jwt_expires_minutes
    payload = {
        "sub": subject,
        "roles": roles,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
