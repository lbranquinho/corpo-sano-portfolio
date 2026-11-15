from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import require
from app.core.errors import AppError, Conflict, NotFound
from app.core.permissions import PERMISSIONS
from app.core.security import hash_password, validate_password_strength
from app.core.utils import utcnow
from app.models.auth import Permission, Role, User, UserPermission, UserSession
from app.models.system import AuditLog
from app.schemas.common import ORM, Page

router = APIRouter(tags=["Usuários e permissões"])
ADMIN = require("users.manage")


class UserOut(ORM):
    id: uuid.UUID
    name: str
    email: str
    role_id: uuid.UUID
    role_name: str | None = None
    professional_id: uuid.UUID | None
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    locked_until: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    role_id: uuid.UUID
    professional_id: uuid.UUID | None = None
    password: str


class UserUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    role_id: uuid.UUID
    professional_id: uuid.UUID | None = None
    is_active: bool = True


class ResetPasswordIn(BaseModel):
    password: str


class RoleOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_system: bool
    permissions: list[str]


class RoleIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = None
    permissions: list[str]


class OverrideIn(BaseModel):
    code: str
    allow: bool


class AuditOut(ORM):
    id: int
    created_at: datetime
    user_name: str | None
    action: str
    entity: str | None
    entity_id: str | None
    ip: str | None
    sensitive: bool
    details: dict | None


def _user_out(u: User) -> UserOut:
    out = UserOut.model_validate(u)
    out.role_name = u.role.name if u.role else None
    return out


def _role_out(r: Role) -> RoleOut:
    return RoleOut(
        id=r.id, code=r.code, name=r.name, description=r.description, is_system=r.is_system,
        permissions=sorted(p.code for p in r.permissions),
    )


def _active_admins(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(User).join(Role).where(Role.code == "admin", User.is_active.is_(True))
    ) or 0


@router.get("/permissions")
def list_permissions(user: User = Depends(ADMIN)):
    return [{"code": c, "module": m, "description": d} for c, (m, d) in PERMISSIONS.items()]


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    return [_user_out(u) for u in db.scalars(select(User).order_by(User.name)).all()]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise Conflict("Já existe um usuário com este e-mail.")
    if db.get(Role, data.role_id) is None:
        raise NotFound("Perfil")
    validate_password_strength(data.password)
    new = User(
        name=data.name, email=email, role_id=data.role_id, professional_id=data.professional_id,
        password_hash=hash_password(data.password), must_change_password=True,
    )
    db.add(new)
    db.flush()
    audit(db, "usuario_criado", user=user, entity="user", entity_id=new.id, details={"email": email})
    db.commit()
    db.refresh(new)
    return _user_out(new)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, data: UserUpdate, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    target = db.get(User, user_id)
    if target is None:
        raise NotFound("Usuário")
    email = data.email.lower()
    other = db.scalar(select(User).where(User.email == email, User.id != user_id))
    if other:
        raise Conflict("Já existe um usuário com este e-mail.")
    role = db.get(Role, data.role_id)
    if role is None:
        raise NotFound("Perfil")
    if target.id == user.id and (not data.is_active or role.code != "admin"):
        raise AppError("Você não pode desativar ou rebaixar o próprio acesso de administrador.")
    if target.role.code == "admin" and (role.code != "admin" or not data.is_active) and _active_admins(db) <= 1:
        raise AppError("É necessário manter pelo menos um administrador ativo.")
    changes = {"name": data.name, "email": email, "role": role.code, "is_active": data.is_active}
    target.name, target.email, target.role_id = data.name, email, data.role_id
    target.professional_id, target.is_active = data.professional_id, data.is_active
    if not data.is_active:
        for s in db.scalars(select(UserSession).where(UserSession.user_id == target.id, UserSession.revoked_at.is_(None))):
            s.revoked_at = utcnow()
    audit(db, "usuario_alterado", user=user, entity="user", entity_id=target.id, details=changes)
    db.commit()
    db.refresh(target)
    return _user_out(target)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: uuid.UUID, data: ResetPasswordIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    target = db.get(User, user_id)
    if target is None:
        raise NotFound("Usuário")
    validate_password_strength(data.password)
    target.password_hash = hash_password(data.password)
    target.must_change_password = True
    target.failed_attempts = 0
    target.locked_until = None
    for s in db.scalars(select(UserSession).where(UserSession.user_id == target.id, UserSession.revoked_at.is_(None))):
        s.revoked_at = utcnow()
    audit(db, "senha_redefinida", user=user, entity="user", entity_id=target.id)
    db.commit()
    return {"message": "Senha provisória definida. O usuário deverá trocá-la no próximo acesso."}


@router.post("/users/{user_id}/unlock")
def unlock_user(user_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    target = db.get(User, user_id)
    if target is None:
        raise NotFound("Usuário")
    target.failed_attempts, target.locked_until = 0, None
    audit(db, "usuario_desbloqueado", user=user, entity="user", entity_id=target.id)
    db.commit()
    return {"message": "Usuário desbloqueado."}


@router.post("/users/{user_id}/revoke-sessions")
def revoke_sessions(user_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    n = 0
    for s in db.scalars(select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))):
        s.revoked_at = utcnow()
        n += 1
    audit(db, "sessoes_revogadas", user=user, entity="user", entity_id=user_id, details={"quantidade": n})
    db.commit()
    return {"message": f"{n} sessão(ões) encerrada(s)."}


@router.get("/users/{user_id}/permissions")
def get_user_permissions(user_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    target = db.get(User, user_id)
    if target is None:
        raise NotFound("Usuário")
    return {
        "role_permissions": sorted(p.code for p in target.role.permissions),
        "overrides": [{"code": o.permission.code, "allow": o.allow} for o in target.overrides],
    }


@router.put("/users/{user_id}/permissions")
def set_user_permissions(
    user_id: uuid.UUID, data: list[OverrideIn], db: Session = Depends(get_db), user: User = Depends(ADMIN)
):
    target = db.get(User, user_id)
    if target is None:
        raise NotFound("Usuário")
    perms = {p.code: p for p in db.scalars(select(Permission)).all()}
    unknown = [o.code for o in data if o.code not in perms]
    if unknown:
        raise AppError(f"Permissões desconhecidas: {', '.join(unknown)}")
    target.overrides.clear()
    db.flush()
    for o in data:
        target.overrides.append(UserPermission(permission_id=perms[o.code].id, allow=o.allow))
    audit(db, "permissoes_usuario_alteradas", user=user, entity="user", entity_id=target.id,
          details={"overrides": [o.model_dump() for o in data]})
    db.commit()
    return {"message": "Permissões personalizadas salvas."}


@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    return [_role_out(r) for r in db.scalars(select(Role).order_by(Role.name)).all()]


def _apply_role(db: Session, role: Role, data: RoleIn) -> None:
    perms = {p.code: p for p in db.scalars(select(Permission)).all()}
    unknown = [c for c in data.permissions if c not in perms]
    if unknown:
        raise AppError(f"Permissões desconhecidas: {', '.join(unknown)}")
    role.name, role.description = data.name, data.description
    role.permissions = [perms[c] for c in data.permissions]


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(data: RoleIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    code = "custom_" + uuid.uuid4().hex[:8]
    role = Role(code=code, name=data.name, is_system=False)
    _apply_role(db, role, data)
    db.add(role)
    audit(db, "perfil_criado", user=user, entity="role", entity_id=code, details=data.model_dump())
    db.commit()
    db.refresh(role)
    return _role_out(role)


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(role_id: uuid.UUID, data: RoleIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    role = db.get(Role, role_id)
    if role is None:
        raise NotFound("Perfil")
    if role.code == "admin" and set(data.permissions) != set(PERMISSIONS):
        raise AppError("O perfil Administrador mantém acesso completo; personalize outro perfil.")
    _apply_role(db, role, data)
    audit(db, "perfil_alterado", user=user, entity="role", entity_id=role.id, details=data.model_dump())
    db.commit()
    db.refresh(role)
    return _role_out(role)


@router.delete("/roles/{role_id}")
def delete_role(role_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    role = db.get(Role, role_id)
    if role is None:
        raise NotFound("Perfil")
    if role.is_system:
        raise AppError("Perfis padrão não podem ser excluídos.")
    if db.scalar(select(func.count()).select_from(User).where(User.role_id == role_id)):
        raise Conflict("Existem usuários com este perfil.")
    db.delete(role)
    audit(db, "perfil_excluido", user=user, entity="role", entity_id=role_id)
    db.commit()
    return {"message": "Perfil excluído."}


@router.get("/audit-logs", response_model=Page[AuditOut])
def audit_logs(
    action: str | None = None,
    entity: str | None = None,
    user_name: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require("audit.read")),
):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if user_name:
        stmt = stmt.where(AuditLog.user_name.ilike(f"%{user_name}%"))
    if date_from:
        stmt = stmt.where(func.date(AuditLog.created_at) >= date_from)
    if date_to:
        stmt = stmt.where(func.date(AuditLog.created_at) <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[AuditOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)
