from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import client_ip, effective_permissions, get_current_user
from app.core.errors import AppError
from app.core.ratelimit import limiter
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    needs_rehash,
    new_refresh_token,
    validate_password_strength,
    verify_password,
)
from app.core.settings_store import get_setting
from app.core.utils import utcnow
from app.models.auth import User, UserSession
from app.models.system import Clinic

router = APIRouter(prefix="/auth", tags=["Autenticação"])

GENERIC_LOGIN_ERROR = "E-mail ou senha inválidos."
_DUMMY: list[str] = []


def _dummy_hash() -> str:
    if not _DUMMY:
        _DUMMY.append(hash_password(uuid.uuid4().hex))
    return _DUMMY[0]


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool


class MeOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    role_name: str
    professional_id: uuid.UUID | None
    permissions: list[str]
    must_change_password: bool
    session_idle_minutes: int
    clinic_name: str | None
    has_logo: bool


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool


def _set_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.refresh_cookie_name,
        token,
        max_age=s.refresh_token_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(s.refresh_cookie_name, path="/api/v1/auth", secure=s.cookie_secure, httponly=True, samesite="strict")


def _start_session(db: Session, user: User, request: Request, response: Response) -> TokenOut:
    s = get_settings()
    token, token_hash = new_refresh_token()
    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=utcnow() + timedelta(days=s.refresh_token_days),
        last_used_at=utcnow(),
        ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:300],
    )
    db.add(session)
    access, expires = create_access_token(user.id, session.id)
    _set_refresh_cookie(response, token)
    return TokenOut(access_token=access, expires_in=expires, must_change_password=user.must_change_password)


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    ip = client_ip(request)
    email = data.email.lower().strip()
    if not limiter.hit(f"login-ip:{ip}", s.login_rate_limit_per_minute) or not limiter.hit(
        f"login-user:{email}", s.login_rate_limit_per_minute
    ):
        raise AppError("Muitas tentativas. Aguarde um minuto e tente novamente.", code="limite", status_code=429)
    user = db.scalar(select(User).where(User.email == email))
    now = utcnow()
    if user is None:
        verify_password(data.password, _dummy_hash())  # tempo de resposta equivalente
        audit(db, "login_falha", details={"email": email, "motivo": "usuario_inexistente"}, ip=ip)
        db.commit()
        raise AppError(GENERIC_LOGIN_ERROR, code="credenciais_invalidas", status_code=401)
    if user.locked_until and user.locked_until > now:
        audit(db, "login_bloqueado", user=user, ip=ip)
        db.commit()
        raise AppError(
            "Conta temporariamente bloqueada por tentativas inválidas. Tente mais tarde.",
            code="conta_bloqueada",
            status_code=423,
        )
    if not verify_password(data.password, user.password_hash) or not user.is_active:
        user.failed_attempts += 1
        if user.failed_attempts >= s.login_max_attempts:
            user.locked_until = now + timedelta(minutes=s.login_lock_minutes)
            user.failed_attempts = 0
        audit(db, "login_falha", user=user, ip=ip, details={"inativo": not user.is_active})
        db.commit()
        raise AppError(GENERIC_LOGIN_ERROR, code="credenciais_invalidas", status_code=401)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    out = _start_session(db, user, request, response)
    audit(db, "login", user=user, ip=ip)
    db.commit()
    return out


@router.post("/refresh", response_model=TokenOut, responses={204: {"description": "Nenhuma sessão salva"}})
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    token = request.cookies.get(s.refresh_cookie_name)
    if not token:
        # navegador sem sessão salva (ex.: tela de login): não é erro, evita 401 no console
        return Response(status_code=204)
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    now = utcnow()
    idle = int(get_setting(db, "security.session_idle_minutes") or 30)
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        _clear_refresh_cookie(response)
        raise AppError("Sessão encerrada. Entre novamente.", code="sessao_encerrada", status_code=401)
    if session.last_used_at < now - timedelta(minutes=idle):
        session.revoked_at = now
        db.commit()
        _clear_refresh_cookie(response)
        raise AppError("Sessão encerrada por inatividade.", code="sessao_inativa", status_code=401)
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        session.revoked_at = now
        db.commit()
        raise AppError("Usuário inativo.", code="usuario_inativo", status_code=401)
    # rotação do refresh token
    new_token, new_hash = new_refresh_token()
    session.token_hash = new_hash
    session.last_used_at = now
    access, expires = create_access_token(user.id, session.id)
    db.commit()
    _set_refresh_cookie(response, new_token)
    return TokenOut(access_token=access, expires_in=expires, must_change_password=user.must_change_password)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(get_settings().refresh_cookie_name)
    if token:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
        if session and session.revoked_at is None:
            session.revoked_at = utcnow()
            user = db.get(User, session.user_id)
            audit(db, "logout", user=user, ip=client_ip(request))
            db.commit()
    _clear_refresh_cookie(response)
    return {"message": "Sessão encerrada."}


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    clinic = db.scalar(select(Clinic).limit(1))
    return MeOut(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role.code,
        role_name=user.role.name,
        professional_id=user.professional_id,
        permissions=sorted(effective_permissions(user)),
        must_change_password=user.must_change_password,
        session_idle_minutes=int(get_setting(db, "security.session_idle_minutes") or 30),
        clinic_name=(clinic.trade_name or clinic.name) if clinic else None,
        has_logo=bool(clinic and clinic.logo),
    )


@router.post("/change-password")
def change_password(data: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise AppError("Senha atual incorreta.", code="senha_incorreta")
    if data.current_password == data.new_password:
        raise AppError("A nova senha deve ser diferente da atual.")
    validate_password_strength(data.new_password)
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    # encerra as demais sessões
    for s in db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))):
        if s.id != getattr(user, "session_id", None):
            s.revoked_at = utcnow()
    audit(db, "senha_alterada", user=user, entity="user", entity_id=user.id)
    db.commit()
    return {"message": "Senha alterada com sucesso."}


@router.get("/sessions", response_model=list[SessionOut])
def my_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None), UserSession.expires_at > utcnow())
        .order_by(UserSession.last_used_at.desc())
    ).all()
    return [
        SessionOut(
            id=r.id,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            expires_at=r.expires_at,
            ip=r.ip,
            user_agent=r.user_agent,
            current=r.id == getattr(user, "session_id", None),
        )
        for r in rows
    ]


@router.delete("/sessions/{session_id}")
def revoke_my_session(session_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(UserSession, session_id)
    if s is None or s.user_id != user.id:
        raise AppError("Sessão não encontrada.", status_code=404)
    s.revoked_at = utcnow()
    audit(db, "sessao_revogada", user=user, entity="session", entity_id=session_id)
    db.commit()
    return {"message": "Sessão encerrada."}
