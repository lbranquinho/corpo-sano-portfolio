from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.crud import make_crud
from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import require, require_any
from app.core.errors import AppError, Conflict, NotFound
from app.core.utils import only_digits, utcnow
from app.models.auth import User
from app.models.catalog import PackagePlan, Service, ServiceCategory, TaxServiceCode
from app.models.clinic import Professional
from app.schemas.common import ORM, ColorStr, Money, StrippedModel

router = APIRouter(tags=["Serviços"])

SUGGESTED_MODALITIES = [
    "Massagem relaxante", "Massagem terapêutica", "Massagem desportiva", "Drenagem linfática",
    "Massagem modeladora", "Reflexologia", "Pedras quentes",
]


# ---------------------------------------------------------------- Categorias
class CategoryIn(StrippedModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = None
    color: ColorStr = "#2563EB"
    is_active: bool = True


class CategoryOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    color: str
    is_active: bool


make_crud(router, path="/service-categories", model=ServiceCategory, schema_in=CategoryIn, schema_out=CategoryOut,
          read_perms=("services.read",), write_perms=("services.write",), entity="categoria_servico",
          order_by=ServiceCategory.name)


# ---------------------------------------------------------------- Códigos fiscais
class TaxCodeIn(StrippedModel):
    national_code: str = Field(description="Código de tributação nacional (cTribNac) — 6 dígitos")
    municipal_code: str | None = Field(default=None, max_length=20)
    lc116_item: str | None = Field(default=None, max_length=10)
    nbs_code: str | None = None
    description: str = Field(min_length=3, max_length=300)
    iss_rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    iss_withheld_default: bool = False
    validated: bool = False
    validated_by: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    is_active: bool = True


class TaxCodeOut(ORM):
    id: uuid.UUID
    national_code: str
    municipal_code: str | None
    lc116_item: str | None
    nbs_code: str | None
    description: str
    iss_rate: Money | None
    iss_withheld_default: bool
    validated: bool
    validated_by: str | None
    validated_at: datetime | None
    notes: str | None
    is_active: bool


def _validate_tax_code(db: Session, values: dict, obj) -> None:
    code = only_digits(values["national_code"])
    if len(code) != 6:
        raise AppError("O código de tributação nacional deve ter 6 dígitos (conforme a lista do Sistema Nacional NFS-e).")
    values["national_code"] = code
    if values.get("nbs_code"):
        nbs = only_digits(values["nbs_code"])
        if len(nbs) != 9:
            raise AppError("O código NBS deve ter 9 dígitos.")
        values["nbs_code"] = nbs
    if values.get("validated"):
        if not values.get("validated_by"):
            raise AppError("Informe quem validou o código (contador responsável).")
        if obj is None or not obj.validated:
            values["validated_at"] = utcnow()
    else:
        values["validated_at"] = None


make_crud(router, path="/tax-service-codes", model=TaxServiceCode, schema_in=TaxCodeIn, schema_out=TaxCodeOut,
          read_perms=("services.read", "fiscal.read"), write_perms=("fiscal.settings",), entity="codigo_servico_fiscal",
          order_by=TaxServiceCode.national_code, validate=_validate_tax_code)


# ---------------------------------------------------------------- Serviços
class ServiceIn(StrippedModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    category_id: uuid.UUID | None = None
    duration_minutes: int = Field(ge=5, le=600)
    buffer_minutes: int = Field(default=0, ge=0, le=120)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    tax_service_code_id: uuid.UUID | None = None
    nfse_description: str | None = Field(default=None, max_length=1000)
    professional_ids: list[uuid.UUID] = Field(default_factory=list)
    is_active: bool = True


class ServiceOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    category_id: uuid.UUID | None
    category_name: str | None = None
    duration_minutes: int
    buffer_minutes: int
    price: Money
    tax_service_code_id: uuid.UUID | None
    tax_code_label: str | None = None
    tax_code_validated: bool | None = None
    nfse_description: str | None
    professional_ids: list[uuid.UUID] = []
    is_active: bool


def _service_out(s: Service) -> ServiceOut:
    out = ServiceOut.model_validate(s)
    out.category_name = s.category.name if s.category else None
    if s.tax_service_code:
        out.tax_code_label = f"{s.tax_service_code.national_code} — {s.tax_service_code.description}"
        out.tax_code_validated = s.tax_service_code.validated
    out.professional_ids = [p.id for p in s.professionals]
    return out


@router.get("/services", response_model=list[ServiceOut])
def list_services(active: bool | None = None, db: Session = Depends(get_db),
                  user: User = Depends(require_any("services.read", "agenda.read", "packages.read", "fiscal.read"))):
    stmt = select(Service).order_by(Service.name)
    if active is not None:
        stmt = stmt.where(Service.is_active == active)
    return [_service_out(s) for s in db.scalars(stmt).all()]


@router.get("/services/suggestions")
def service_suggestions(user: User = Depends(require("services.read"))):
    return SUGGESTED_MODALITIES


def _apply_service(db: Session, s: Service, data: ServiceIn) -> None:
    values = data.model_dump(exclude={"professional_ids"})
    for k, v in values.items():
        setattr(s, k, v)
    profs = []
    for pid in data.professional_ids:
        p = db.get(Professional, pid)
        if p is None:
            raise NotFound("Profissional")
        profs.append(p)
    s.professionals = profs


@router.post("/services", response_model=ServiceOut, status_code=201)
def create_service(data: ServiceIn, db: Session = Depends(get_db), user: User = Depends(require("services.write"))):
    s = Service()
    _apply_service(db, s, data)
    db.add(s)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Já existe um serviço com este nome.") from exc
    audit(db, "servico_criado", user=user, entity="service", entity_id=s.id, details=data.model_dump(mode="json"))
    db.commit()
    db.refresh(s)
    return _service_out(s)


@router.put("/services/{service_id}", response_model=ServiceOut)
def update_service(service_id: uuid.UUID, data: ServiceIn, db: Session = Depends(get_db),
                   user: User = Depends(require("services.write"))):
    s = db.get(Service, service_id)
    if s is None:
        raise NotFound("Serviço")
    _apply_service(db, s, data)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Já existe um serviço com este nome.") from exc
    audit(db, "servico_alterado", user=user, entity="service", entity_id=s.id, details=data.model_dump(mode="json"))
    db.commit()
    db.refresh(s)
    return _service_out(s)


@router.delete("/services/{service_id}")
def delete_service(service_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("services.write"))):
    s = db.get(Service, service_id)
    if s is None:
        raise NotFound("Serviço")
    try:
        db.delete(s)
        db.flush()
        msg = "Serviço excluído."
    except IntegrityError:
        db.rollback()
        s = db.get(Service, service_id)
        s.is_active = False
        msg = "Serviço já utilizado: foi inativado para preservar o histórico."
    audit(db, "servico_excluido", user=user, entity="service", entity_id=service_id)
    db.commit()
    return {"message": msg}


# ---------------------------------------------------------------- Planos de pacote
class PlanIn(StrippedModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    service_id: uuid.UUID
    sessions_count: int = Field(ge=1, le=200)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    validity_days: int | None = Field(default=None, ge=1, le=1825)
    no_show_consumes: bool = True
    late_cancel_consumes: bool = False
    late_cancel_hours: int = Field(default=24, ge=0, le=168)
    is_active: bool = True


class PlanOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    service_id: uuid.UUID
    sessions_count: int
    price: Money
    validity_days: int | None
    no_show_consumes: bool
    late_cancel_consumes: bool
    late_cancel_hours: int
    is_active: bool


def _validate_plan(db: Session, values: dict, obj) -> None:
    if db.get(Service, values["service_id"]) is None:
        raise NotFound("Serviço")


make_crud(router, path="/package-plans", model=PackagePlan, schema_in=PlanIn, schema_out=PlanOut,
          read_perms=("services.read", "packages.read"), write_perms=("services.write",), entity="plano_pacote",
          order_by=PackagePlan.name, validate=_validate_plan)
