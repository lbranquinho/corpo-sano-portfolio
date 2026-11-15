from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import has_perm
from app.core.errors import AppError, Forbidden, NotFound
from app.core.settings_store import get_setting
from app.core.utils import local_today, normalize_text, only_digits, phone_variants, utcnow
from app.models.auth import User
from app.models.customer import Customer, CustomerConsent
from app.models.schedule import Appointment

CONSENT_TYPES = {
    "tratamento_dados": "Tratamento de dados pessoais",
    "dados_saude": "Tratamento de dados de saúde (anamnese)",
    "whatsapp_transacional": "WhatsApp: confirmações e lembretes",
    "whatsapp_marketing": "WhatsApp: campanhas, aniversário e retorno",
    "email_marketing": "E-mail: comunicações promocionais",
}


def scope_condition(user: User):
    """Massoterapeutas sem 'customers.read_all' veem apenas clientes que atendem/atenderam."""
    if has_perm(user, "customers.read_all"):
        return None
    if not user.professional_id:
        return Customer.id.is_(None)  # nenhum cliente
    return exists().where(
        and_(Appointment.customer_id == Customer.id, Appointment.professional_id == user.professional_id)
    )


def get_customer_for(db: Session, user: User, customer_id: uuid.UUID) -> Customer:
    c = db.get(Customer, customer_id)
    if c is None:
        raise NotFound("Cliente")
    cond = scope_condition(user)
    if cond is not None and not db.scalar(select(Customer.id).where(Customer.id == customer_id, cond)):
        raise Forbidden("Cliente não autorizado para o seu perfil.")
    return c


def last_visit_subq():
    return (
        select(func.max(Appointment.start_at))
        .where(Appointment.customer_id == Customer.id, Appointment.status == "concluido")
        .correlate(Customer)
        .scalar_subquery()
    )


def visits_subq():
    return (
        select(func.count(Appointment.id))
        .where(Appointment.customer_id == Customer.id, Appointment.status == "concluido")
        .correlate(Customer)
        .scalar_subquery()
    )


def next_appointment_subq():
    return (
        select(func.min(Appointment.start_at))
        .where(
            Appointment.customer_id == Customer.id,
            Appointment.status.in_(("agendado", "confirmado")),
            Appointment.start_at >= utcnow(),
        )
        .correlate(Customer)
        .scalar_subquery()
    )


def search_condition(q: str):
    q = q.strip()
    digits = only_digits(q)
    conds = [Customer.name_search.like(f"%{normalize_text(q)}%")]
    if len(digits) >= 3:
        conds += [Customer.cpf.like(f"{digits}%"), Customer.phone.like(f"%{digits}%"), Customer.whatsapp.like(f"%{digits}%")]
    return or_(*conds)


def filter_condition(db: Session, segment: str):
    inactive_days = int(get_setting(db, "crm.inactive_after_days") or 120)
    min_visits = int(get_setting(db, "crm.recurring_min_visits") or 2)
    now = utcnow()
    last = last_visit_subq()
    nxt = next_appointment_subq()
    if segment == "novos":
        return Customer.created_at >= now - timedelta(days=30)
    if segment == "ativos":
        return and_(Customer.status == "ativo", or_(last >= now - timedelta(days=inactive_days), nxt.is_not(None),
                                                    Customer.created_at >= now - timedelta(days=inactive_days)))
    if segment == "inativos":
        return or_(Customer.status == "inativo", and_(
            Customer.status == "ativo", nxt.is_(None), Customer.created_at < now - timedelta(days=inactive_days),
            or_(last.is_(None), last < now - timedelta(days=inactive_days))))
    if segment == "recorrentes":
        return visits_subq() >= min_visits
    raise AppError("Filtro inválido.")


def find_by_phone(db: Session, phone: str) -> Customer | None:
    variants = phone_variants(phone)
    return db.scalar(
        select(Customer)
        .where(or_(Customer.whatsapp.in_(variants), Customer.phone.in_(variants)), Customer.status != "anonimizado")
        .order_by(Customer.created_at)
        .limit(1)
    )


def current_consents(db: Session, customer_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    rows = db.scalars(
        select(CustomerConsent).where(CustomerConsent.customer_id == customer_id).order_by(CustomerConsent.created_at)
    ).all()
    out: dict[str, dict[str, Any]] = {
        k: {"type": k, "label": v, "granted": False, "updated_at": None, "source": None} for k, v in CONSENT_TYPES.items()
    }
    for r in rows:
        out.setdefault(r.consent_type, {"type": r.consent_type, "label": r.consent_type})
        out[r.consent_type].update(granted=r.granted, updated_at=r.created_at, source=r.source)
    return out


def has_consent(db: Session, customer_id: uuid.UUID, consent_type: str) -> bool:
    row = db.scalar(
        select(CustomerConsent)
        .where(CustomerConsent.customer_id == customer_id, CustomerConsent.consent_type == consent_type)
        .order_by(CustomerConsent.created_at.desc())
        .limit(1)
    )
    return bool(row and row.granted)


def record_consent(
    db: Session, customer_id: uuid.UUID, consent_type: str, granted: bool, *, source: str = "sistema",
    notes: str | None = None, user_id: uuid.UUID | None = None, ip: str | None = None,
) -> CustomerConsent:
    if consent_type not in CONSENT_TYPES:
        raise AppError("Tipo de consentimento inválido.")
    c = CustomerConsent(customer_id=customer_id, consent_type=consent_type, granted=granted, source=source,
                        notes=notes, recorded_by=user_id, ip=ip)
    db.add(c)
    db.flush()
    return c


def birthdays_between(db: Session, start_offset: int = 0, days: int = 7) -> list[Customer]:
    today = local_today()
    targets = {(today + timedelta(days=i)).strftime("%m-%d") for i in range(start_offset, start_offset + days)}
    rows = db.scalars(select(Customer).where(Customer.birth_date.is_not(None), Customer.status == "ativo")).all()
    return [c for c in rows if c.birth_date.strftime("%m-%d") in targets]
