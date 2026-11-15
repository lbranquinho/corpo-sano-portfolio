"""Autenticação: hash Argon2id, JWT de curta duração e refresh token rotativo."""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.utils import utcnow

_hasher = PasswordHasher()  # Argon2id com parâmetros recomendados (RFC 9106)
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate_password_strength(password: str) -> None:
    min_len = get_settings().password_min_length
    problems = []
    if len(password) < min_len:
        problems.append(f"no mínimo {min_len} caracteres")
    if not re.search(r"[A-Za-z]", password):
        problems.append("letras")
    if not re.search(r"\d", password):
        problems.append("números")
    if problems:
        raise AppError("A senha deve conter " + ", ".join(problems) + ".", code="senha_fraca")


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID) -> tuple[str, int]:
    settings = get_settings()
    minutes = settings.access_token_minutes
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM), minutes * 60


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AppError("Sessão expirada.", code="token_expirado", status_code=401) from exc
    except jwt.PyJWTError as exc:
        raise AppError("Token inválido.", code="token_invalido", status_code=401) from exc
    if payload.get("typ") != "access":
        raise AppError("Token inválido.", code="token_invalido", status_code=401)
    return payload


def new_refresh_token() -> tuple[str, str]:
    """Retorna (token em claro para o cookie, hash SHA-256 para o banco)."""
    token = secrets.token_urlsafe(48)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
