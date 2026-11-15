from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import has_perm, require
from app.core.errors import AppError, NotFound
from app.core.utils import local_today, utcnow
from app.models.auth import User
from app.models.catalog import PackagePlan, Service
from app.models.customer import Customer
from app.models.finance import AccountsReceivable
from app.models.fiscal import FiscalInvoice
from app.models.package import Package, PackageSession
from app.models.schedule import Appointment
from app.schemas.common import ORM, Money
from app.services import crm as crm_service
from app.services import finance as fin
from app.services import packages as svc
from app.services.customers import get_customer_for

router = APIRouter(prefix="/packages", tags=["Pacotes"])


class PackageSellIn(BaseModel):
    customer_id: uuid.UUID
    plan_id: uuid.UUID | None = None
    service_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=120)
    sessions_total: int | None = Field(default=None, ge=1, le=200)
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    purchased_at: date | None = None
    expires_at: date | None = None
    payment_method_id: uuid.UUID | None = None
    installments: int = Field(default=1, ge=1, le=24)
    first_due_date: date | None = None
    no_show_consumes: bool | None = None
    late_cancel_consumes: bool | None = None
    late_cancel_hours: int | None = Field(default=None, ge=0, le=168)
    notes: str | None = Field(default=None, max_length=2000)
    receive_now: bool = False
    account_id: uuid.UUID | None = None


class PackageOut(ORM):
    id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str = ""
    plan_id: uuid.UUID | None
    service_id: uuid.UUID
    service_name: str = ""
    name: str
    sessions_total: int
    sessions_used: int
    sessions_remaining: int
    price: Money
    purchased_at: date
    expires_at: date | None
    payment_method_id: uuid.UUID | None
    status: str
    no_show_consumes: bool
    late_cancel_consumes: bool
    late_cancel_hours: int
    notes: str | None
    reserved: int = 0


class CancelIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


def _out(db: Session, p: Package) -> PackageOut:
    o = PackageOut.model_validate(p)
    o.customer_name, o.service_name = p.customer.full_name, p.service.name
    o.reserved = svc.reserved_sessions(db, p.id)
    return o


@router.get("", response_model=list[PackageOut])
def list_packages(status: str | None = None, customer_id: uuid.UUID | None = None, alert: str | None = Query(None, pattern=r"^(low_balance|expiring)$"),
                  db: Session = Depends(get_db), user: User = Depends(require("packages.read"))):
    if alert:
        return [_out(db, p) for p in svc.package_alerts(db)[alert]]
    stmt = select(Package)
    if status:
        stmt = stmt.where(Package.status == status)
    if customer_id:
        get_customer_for(db, user, customer_id)
        stmt = stmt.where(Package.customer_id == customer_id)
    return [_out(db, p) for p in db.scalars(stmt.order_by(Package.purchased_at.desc()).limit(500)).all()]


@router.get("/{package_id}")
def get_package(package_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("packages.read"))):
    p = db.get(Package, package_id)
    if p is None:
        raise NotFound("Pacote")
    get_customer_for(db, user, p.customer_id)
    sessions = db.scalars(select(PackageSession).where(PackageSession.package_id == p.id).order_by(PackageSession.consumed_at)).all()
    appts = {a.id: a for a in db.scalars(select(Appointment).where(Appointment.package_id == p.id)).all()}
    out: dict = {
        "package": _out(db, p).model_dump(mode="json"),
        "sessions": [{"id": str(s.id), "reason": s.reason, "consumed_at": s.consumed_at, "reverted_at": s.reverted_at,
                      "appointment_id": str(s.appointment_id) if s.appointment_id else None,
                      "appointment_start": appts[s.appointment_id].start_at if s.appointment_id in appts else None}
                     for s in sessions],
        "scheduled": [{"id": str(a.id), "start_at": a.start_at, "status": a.status} for a in appts.values()
                      if a.status in ("agendado", "confirmado")],
    }
    if has_perm(user, "finance.read") or has_perm(user, "finance.payments"):
        out["receivables"] = [
            {"id": str(r.id), "description": r.description, "due_date": r.due_date, "amount": float(r.net_amount),
             "paid": float(r.amount_paid), "status": r.status}
            for r in db.scalars(select(AccountsReceivable).where(AccountsReceivable.package_id == p.id)
                                .order_by(AccountsReceivable.installment_number)).all()
        ]
    return out


@router.post("", status_code=201)
def sell_package(data: PackageSellIn, db: Session = Depends(get_db), user: User = Depends(require("packages.write"))):
    customer = db.get(Customer, data.customer_id)
    if customer is None or customer.status == "anonimizado":
        raise NotFound("Cliente")
    plan = db.get(PackagePlan, data.plan_id) if data.plan_id else None
    if data.plan_id and (plan is None or not plan.is_active):
        raise AppError("Plano de pacote inexistente ou inativo.")
    service_id = plan.service_id if plan else data.service_id
    if service_id is None or db.get(Service, service_id) is None:
        raise AppError("Informe o serviço do pacote.")
    sessions = data.sessions_total or (plan.sessions_count if plan else None)
    price = data.price if data.price is not None else (plan.price if plan else None)
    if not sessions or price is None:
        raise AppError("Informe a quantidade de sessões e o valor.")
    purchased = data.purchased_at or local_today()
    expires = data.expires_at or svc.default_expiry(purchased, plan.validity_days if plan else None)
    if expires and expires < purchased:
        raise AppError("O vencimento não pode ser anterior à contratação.")
    if data.discount and data.discount >= price:
        raise AppError("Desconto inválido.")
    service = db.get(Service, service_id)
    p = Package(
        customer_id=customer.id, plan_id=plan.id if plan else None, service_id=service_id,
        name=data.name or (plan.name if plan else f"Pacote {sessions}x {service.name}"), sessions_total=sessions,
        sessions_used=0, price=price - data.discount, purchased_at=purchased, expires_at=expires,
        payment_method_id=data.payment_method_id, status="ativo",
        no_show_consumes=data.no_show_consumes if data.no_show_consumes is not None else (plan.no_show_consumes if plan else True),
        late_cancel_consumes=data.late_cancel_consumes if data.late_cancel_consumes is not None else (plan.late_cancel_consumes if plan else False),
        late_cancel_hours=data.late_cancel_hours if data.late_cancel_hours is not None else (plan.late_cancel_hours if plan else 24),
        notes=data.notes, created_by=user.id,
    )
    db.add(p)
    db.flush()
    receivables = []
    if price > 0:
        receivables = fin.create_receivables(
            db, customer_id=customer.id, description=f"Pacote: {p.name}", origin="pacote", total=price,
            discount=data.discount, competence_date=purchased, first_due=data.first_due_date or purchased,
            installments=data.installments, package_id=p.id, user_id=user.id,
        )
        if data.receive_now:
            if not has_perm(user, "finance.payments"):
                raise AppError("Sem permissão para registrar pagamentos.", status_code=403)
            if data.payment_method_id is None:
                raise AppError("Informe a forma de pagamento para registrar o recebimento.")
            first = receivables[0]
            fin.register_receipt(db, first, amount=first.balance, payment_date=local_today(),
                                 payment_method_id=data.payment_method_id, account_id=data.account_id, user_id=user.id)
    crm_service.refresh_stage(db, customer, user_id=user.id)
    audit(db, "pacote_vendido", user=user, entity="package", entity_id=p.id,
          details={"cliente": str(customer.id), "sessoes": sessions, "valor": str(price - data.discount)})
    db.commit()
    db.refresh(p)
    return {"message": "Pacote registrado.", "package": _out(db, p).model_dump(mode="json"),
            "receivables": [str(r.id) for r in receivables]}


@router.post("/{package_id}/cancel")
def cancel_package(package_id: uuid.UUID, data: CancelIn, db: Session = Depends(get_db),
                   user: User = Depends(require("packages.write"))):
    p = svc.lock_package(db, package_id)
    if p.status in ("cancelado",):
        raise AppError("Pacote já cancelado.")
    future = db.scalar(select(func.count()).select_from(Appointment).where(
        Appointment.package_id == p.id, Appointment.status.in_(("agendado", "confirmado"))))
    if future:
        raise AppError("Há agendamentos futuros usando este pacote. Cancele ou remarque-os antes.")
    active_inv = db.scalar(select(FiscalInvoice.id).where(FiscalInvoice.package_id == p.id,
                                                          FiscalInvoice.status == "autorizada").limit(1))
    for r in db.scalars(select(AccountsReceivable).where(AccountsReceivable.package_id == p.id)).all():
        if r.status == "aberto":
            r.status, r.cancelled_at, r.cancel_reason = "cancelado", utcnow(), f"Pacote cancelado: {data.reason}"
    p.status, p.cancelled_at = "cancelado", utcnow()
    p.notes = ((p.notes or "") + f"\nCancelado: {data.reason}").strip()
    audit(db, "pacote_cancelado", user=user, entity="package", entity_id=p.id, details={"motivo": data.reason})
    db.commit()
    msg = "Pacote cancelado. Parcelas em aberto foram canceladas; valores já pagos exigem estorno no Financeiro, se aplicável."
    if active_inv:
        msg += " Existe NFS-e autorizada para este pacote: avalie cancelamento/substituição no módulo fiscal."
    return {"message": msg}


@router.post("/sessions/{session_id}/revert")
def revert_session(session_id: uuid.UUID, data: CancelIn, db: Session = Depends(get_db),
                   user: User = Depends(require("packages.write"))):
    s = svc.revert(db, session_id, user.id)
    s.notes = data.reason
    audit(db, "baixa_sessao_revertida", user=user, entity="package_session", entity_id=session_id,
          details={"motivo": data.reason})
    db.commit()
    return {"message": "Baixa de sessão revertida."}
