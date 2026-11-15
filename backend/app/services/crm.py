"""Funil de relacionamento: estágio atualizado automaticamente pelos eventos reais
(agendamentos, atendimentos concluídos, pacotes) e manualmente pela equipe."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.settings_store import get_setting
from app.core.utils import utcnow
from app.models.crm import CRM_STAGES, CrmInteraction, CrmLead
from app.models.customer import Customer
from app.models.package import Package
from app.models.schedule import Appointment

STAGE_ORDER = {s: i for i, s in enumerate(CRM_STAGES)}


def ensure_lead(db: Session, customer: Customer, *, source: str | None = None, user_id: uuid.UUID | None = None) -> CrmLead:
    lead = db.scalar(select(CrmLead).where(CrmLead.customer_id == customer.id))
    if lead:
        return lead
    phone = customer.whatsapp or customer.phone
    if phone:
        lead = db.scalar(
            select(CrmLead).where(CrmLead.customer_id.is_(None), CrmLead.phone == phone).order_by(CrmLead.created_at).limit(1)
        )
        if lead:
            lead.customer_id = customer.id
            lead.name = customer.full_name
            return lead
    lead = CrmLead(
        customer_id=customer.id, name=customer.full_name, phone=phone, email=customer.email,
        source=source or customer.source, stage="novo_contato", owner_id=user_id,
    )
    db.add(lead)
    db.flush()
    return lead


def natural_stage(db: Session, customer_id: uuid.UUID) -> str | None:
    if db.scalar(select(func.count()).select_from(Package).where(Package.customer_id == customer_id, Package.status == "ativo")):
        return "pacote_contratado"
    visits = db.scalar(
        select(func.count()).select_from(Appointment).where(
            Appointment.customer_id == customer_id, Appointment.status == "concluido")
    ) or 0
    if visits >= int(get_setting(db, "crm.recurring_min_visits") or 2):
        return "cliente_recorrente"
    if visits >= 1:
        return "primeiro_atendimento"
    has_eval = db.scalar(
        select(func.count()).select_from(Appointment).where(
            Appointment.customer_id == customer_id, Appointment.is_evaluation.is_(True),
            Appointment.status.in_(("agendado", "confirmado")))
    )
    if has_eval:
        return "avaliacao_agendada"
    return None


def refresh_stage(db: Session, customer: Customer, *, user_id: uuid.UUID | None = None) -> CrmLead:
    lead = ensure_lead(db, customer, user_id=user_id)
    target = natural_stage(db, customer.id)
    if target is None:
        return lead
    if lead.stage == "cliente_inativo" or STAGE_ORDER[target] > STAGE_ORDER.get(lead.stage, 0):
        old = lead.stage
        lead.stage = target
        lead.stage_changed_at = utcnow()
        db.add(CrmInteraction(lead_id=lead.id, customer_id=customer.id, kind="sistema",
                              subject="Estágio atualizado", summary=f"{old} → {target}", user_id=user_id))
    return lead


def mark_inactive_customers(db: Session) -> int:
    """Rotina diária: move ao estágio 'cliente_inativo' quem não retorna há N dias."""
    days = int(get_setting(db, "crm.inactive_after_days") or 120)
    limit = utcnow() - timedelta(days=days)
    last_visit = (
        select(Appointment.customer_id, func.max(Appointment.start_at).label("last"))
        .where(Appointment.status == "concluido")
        .group_by(Appointment.customer_id)
        .subquery()
    )
    future = select(Appointment.customer_id).where(
        Appointment.status.in_(("agendado", "confirmado")), Appointment.start_at >= utcnow()
    )
    leads = db.scalars(
        select(CrmLead)
        .join(last_visit, last_visit.c.customer_id == CrmLead.customer_id)
        .where(last_visit.c.last < limit, CrmLead.stage != "cliente_inativo", CrmLead.customer_id.not_in(future))
    ).all()
    for lead in leads:
        old = lead.stage
        lead.stage = "cliente_inativo"
        lead.stage_changed_at = utcnow()
        db.add(CrmInteraction(lead_id=lead.id, customer_id=lead.customer_id, kind="sistema",
                              subject="Cliente inativo", summary=f"{old} → cliente_inativo (sem retorno há {days} dias)"))
    return len(leads)


def log_interaction(db: Session, customer_id: uuid.UUID | None, kind: str, subject: str, summary: str | None = None,
                    *, direction: str | None = None, user_id: uuid.UUID | None = None,
                    whatsapp_message_id: uuid.UUID | None = None) -> None:
    lead_id = None
    if customer_id:
        lead_id = db.scalar(select(CrmLead.id).where(CrmLead.customer_id == customer_id))
    db.add(CrmInteraction(lead_id=lead_id, customer_id=customer_id, kind=kind, direction=direction, subject=subject,
                          summary=summary, user_id=user_id, whatsapp_message_id=whatsapp_message_id))
