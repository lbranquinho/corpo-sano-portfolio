from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import client_ip, has_perm, require
from app.core.errors import AppError, Conflict
from app.core.utils import normalize_text, utcnow
from app.models.auth import User
from app.models.clinical import CustomerHealthRecord, Treatment, TreatmentRecord
from app.models.crm import CrmInteraction, CrmLead, CrmTask
from app.models.customer import Customer
from app.models.finance import AccountsReceivable, FinancialTransaction
from app.models.fiscal import FiscalInvoice
from app.models.package import Package
from app.models.schedule import Appointment
from app.models.system import StoredFile
from app.models.whatsapp import WhatsappMessage
from app.schemas.common import ORM, CepStr, CpfStr, IbgeStr, Money, Page, PhoneStr, StrippedModel, UfStr
from app.services import crm as crm_service
from app.services.customers import (
    CONSENT_TYPES,
    current_consents,
    filter_condition,
    get_customer_for,
    last_visit_subq,
    next_appointment_subq,
    record_consent,
    scope_condition,
    search_condition,
    visits_subq,
)

router = APIRouter(prefix="/customers", tags=["Clientes"])


class CustomerIn(StrippedModel):
    full_name: str = Field(min_length=3, max_length=150)
    cpf: CpfStr = None
    birth_date: date | None = None
    phone: PhoneStr = None
    whatsapp: PhoneStr = None
    email: EmailStr | None = None
    zip_code: CepStr = None
    street: str | None = Field(default=None, max_length=200)
    number: str | None = Field(default=None, max_length=20)
    complement: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    state: UfStr = None
    ibge_code: IbgeStr = None
    source: str | None = Field(default=None, max_length=60)
    notes: str | None = None
    preferences: str | None = None
    status: str = Field(default="ativo", pattern=r"^(ativo|inativo)$")


class CustomerCreate(CustomerIn):
    consents: dict[str, bool] = Field(default_factory=dict)


class CustomerOut(ORM):
    id: uuid.UUID
    full_name: str
    cpf: str | None
    birth_date: date | None
    phone: str | None
    whatsapp: str | None
    email: str | None
    zip_code: str | None
    street: str | None
    number: str | None
    complement: str | None
    district: str | None
    city: str | None
    state: str | None
    ibge_code: str | None
    source: str | None
    notes: str | None
    preferences: str | None
    status: str
    created_at: datetime


class CustomerListItem(ORM):
    id: uuid.UUID
    full_name: str
    cpf: str | None
    phone: str | None
    whatsapp: str | None
    email: str | None
    birth_date: date | None
    status: str
    created_at: datetime
    last_visit_at: datetime | None = None
    next_appointment_at: datetime | None = None
    visits: int = 0
    crm_stage: str | None = None


class ConsentIn(BaseModel):
    consent_type: str
    granted: bool
    source: str = Field(default="presencial", max_length=40)
    notes: str | None = Field(default=None, max_length=300)


class AnonymizeIn(BaseModel):
    confirmation: str
    reason: str = Field(min_length=5, max_length=300)


def _dup_check(db: Session, data: CustomerIn, exclude: uuid.UUID | None = None) -> None:
    if data.cpf:
        stmt = select(Customer.id).where(Customer.cpf == data.cpf)
        if exclude:
            stmt = stmt.where(Customer.id != exclude)
        if db.scalar(stmt):
            raise Conflict("Já existe um cliente com este CPF.")


@router.get("", response_model=Page[CustomerListItem])
def list_customers(
    q: str | None = None,
    segment: str | None = Query(None, pattern=r"^(novos|ativos|inativos|recorrentes)$"),
    stage: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require("customers.read")),
):
    last, nxt, visits = last_visit_subq().label("last"), next_appointment_subq().label("nxt"), visits_subq().label("visits")
    stmt = select(Customer, last, nxt, visits, CrmLead.stage).outerjoin(CrmLead, CrmLead.customer_id == Customer.id)
    stmt = stmt.where(Customer.status != "anonimizado")
    cond = scope_condition(user)
    if cond is not None:
        stmt = stmt.where(cond)
    if q:
        stmt = stmt.where(search_condition(q))
    if segment:
        stmt = stmt.where(filter_condition(db, segment))
    if stage:
        stmt = stmt.where(CrmLead.stage == stage)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(Customer.name_search).offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for c, lv, na, vc, st in rows:
        item = CustomerListItem.model_validate(c)
        item.last_visit_at, item.next_appointment_at, item.visits, item.crm_stage = lv, na, vc or 0, st
        items.append(item)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=CustomerOut, status_code=201)
def create_customer(data: CustomerCreate, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("customers.write"))):
    _dup_check(db, data)
    values = data.model_dump(exclude={"consents"})
    c = Customer(**values, name_search=normalize_text(data.full_name), created_by=user.id)
    if not c.whatsapp and c.phone:
        c.whatsapp = c.phone
    db.add(c)
    db.flush()
    for ctype, granted in data.consents.items():
        if ctype in CONSENT_TYPES:
            record_consent(db, c.id, ctype, granted, source="cadastro", user_id=user.id, ip=client_ip(request))
    crm_service.ensure_lead(db, c, user_id=user.id)
    audit(db, "cliente_criado", user=user, entity="customer", entity_id=c.id)
    db.commit()
    db.refresh(c)
    return c


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("customers.read"))):
    return get_customer_for(db, user, customer_id)


@router.put("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: uuid.UUID, data: CustomerIn, db: Session = Depends(get_db),
                    user: User = Depends(require("customers.write"))):
    c = get_customer_for(db, user, customer_id)
    if c.status == "anonimizado":
        raise AppError("Cliente anonimizado não pode ser alterado.")
    _dup_check(db, data, exclude=c.id)
    before = {k: getattr(c, k) for k in data.model_fields}
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    c.name_search = normalize_text(c.full_name)
    changed = [k for k in data.model_fields if before[k] != getattr(c, k)]
    lead = db.scalar(select(CrmLead).where(CrmLead.customer_id == c.id))
    if lead:
        lead.name, lead.phone, lead.email = c.full_name, c.whatsapp or c.phone, c.email
    audit(db, "cliente_alterado", user=user, entity="customer", entity_id=c.id, details={"campos": changed})
    db.commit()
    db.refresh(c)
    return c


@router.get("/{customer_id}/profile")
def customer_profile(customer_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("customers.read"))):
    c = get_customer_for(db, user, customer_id)
    appts = db.scalars(select(Appointment).where(Appointment.customer_id == c.id).order_by(Appointment.start_at.desc())).all()
    if not has_perm(user, "agenda.read_all") and user.professional_id:
        appts = [a for a in appts if a.professional_id == user.professional_id]
    packages = db.scalars(select(Package).where(Package.customer_id == c.id).order_by(Package.purchased_at.desc())).all()
    finance_visible = has_perm(user, "finance.read") or has_perm(user, "finance.payments")
    receivables = []
    payments_total = Decimal("0")
    open_balance = Decimal("0")
    if finance_visible:
        rec_rows = db.scalars(select(AccountsReceivable).where(AccountsReceivable.customer_id == c.id)
                              .order_by(AccountsReceivable.due_date.desc())).all()
        for r in rec_rows:
            receivables.append({"id": str(r.id), "description": r.description, "origin": r.origin,
                                "due_date": r.due_date, "amount": float(r.net_amount), "paid": float(r.amount_paid),
                                "balance": float(r.balance), "status": r.status})
            if r.status in ("aberto", "parcial"):
                open_balance += r.balance
        payments_total = db.scalar(
            select(func.coalesce(func.sum(FinancialTransaction.amount), 0)).join(
                AccountsReceivable, AccountsReceivable.id == FinancialTransaction.receivable_id
            ).where(AccountsReceivable.customer_id == c.id, FinancialTransaction.kind == "entrada",
                    FinancialTransaction.is_reversal.is_(False), FinancialTransaction.reversed.is_(False))
        ) or Decimal("0")
    invoices = []
    if has_perm(user, "fiscal.read") or has_perm(user, "finance.read"):
        for inv in db.scalars(select(FiscalInvoice).where(FiscalInvoice.customer_id == c.id)
                              .order_by(FiscalInvoice.created_at.desc())).all():
            invoices.append({"id": str(inv.id), "number": inv.nfse_number, "status": inv.status,
                             "competence_date": inv.competence_date, "amount": float(inv.net_amount),
                             "environment": inv.environment})
    lead = db.scalar(select(CrmLead).where(CrmLead.customer_id == c.id))
    interactions, tasks = [], []
    if has_perm(user, "crm.read"):
        interactions = [
            {"id": str(i.id), "kind": i.kind, "direction": i.direction, "subject": i.subject, "summary": i.summary,
             "occurred_at": i.occurred_at}
            for i in db.scalars(select(CrmInteraction).where(CrmInteraction.customer_id == c.id)
                                .order_by(CrmInteraction.occurred_at.desc()).limit(100)).all()
        ]
        tasks = [
            {"id": str(t.id), "title": t.title, "kind": t.kind, "due_at": t.due_at, "status": t.status}
            for t in db.scalars(select(CrmTask).where(CrmTask.customer_id == c.id).order_by(CrmTask.due_at.desc())).all()
        ]
    completed = [a for a in appts if a.status == "concluido"]
    services_count: dict[str, int] = {}
    for a in completed:
        services_count[a.service.name] = services_count.get(a.service.name, 0) + 1
    future = [a for a in appts if a.status in ("agendado", "confirmado") and a.start_at >= utcnow()]
    return {
        "customer": CustomerOut.model_validate(c).model_dump(),
        "crm": {"lead_id": str(lead.id) if lead else None, "stage": lead.stage if lead else None},
        "stats": {
            "visits": len(completed),
            "last_visit_at": completed[0].start_at if completed else None,
            "next_appointment_at": min((a.start_at for a in future), default=None),
            "cancellations": sum(1 for a in appts if a.status == "cancelado"),
            "no_shows": sum(1 for a in appts if a.status == "falta"),
            "payments_total": float(payments_total) if finance_visible else None,
            "open_balance": float(open_balance) if finance_visible else None,
            "sessions_available": sum(p.sessions_remaining for p in packages if p.status == "ativo"),
        },
        "services": [{"name": k, "count": v} for k, v in sorted(services_count.items(), key=lambda kv: -kv[1])],
        "appointments": [
            {"id": str(a.id), "start_at": a.start_at, "end_at": a.end_at, "service": a.service.name,
             "professional": a.professional.name, "status": a.status, "price": float(a.net_price),
             "package_id": str(a.package_id) if a.package_id else None}
            for a in appts
        ],
        "packages": [
            {"id": str(p.id), "name": p.name, "service": p.service.name, "sessions_total": p.sessions_total,
             "sessions_used": p.sessions_used, "sessions_remaining": p.sessions_remaining, "status": p.status,
             "purchased_at": p.purchased_at, "expires_at": p.expires_at,
             "price": float(p.price) if finance_visible else None}
            for p in packages
        ],
        "receivables": receivables,
        "invoices": invoices,
        "interactions": interactions,
        "tasks": tasks,
        "consents": list(current_consents(db, c.id).values()),
    }


@router.get("/{customer_id}/consents")
def get_consents(customer_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("customers.read"))):
    get_customer_for(db, user, customer_id)
    return list(current_consents(db, customer_id).values())


@router.post("/{customer_id}/consents")
def set_consent(customer_id: uuid.UUID, data: ConsentIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require("customers.write"))):
    get_customer_for(db, user, customer_id)
    record_consent(db, customer_id, data.consent_type, data.granted, source=data.source, notes=data.notes,
                   user_id=user.id, ip=client_ip(request))
    audit(db, "consentimento_registrado", user=user, entity="customer", entity_id=customer_id,
          details={"tipo": data.consent_type, "concedido": data.granted})
    db.commit()
    return list(current_consents(db, customer_id).values())


@router.get("/{customer_id}/export")
def export_customer_data(customer_id: uuid.UUID, db: Session = Depends(get_db),
                         user: User = Depends(require("customers.lgpd"))):
    """Portabilidade/acesso (LGPD art. 18): todos os dados pessoais do titular em JSON."""
    c = get_customer_for(db, user, customer_id)
    data: dict = {"gerado_em": utcnow().isoformat(), "titular": CustomerOut.model_validate(c).model_dump(mode="json")}
    data["consentimentos"] = [
        {"tipo": k, **{kk: (vv.isoformat() if isinstance(vv, datetime) else vv) for kk, vv in v.items()}}
        for k, v in current_consents(db, c.id).items()
    ]
    data["agendamentos"] = [
        {"data": a.start_at.isoformat(), "servico": a.service.name, "profissional": a.professional.name, "status": a.status}
        for a in db.scalars(select(Appointment).where(Appointment.customer_id == c.id)).all()
    ]
    data["pacotes"] = [
        {"nome": p.name, "sessoes": p.sessions_total, "usadas": p.sessions_used, "valor": float(p.price), "status": p.status}
        for p in db.scalars(select(Package).where(Package.customer_id == c.id)).all()
    ]
    data["financeiro"] = [
        {"descricao": r.description, "vencimento": r.due_date.isoformat(), "valor": float(r.net_amount),
         "pago": float(r.amount_paid), "status": r.status}
        for r in db.scalars(select(AccountsReceivable).where(AccountsReceivable.customer_id == c.id)).all()
    ]
    data["notas_fiscais"] = [
        {"numero": i.nfse_number, "competencia": i.competence_date.isoformat(), "valor": float(i.net_amount), "status": i.status}
        for i in db.scalars(select(FiscalInvoice).where(FiscalInvoice.customer_id == c.id)).all()
    ]
    data["mensagens_whatsapp"] = [
        {"data": m.created_at.isoformat(), "direcao": m.direction, "finalidade": m.purpose, "status": m.status}
        for m in db.scalars(select(WhatsappMessage).where(WhatsappMessage.customer_id == c.id)).all()
    ]
    included_health = has_perm(user, "clinical.read")
    if included_health:
        from app.core.crypto import decrypt_health

        data["anamneses"] = [
            {"data": h.created_at.isoformat(), "versao": h.version, **decrypt_health(h.data_enc)}
            for h in db.scalars(select(CustomerHealthRecord).where(CustomerHealthRecord.customer_id == c.id)).all()
        ]
    audit(db, "dados_titular_exportados", user=user, entity="customer", entity_id=c.id,
          details={"inclui_saude": included_health}, sensitive=True)
    db.commit()
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return Response(content=content, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="dados_titular_{c.id}.json"'})


@router.post("/{customer_id}/anonymize")
def anonymize_customer(customer_id: uuid.UUID, data: AnonymizeIn, db: Session = Depends(get_db),
                       user: User = Depends(require("customers.lgpd"))):
    """Anonimização (LGPD). Mantém registros fiscais/financeiros exigidos por lei (retenção legal)."""
    c = get_customer_for(db, user, customer_id)
    if data.confirmation.strip().upper() != "ANONIMIZAR":
        raise AppError('Digite "ANONIMIZAR" para confirmar.')
    if c.status == "anonimizado":
        raise AppError("Cliente já anonimizado.")
    open_rec = db.scalar(select(func.count()).select_from(AccountsReceivable).where(
        AccountsReceivable.customer_id == c.id, AccountsReceivable.status.in_(("aberto", "parcial"))))
    if open_rec:
        raise AppError("Há valores em aberto para este cliente. Regularize antes de anonimizar.")
    future = db.scalar(select(func.count()).select_from(Appointment).where(
        Appointment.customer_id == c.id, Appointment.status.in_(("agendado", "confirmado"))))
    if future:
        raise AppError("Há agendamentos futuros. Cancele-os antes de anonimizar.")
    tag = c.id.hex[:8]
    for field in ("cpf", "birth_date", "phone", "whatsapp", "email", "zip_code", "street", "number", "complement",
                  "district", "notes", "preferences", "ibge_code"):
        setattr(c, field, None)
    c.full_name = f"Cliente anonimizado {tag}"
    c.name_search = normalize_text(c.full_name)
    c.status = "anonimizado"
    c.anonymized_at = utcnow()
    # dados de saúde: removidos
    for h in db.scalars(select(CustomerHealthRecord).where(CustomerHealthRecord.customer_id == c.id)).all():
        db.delete(h)
    for t in db.scalars(select(Treatment).where(Treatment.customer_id == c.id)).all():
        for r in db.scalars(select(TreatmentRecord).where(TreatmentRecord.treatment_id == t.id)).all():
            db.delete(r)
    from app.core.storage import delete_file

    for f in db.scalars(select(StoredFile).where(StoredFile.customer_id == c.id, StoredFile.sensitive.is_(True))).all():
        delete_file(db, f)
    for m in db.scalars(select(WhatsappMessage).where(WhatsappMessage.customer_id == c.id)).all():
        m.content, m.variables, m.phone = None, None, "anonimizado"
    lead = db.scalar(select(CrmLead).where(CrmLead.customer_id == c.id))
    if lead:
        lead.name, lead.phone, lead.email, lead.notes = c.full_name, None, None, None
    for i in db.scalars(select(CrmInteraction).where(CrmInteraction.customer_id == c.id)).all():
        i.summary = None
    audit(db, "cliente_anonimizado", user=user, entity="customer", entity_id=c.id, details={"motivo": data.reason},
          sensitive=True)
    db.commit()
    return {"message": "Dados pessoais anonimizados. Registros fiscais e financeiros foram mantidos por obrigação legal."}
