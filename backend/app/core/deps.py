"""Dependências FastAPI: usuário autenticado, permissões e IP do cliente."""
from __future__ import annotations

import ipaddress
import uuid
from datetime import timedelta

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError, Forbidden
from app.core.security import decode_access_token
from app.core.settings_store import get_setting
from app.core.utils import utcnow
from app.models.auth import User, UserSession


def _trusted(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for net in get_settings().trusted_proxies.split(","):
        net = net.strip()
        if not net:
            continue
        try:
            if addr in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request) -> str:
    """IP real do cliente; só confia em X-Forwarded-For vindo do proxy reverso."""
    peer = request.client.host if request.client else "0.0.0.0"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _trusted(peer):
        return forwarded.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real and _trusted(peer):
        return real.strip()
    return peer


def effective_permissions(user: User) -> set[str]:
    perms = {p.code for p in user.role.permissions}
    for ov in user.overrides:
        if ov.allow:
            perms.add(ov.permission.code)
        else:
            perms.discard(ov.permission.code)
    return perms


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise AppError("Autenticação necessária.", code="nao_autenticado", status_code=401)
    payload = decode_access_token(auth[7:].strip())
    try:
        user_id = uuid.UUID(payload["sub"])
        session_id = uuid.UUID(payload["sid"])
    except (KeyError, ValueError) as exc:
        raise AppError("Token inválido.", code="token_invalido", status_code=401) from exc
    session = db.get(UserSession, session_id)
    now = utcnow()
    if session is None or session.revoked_at is not None or session.expires_at <= now or session.user_id != user_id:
        raise AppError("Sessão encerrada. Entre novamente.", code="sessao_encerrada", status_code=401)
    idle = int(get_setting(db, "security.session_idle_minutes") or 30)
    if session.last_used_at < now - timedelta(minutes=idle + get_settings().access_token_minutes):
        raise AppError("Sessão encerrada por inatividade.", code="sessao_inativa", status_code=401)
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError("Usuário inativo.", code="usuario_inativo", status_code=401)
    user.permissions_set = effective_permissions(user)  # type: ignore[attr-defined]
    user.session_id = session_id  # type: ignore[attr-defined]
    user._request_ip = client_ip(request)  # type: ignore[attr-defined]
    return user


def has_perm(user: User, *perms: str) -> bool:
    granted: set[str] = getattr(user, "permissions_set", set())
    return all(p in granted for p in perms)


def require(*perms: str):
    """Exige TODAS as permissões listadas."""

    def dep(user: User = Depends(get_current_user)) -> User:
        if getattr(user, "must_change_password", False):
            raise AppError("Altere sua senha para continuar.", code="troca_senha_obrigatoria", status_code=403)
        if not has_perm(user, *perms):
            raise Forbidden()
        return user

    return dep


def require_any(*perms: str):
    """Exige AO MENOS UMA das permissões listadas."""

    def dep(user: User = Depends(get_current_user)) -> User:
        if getattr(user, "must_change_password", False):
            raise AppError("Altere sua senha para continuar.", code="troca_senha_obrigatoria", status_code=403)
        if not any(has_perm(user, p) for p in perms):
            raise Forbidden()
        return user

    return dep
