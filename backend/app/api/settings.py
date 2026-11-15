"""Configurações gerais: dados da clínica, logotipo, profissionais, salas, horários, feriados,
cadastros financeiros e parâmetros do sistema — tudo editável sem alterar código."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.crud import make_crud
from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import get_current_user, require, require_any
from app.core.errors import AppError, NotFound
from app.core.settings_store import DEFAULTS, SECRET_KEYS, get_group, set_setting
from app.models.auth import User
from app.models.clinic import BusinessHour, Holiday, Professional, ProfessionalAvailability, Room
from app.models.finance import CostCenter, FinancialAccount, FinancialCategory, PaymentMethod
from app.models.system import Clinic
from app.schemas.common import ORM, CepStr, ColorStr, CpfStr, DocumentStr, Money, PhoneStr, StrippedModel, UfStr

router = APIRouter(prefix="/settings", tags=["Configurações"])


# ---------------------------------------------------------------- Clínica
class ClinicIn(StrippedModel):
    name: str = Field(min_length=2, max_length=150)
    trade_name: str | None = None
    document: DocumentStr = None
    phone: PhoneStr = None
    whatsapp: PhoneStr = None
    email: EmailStr | None = None
    website: str | None = None
    zip_code: CepStr = None
    street: str | None = None
    number: str | None = None
    complement: str | None = None
    district: str | None = None
    city: str | None = None
    state: UfStr = None


class ClinicOut(ORM):
    id: uuid.UUID
    name: str
    trade_name: str | None
    document: str | None
    phone: str | None
    whatsapp: str | None
    email: str | None
    website: str | None
    zip_code: str | None
    street: str | None
    number: str | None
    complement: str | None
    district: str | None
    city: str | None
    state: str | None
    timezone: str
    has_logo: bool = False


def get_clinic(db: Session) -> Clinic:
    clinic = db.scalar(select(Clinic).limit(1))
    if clinic is None:
        clinic = Clinic(name="Corpo Sano")
        db.add(clinic)
        db.flush()
    return clinic


@router.get("/clinic", response_model=ClinicOut)
def read_clinic(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = get_clinic(db)
    out = ClinicOut.model_validate(c)
    out.has_logo = bool(c.logo)
    return out


@router.put("/clinic", response_model=ClinicOut)
def update_clinic(data: ClinicIn, db: Session = Depends(get_db), user: User = Depends(require("settings.manage"))):
    c = get_clinic(db)
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    audit(db, "clinica_alterada", user=user, entity="clinic", entity_id=c.id, details=data.model_dump())
    db.commit()
    out = ClinicOut.model_validate(c)
    out.has_logo = bool(c.logo)
    return out


@router.get("/clinic/logo/status")
def clinic_logo_status(db: Session = Depends(get_db)):
    """Informa (publicamente) se há logotipo, para a tela de login não pedir uma imagem inexistente."""
    c = db.scalar(select(Clinic).limit(1))
    return {"has_logo": bool(c and c.logo)}


@router.get("/clinic/logo")
def clinic_logo(db: Session = Depends(get_db)):
    """Logotipo público (usado na tela de login e nos relatórios)."""
    c = db.scalar(select(Clinic).limit(1))
    if c is None or not c.logo:
        raise NotFound("Logotipo")
    return Response(content=c.logo, media_type=c.logo_content_type or "image/png",
                    headers={"Cache-Control": "public, max-age=300"})


@router.post("/clinic/logo")
async def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db),
                      user: User = Depends(require("settings.manage"))):
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise AppError("O logotipo deve ter até 2 MB.")
    ctype = (file.content_type or "").split(";")[0]
    signatures = {"image/png": b"\x89PNG", "image/jpeg": b"\xff\xd8\xff", "image/webp": b"RIFF"}
    if ctype not in signatures or not data.startswith(signatures[ctype]):
        raise AppError("Envie uma imagem PNG, JPEG ou WEBP.")
    c = get_clinic(db)
    c.logo, c.logo_content_type = data, ctype
    audit(db, "logotipo_alterado", user=user, entity="clinic", entity_id=c.id)
    db.commit()
    return {"message": "Logotipo atualizado."}


@router.delete("/clinic/logo")
def delete_logo(db: Session = Depends(get_db), user: User = Depends(require("settings.manage"))):
    c = get_clinic(db)
    c.logo, c.logo_content_type = None, None
    audit(db, "logotipo_removido", user=user, entity="clinic", entity_id=c.id)
    db.commit()
    return {"message": "Logotipo removido."}


# ---------------------------------------------------------------- Parâmetros
EDITABLE_GROUPS = {
    "agenda.": "agenda.settings",
    "crm.": "settings.manage",
    "packages.": "settings.manage",
    "finance.": "finance.settings",
    "security.": "settings.manage",
    "lgpd.": "settings.manage",
    "backup.": "backups.manage",
}


@router.get("/params/{group}")
def read_params(group: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prefix = group.rstrip(".") + "."
    if prefix not in EDITABLE_GROUPS:
        raise NotFound("Grupo de configurações")
    return get_group(db, prefix)


@router.put("/params/{group}")
def update_params(group: str, values: dict[str, Any], db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    prefix = group.rstrip(".") + "."
    perm = EDITABLE_GROUPS.get(prefix)
    if perm is None:
        raise NotFound("Grupo de configurações")
    if perm not in getattr(user, "permissions_set", set()):
        raise AppError("Você não tem permissão para esta operação.", status_code=403)
    for key, value in values.items():
        if not key.startswith(prefix) or key not in DEFAULTS or key in SECRET_KEYS:
            raise AppError(f"Parâmetro desconhecido: {key}")
        default = DEFAULTS[key]
        if isinstance(default, bool) and not isinstance(value, bool):
            raise AppError(f"{key}: valor deve ser verdadeiro/falso.")
        if isinstance(default, int) and not isinstance(default, bool) and value is not None:
            if not isinstance(value, int) or value < 0:
                raise AppError(f"{key}: informe um número inteiro não negativo.")
        if isinstance(default, list) and not isinstance(value, list):
            raise AppError(f"{key}: informe uma lista.")
        set_setting(db, key, value, user.id)
    audit(db, "parametros_alterados", user=user, entity="settings", entity_id=prefix, details=values)
    db.commit()
    return get_group(db, prefix)


# ---------------------------------------------------------------- Profissionais
class ProfessionalIn(StrippedModel):
    name: str = Field(min_length=2, max_length=120)
    cpf: CpfStr = None
    phone: PhoneStr = None
    email: EmailStr | None = None
    registration: str | None = None
    specialties: str | None = None
    color: ColorStr = "#2563EB"
    is_active: bool = True


class ProfessionalOut(ORM):
    id: uuid.UUID
    name: str
    cpf: str | None
    phone: str | None
    email: str | None
    registration: str | None
    specialties: str | None
    color: str
    is_active: bool


make_crud(router, path="/professionals", model=Professional, schema_in=ProfessionalIn, schema_out=ProfessionalOut,
          read_perms=("agenda.read", "services.read", "settings.manage", "reports.operational"),
          write_perms=("agenda.settings", "settings.manage"), entity="profissional", order_by=Professional.name)


class AvailabilityItem(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: dt.time
    end_time: dt.time


@router.get("/professionals/{professional_id}/availability", response_model=list[AvailabilityItem])
def get_availability(professional_id: uuid.UUID, db: Session = Depends(get_db),
                     user: User = Depends(require("agenda.read"))):
    rows = db.scalars(select(ProfessionalAvailability).where(ProfessionalAvailability.professional_id == professional_id)
                      .order_by(ProfessionalAvailability.weekday, ProfessionalAvailability.start_time)).all()
    return [AvailabilityItem(weekday=r.weekday, start_time=r.start_time, end_time=r.end_time) for r in rows]


@router.put("/professionals/{professional_id}/availability", response_model=list[AvailabilityItem])
def set_availability(professional_id: uuid.UUID, items: list[AvailabilityItem], db: Session = Depends(get_db),
                     user: User = Depends(require_any("agenda.settings", "settings.manage"))):
    if db.get(Professional, professional_id) is None:
        raise NotFound("Profissional")
    for it in items:
        if it.end_time <= it.start_time:
            raise AppError("Horário final deve ser posterior ao inicial.")
    db.execute(delete(ProfessionalAvailability).where(ProfessionalAvailability.professional_id == professional_id))
    for it in items:
        db.add(ProfessionalAvailability(professional_id=professional_id, **it.model_dump()))
    audit(db, "disponibilidade_alterada", user=user, entity="professional", entity_id=professional_id,
          details={"itens": [i.model_dump(mode="json") for i in items]})
    db.commit()
    return items


# ---------------------------------------------------------------- Salas
class RoomIn(StrippedModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = None
    color: str = Field(default="#8B5CF6", pattern=r"^#[0-9A-Fa-f]{6}$")
    is_active: bool = True


class RoomOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    color: str
    is_active: bool


make_crud(router, path="/rooms", model=Room, schema_in=RoomIn, schema_out=RoomOut,
          read_perms=("agenda.read", "settings.manage"), write_perms=("agenda.settings", "settings.manage"),
          entity="sala", order_by=Room.name)


# ---------------------------------------------------------------- Horário de funcionamento
class BusinessHourItem(BaseModel):
    weekday: int = Field(ge=0, le=6)
    is_open: bool
    open_time: dt.time | None = None
    close_time: dt.time | None = None
    break_start: dt.time | None = None
    break_end: dt.time | None = None


@router.get("/business-hours", response_model=list[BusinessHourItem])
def get_hours(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(BusinessHour).order_by(BusinessHour.weekday)).all()
    return [BusinessHourItem.model_validate(r, from_attributes=True) for r in rows]


@router.put("/business-hours", response_model=list[BusinessHourItem])
def set_hours(items: list[BusinessHourItem], db: Session = Depends(get_db),
              user: User = Depends(require_any("agenda.settings", "settings.manage"))):
    for it in items:
        if it.is_open:
            if not it.open_time or not it.close_time or it.close_time <= it.open_time:
                raise AppError("Informe abertura e fechamento válidos para os dias de funcionamento.")
            if (it.break_start is None) != (it.break_end is None):
                raise AppError("Informe início e fim do intervalo.")
            if it.break_start and not (it.open_time <= it.break_start < it.break_end <= it.close_time):
                raise AppError("O intervalo deve estar dentro do horário de funcionamento.")
    db.execute(delete(BusinessHour))
    for it in items:
        db.add(BusinessHour(**it.model_dump()))
    audit(db, "horarios_alterados", user=user, entity="business_hours",
          details={"itens": [i.model_dump(mode="json") for i in items]})
    db.commit()
    return items


# ---------------------------------------------------------------- Feriados
class HolidayIn(StrippedModel):
    date: dt.date
    name: str = Field(min_length=2, max_length=120)
    recurring: bool = False


class HolidayOut(ORM):
    id: uuid.UUID
    date: dt.date
    name: str
    recurring: bool


make_crud(router, path="/holidays", model=Holiday, schema_in=HolidayIn, schema_out=HolidayOut,
          read_perms=("agenda.read", "settings.manage"), write_perms=("agenda.settings", "settings.manage"),
          entity="feriado", order_by=Holiday.date)


# ---------------------------------------------------------------- Financeiro (cadastros)
class PaymentMethodIn(StrippedModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=60)
    fee_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=2)
    settlement_days: int = Field(default=0, ge=0, le=120)
    is_active: bool = True


class PaymentMethodOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    fee_percent: Money
    settlement_days: int
    is_active: bool


make_crud(router, path="/payment-methods", model=PaymentMethod, schema_in=PaymentMethodIn, schema_out=PaymentMethodOut,
          read_perms=("finance.read", "finance.payments", "agenda.read", "packages.read", "fiscal.read"),
          write_perms=("finance.settings",), entity="forma_pagamento", order_by=PaymentMethod.name)


class AccountIn(StrippedModel):
    name: str = Field(min_length=2, max_length=80)
    kind: str = Field(pattern=r"^(caixa|banco|carteira|outro)$")
    bank_name: str | None = None
    agency: str | None = None
    account_number: str | None = None
    opening_balance: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    opening_date: dt.date | None = None
    is_active: bool = True


class AccountOut(ORM):
    id: uuid.UUID
    name: str
    kind: str
    bank_name: str | None
    agency: str | None
    account_number: str | None
    opening_balance: Money
    opening_date: dt.date | None
    is_active: bool


make_crud(router, path="/financial-accounts", model=FinancialAccount, schema_in=AccountIn, schema_out=AccountOut,
          read_perms=("finance.read", "finance.payments", "fiscal.read"), write_perms=("finance.settings",),
          entity="conta_financeira", order_by=FinancialAccount.name)


class CategoryIn(StrippedModel):
    name: str = Field(min_length=2, max_length=80)
    kind: str = Field(pattern=r"^(receita|despesa)$")
    is_active: bool = True


class CategoryOut(ORM):
    id: uuid.UUID
    name: str
    kind: str
    is_active: bool


make_crud(router, path="/financial-categories", model=FinancialCategory, schema_in=CategoryIn, schema_out=CategoryOut,
          read_perms=("finance.read", "finance.payments", "fiscal.read"), write_perms=("finance.settings",),
          entity="categoria_financeira", order_by=FinancialCategory.name)


class CostCenterIn(StrippedModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = None
    is_active: bool = True


class CostCenterOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool


make_crud(router, path="/cost-centers", model=CostCenter, schema_in=CostCenterIn, schema_out=CostCenterOut,
          read_perms=("finance.read", "fiscal.read"), write_perms=("finance.settings",),
          entity="centro_custo", order_by=CostCenter.name)
