from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import require
from app.core.errors import AppError, NotFound
from app.core.settings_store import get_setting
from app.core.utils import local_today, normalize_text, utcnow
from app.models.auth import User
from app.models.crm import CRM_STAGES, CrmCampaign, CrmInteraction, CrmLead, CrmTask
from app.models.customer import Customer
from app.models.schedule import Appointment
from app.models.whatsapp import WhatsappTemplate
from app.schemas.common import ORM, PhoneStr, StrippedModel
from app.services import whatsapp as wa
from app.services.customers import birthdays_between, has_consent

router = APIRouter(prefix="/crm", tags=["CRM"])

STAGE_LABELS = {
    "novo_contato": "Novo contato", "interessado": "Interessado", "avaliacao_agendada": "Avaliação agendada",
    "primeiro_atendimento": "Primeiro atendimento realizado", "cliente_recorrente": "Cliente recorrente",
    "pacote_contratado": "Pacote contratado", "cliente_inativo": "Cliente inativo",
}


class LeadIn(StrippedModel):
    name: str = Field(min_length=2, max_length=150)
    phone: PhoneStr = None
    email: EmailStr | None = None
    source: str | None = Field(default=None, max_length=60)
    stage: str = "novo_contato"
    interest_service_id: uuid.UUID | None = None
    notes: str | None = None
    next_contact_at: datetime | None = None


class LeadOut(ORM):
    id: uuid.UUID
    customer_id: uuid.UUID | None
    name: str
    phone: str | None
    email: str | None
    source: str | None
    stage: str
    interest_service_id: uuid.UUID | None
    notes: str | None
    next_contact_at: datetime | None
    stage_changed_at: datetime
    created_at: datetime


class StageIn(BaseModel):
    stage: str
    note: str | None = Field(default=None, max_length=500)


class InteractionIn(StrippedModel):
    customer_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    kind: str = Field(pattern=r"^(ligacao|mensagem|whatsapp|email|presencial|nota)$")
    direction: str | None = Field(default=None, pattern=r"^(entrada|saida)$")
    subject: str = Field(min_length=2, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    occurred_at: datetime | None = None


class TaskIn(StrippedModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = None
    kind: str = Field(default="follow_up", pattern=r"^(retorno|lembrete|follow_up|aniversario|outro)$")
    due_at: datetime
    customer_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    assigned_to: uuid.UUID | None = None


class TaskOut(ORM):
    id: uuid.UUID
    title: str
    description: str | None
    kind: str
    due_at: datetime
    status: str
    customer_id: uuid.UUID | None
    lead_id: uuid.UUID | None
    assigned_to: uuid.UUID | None
    completed_at: datetime | None
    customer_name: str | None = None


class CampaignIn(StrippedModel):
    name: str = Field(min_length=3, max_length=150)
    description: str | None = None
    template_id: uuid.UUID
    audience: dict = Field(default_factory=dict)


def _stage_ok(stage: str) -> None:
    if stage not in CRM_STAGES:
        raise AppError("Estágio inválido.")


@router.get("/stages")
def stages(user: User = Depends(require("crm.read"))):
    return [{"code": s, "label": STAGE_LABELS[s]} for s in CRM_STAGES]


@router.get("/leads", response_model=list[LeadOut])
def list_leads(stage: str | None = None, q: str | None = None, db: Session = Depends(get_db),
               user: User = Depends(require("crm.read"))):
    stmt = select(CrmLead)
    if stage:
        stmt = stmt.where(CrmLead.stage == stage)
    if q:
        stmt = stmt.where(or_(func.lower(CrmLead.name).like(f"%{q.lower()}%"), CrmLead.phone.like(f"%{q}%")))
    return db.scalars(stmt.order_by(CrmLead.stage_changed_at.desc()).limit(1000)).all()


@router.post("/leads", response_model=LeadOut, status_code=201)
def create_lead(data: LeadIn, db: Session = Depends(get_db), user: User = Depends(require("crm.write"))):
    _stage_ok(data.stage)
    lead = CrmLead(**data.model_dump(), owner_id=user.id)
    db.add(lead)
    db.flush()
    db.add(CrmInteraction(lead_id=lead.id, kind="sistema", subject="Contato registrado", user_id=user.id))
    audit(db, "lead_criado", user=user, entity="crm_lead", entity_id=lead.id)
    db.commit()
    db.refresh(lead)
    return lead


@router.put("/leads/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: uuid.UUID, data: LeadIn, db: Session = Depends(get_db), user: User = Depends(require("crm.write"))):
    lead = db.get(CrmLead, lead_id)
    if lead is None:
        raise NotFound("Contato")
    _stage_ok(data.stage)
    if data.stage != lead.stage:
        lead.stage_changed_at = utcnow()
        db.add(CrmInteraction(lead_id=lead.id, customer_id=lead.customer_id, kind="sistema", subject="Estágio alterado",
                              summary=f"{lead.stage} → {data.stage}", user_id=user.id))
    for k, v in data.model_dump().items():
        if lead.customer_id and k in ("name", "phone", "email"):
            continue  # dados do cliente são editados no cadastro
        setattr(lead, k, v)
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/leads/{lead_id}/stage", response_model=LeadOut)
def move_stage(lead_id: uuid.UUID, data: StageIn, db: Session = Depends(get_db), user: User = Depends(require("crm.write"))):
    lead = db.get(CrmLead, lead_id)
    if lead is None:
        raise NotFound("Contato")
    _stage_ok(data.stage)
    if data.stage != lead.stage:
        db.add(CrmInteraction(lead_id=lead.id, customer_id=lead.customer_id, kind="sistema", subject="Estágio alterado",
                              summary=f"{STAGE_LABELS[lead.stage]} → {STAGE_LABELS[data.stage]}" + (f" — {data.note}" if data.note else ""),
                              user_id=user.id))
        lead.stage, lead.stage_changed_at = data.stage, utcnow()
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/leads/{lead_id}/convert")
def convert_lead(lead_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("crm.write", "customers.write"))):
    """Cria o cadastro de cliente a partir do contato (dados mínimos)."""
    lead = db.get(CrmLead, lead_id)
    if lead is None:
        raise NotFound("Contato")
    if lead.customer_id:
        raise AppError("Este contato já possui cadastro de cliente.")
    c = Customer(full_name=lead.name, name_search=normalize_text(lead.name), phone=lead.phone, whatsapp=lead.phone,
                 email=lead.email, source=lead.source, created_by=user.id)
    db.add(c)
    db.flush()
    lead.customer_id = c.id
    audit(db, "lead_convertido", user=user, entity="crm_lead", entity_id=lead.id, details={"cliente": str(c.id)})
    db.commit()
    return {"message": "Cliente cadastrado a partir do contato. Complete os dados e consentimentos no cadastro.",
            "customer_id": str(c.id)}


@router.get("/interactions")
def list_interactions(customer_id: uuid.UUID | None = None, lead_id: uuid.UUID | None = None,
                      kind: str | None = None, limit: int = Query(100, le=500), db: Session = Depends(get_db),
                      user: User = Depends(require("crm.read"))):
    stmt = select(CrmInteraction, Customer.full_name).outerjoin(Customer, Customer.id == CrmInteraction.customer_id)
    if customer_id:
        stmt = stmt.where(CrmInteraction.customer_id == customer_id)
    if lead_id:
        stmt = stmt.where(CrmInteraction.lead_id == lead_id)
    if kind:
        stmt = stmt.where(CrmInteraction.kind == kind)
    rows = db.execute(stmt.order_by(CrmInteraction.occurred_at.desc()).limit(limit)).all()
    return [{"id": str(i.id), "customer_id": str(i.customer_id) if i.customer_id else None, "customer_name": name,
             "lead_id": str(i.lead_id) if i.lead_id else None, "kind": i.kind, "direction": i.direction,
             "subject": i.subject, "summary": i.summary, "occurred_at": i.occurred_at} for i, name in rows]


@router.post("/interactions", status_code=201)
def create_interaction(data: InteractionIn, db: Session = Depends(get_db), user: User = Depends(require("crm.write"))):
    if not data.customer_id and not data.lead_id:
        raise AppError("Informe o cliente ou o contato.")
    lead_id = data.lead_id
    if data.customer_id and not lead_id:
        lead_id = db.scalar(select(CrmLead.id).where(CrmLead.customer_id == data.customer_id))
    i = CrmInteraction(customer_id=data.customer_id, lead_id=lead_id, kind=data.kind, direction=data.direction,
                       subject=data.subject, summary=data.summary, occurred_at=data.occurred_at or utcnow(),
                       user_id=user.id)
    db.add(i)
    db.commit()
    return {"message": "Contato registrado.", "id": str(i.id)}


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(status: str | None = "pendente", customer_id: uuid.UUID | None = None, mine: bool = False,
               db: Session = Depends(get_db), user: User = Depends(require("crm.read"))):
    stmt = select(CrmTask, Customer.full_name).outerjoin(Customer, Customer.id == CrmTask.customer_id)
    if status:
        stmt = stmt.where(CrmTask.status == status)
    if customer_id:
        stmt = stmt.where(CrmTask.customer_id == customer_id)
    if mine:
        stmt = stmt.where(CrmTask.assigned_to == user.id)
    out = []
    for t, name in db.execute(stmt.order_by(CrmTask.due_at).limit(500)).all():
        o = TaskOut.model_validate(t)
        o.customer_name = name
        out.append(o)
    return out


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(data: TaskIn, db: Session = Depends(get_db), user: User = Depends(require("crm.write"))):
    t = CrmTask(**data.model_dump(), created_by=user.id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.put("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: uuid.UUID, data: TaskIn, db: Session = Depends(get_db), user: User = Depends(require("crm.write"))):
    t = db.get(CrmTask, task_id)
    if t is None:
        raise NotFound("Tarefa")
    for k, v in data.model_dump().items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return t


@router.post("/tasks/{task_id}/{action}", response_model=TaskOut)
def task_action(task_id: uuid.UUID, action: str, db: Session = Depends(get_db), user: User = Depends(require("crm.write"))):
    t = db.get(CrmTask, task_id)
    if t is None:
        raise NotFound("Tarefa")
    if action == "concluir":
        t.status, t.completed_at = "concluida", utcnow()
    elif action == "cancelar":
        t.status = "cancelada"
    elif action == "reabrir":
        t.status, t.completed_at = "pendente", None
    else:
        raise AppError("Ação inválida.")
    db.commit()
    db.refresh(t)
    return t


@router.get("/alerts")
def alerts(db: Session = Depends(get_db), user: User = Depends(require("crm.read"))):
    """Retornos (30/60/90 dias configuráveis), aniversariantes, clientes sem agendamento futuro e inativos."""
    thresholds = sorted(int(x) for x in (get_setting(db, "crm.return_alert_days") or [30, 60, 90]))
    now = utcnow()
    last_visit = (select(Appointment.customer_id, func.max(Appointment.start_at).label("last"))
                  .where(Appointment.status == "concluido").group_by(Appointment.customer_id).subquery())
    future_ids = set(db.scalars(select(Appointment.customer_id).where(
        Appointment.status.in_(("agendado", "confirmado")), Appointment.start_at >= now)).all())
    rows = db.execute(select(Customer, last_visit.c.last).join(last_visit, last_visit.c.customer_id == Customer.id)
                      .where(Customer.status == "ativo")).all()
    returns: dict[int, list] = {d: [] for d in thresholds}
    without_future = []
    for c, last in rows:
        if c.id in future_ids:
            continue
        days = (now - last).days
        item = {"customer_id": str(c.id), "name": c.full_name, "phone": c.whatsapp or c.phone, "last_visit_at": last,
                "days": days, "marketing_consent": has_consent(db, c.id, "whatsapp_marketing")}
        without_future.append(item)
        bucket = None
        for d in thresholds:
            if days >= d:
                bucket = d
        if bucket:
            returns[bucket].append(item)
    inactive = db.scalars(select(CrmLead).where(CrmLead.stage == "cliente_inativo").limit(500)).all()
    bdays = birthdays_between(db, 0, 7)
    today = local_today()
    overdue_tasks = db.scalar(select(func.count()).select_from(CrmTask).where(
        CrmTask.status == "pendente", CrmTask.due_at < now)) or 0
    return {
        "return_thresholds": thresholds,
        "returns": {str(d): sorted(v, key=lambda x: -x["days"]) for d, v in returns.items()},
        "birthdays": [{"customer_id": str(c.id), "name": c.full_name, "birth_date": c.birth_date,
                       "today": c.birth_date.strftime("%m-%d") == today.strftime("%m-%d"),
                       "marketing_consent": has_consent(db, c.id, "whatsapp_marketing")} for c in bdays],
        "without_future": sorted(without_future, key=lambda x: -x["days"])[:300],
        "inactive": [{"lead_id": str(l.id), "customer_id": str(l.customer_id) if l.customer_id else None,
                      "name": l.name, "since": l.stage_changed_at} for l in inactive],
        "overdue_tasks": overdue_tasks,
    }


# ---------------------------------------------------------------- Campanhas
def _audience(db: Session, audience: dict) -> list[Customer]:
    stmt = select(Customer).where(Customer.status == "ativo")
    seg = audience.get("segment")
    if seg in ("novos", "ativos", "inativos", "recorrentes"):
        from app.services.customers import filter_condition

        stmt = stmt.where(filter_condition(db, seg))
    if audience.get("stage"):
        stmt = stmt.join(CrmLead, CrmLead.customer_id == Customer.id).where(CrmLead.stage == audience["stage"])
    if audience.get("no_visit_days"):
        limit = utcnow() - timedelta(days=int(audience["no_visit_days"]))
        recent = select(Appointment.customer_id).where(Appointment.status == "concluido", Appointment.start_at >= limit)
        stmt = stmt.where(Customer.id.not_in(recent))
    if audience.get("customer_ids"):
        stmt = stmt.where(Customer.id.in_([uuid.UUID(x) for x in audience["customer_ids"]]))
    customers = db.scalars(stmt).all()
    return customers


@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db), user: User = Depends(require("crm.read"))):
    rows = db.scalars(select(CrmCampaign).order_by(CrmCampaign.created_at.desc())).all()
    return [{"id": str(c.id), "name": c.name, "description": c.description, "template_id": str(c.template_id),
             "audience": c.audience, "status": c.status, "total_recipients": c.total_recipients,
             "queued_count": c.queued_count, "skipped_count": c.skipped_count, "created_at": c.created_at} for c in rows]


@router.post("/campaigns/preview")
def preview_campaign(data: CampaignIn, db: Session = Depends(get_db), user: User = Depends(require("crm.campaigns"))):
    customers = _audience(db, data.audience)
    allowed = [c for c in customers if has_consent(db, c.id, "whatsapp_marketing") and (c.whatsapp or c.phone)]
    return {"total": len(customers), "with_consent": len(allowed),
            "sample": [c.full_name for c in allowed[:10]]}


@router.post("/campaigns", status_code=201)
def create_campaign(data: CampaignIn, db: Session = Depends(get_db), user: User = Depends(require("crm.campaigns"))):
    tpl = db.get(WhatsappTemplate, data.template_id)
    if tpl is None:
        raise NotFound("Template")
    c = CrmCampaign(**data.model_dump(), created_by=user.id)
    db.add(c)
    audit(db, "campanha_criada", user=user, entity="campaign", details=data.model_dump(mode="json"))
    db.commit()
    return {"message": "Campanha criada como rascunho.", "id": str(c.id)}


@router.post("/campaigns/{campaign_id}/dispatch")
def dispatch_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("crm.campaigns"))):
    c = db.get(CrmCampaign, campaign_id)
    if c is None:
        raise NotFound("Campanha")
    if c.status != "rascunho":
        raise AppError("Campanha já disparada ou encerrada.")
    if not wa.is_enabled(db):
        raise AppError("Ative e configure a integração WhatsApp antes de disparar campanhas.")
    tpl = db.get(WhatsappTemplate, c.template_id)
    if tpl is None or tpl.meta_status != "APPROVED" or not tpl.is_active:
        raise AppError("O template da campanha precisa estar ativo e APROVADO pela Meta.")
    customers = _audience(db, c.audience)
    queued = skipped = 0
    for cust in customers:
        m = wa.enqueue(db, customer=cust, purpose="campanha", template=tpl, campaign_id=c.id,
                       dedupe_key=f"campanha:{c.id}:{cust.id}", user_id=user.id, automatic=False)
        if m is not None and m.status == "pendente":
            queued += 1
        else:
            skipped += 1
    c.status, c.total_recipients, c.queued_count, c.skipped_count = "enviando", len(customers), queued, skipped
    audit(db, "campanha_disparada", user=user, entity="campaign", entity_id=c.id,
          details={"enfileiradas": queued, "ignoradas": skipped})
    db.commit()
    return {"message": f"{queued} mensagem(ns) na fila; {skipped} ignorada(s) por falta de consentimento/telefone.",
            "queued": queued, "skipped": skipped}
