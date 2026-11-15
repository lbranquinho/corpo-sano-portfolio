from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require
from app.core.errors import AppError, IntegrationError, NotFound
from app.core.settings_store import get_group, get_setting, has_secret, set_setting
from app.core.utils import utcnow
from app.integrations.whatsapp.client import WhatsAppError, verify_signature
from app.models.auth import User
from app.models.customer import Customer
from app.models.whatsapp import WhatsappMessage, WhatsappTemplate
from app.schemas.common import Page
from app.services import whatsapp as svc
from app.services.customers import get_customer_for

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])
log = logging.getLogger("corposano.whatsapp")


class WhatsAppSettingsIn(BaseModel):
    enabled: bool
    api_version: str = Field(pattern=r"^v\d+\.\d+$")
    business_id: str | None = Field(default=None, max_length=40)
    waba_id: str | None = Field(default=None, max_length=40)
    phone_number_id: str | None = Field(default=None, max_length=40)
    access_token: str | None = Field(default=None, description="Deixe vazio para manter o atual")
    app_secret: str | None = None
    verify_token: str | None = None
    reminder_hours_before: int = Field(ge=1, le=72)
    auto_confirmation: bool
    auto_reminder: bool
    auto_reschedule: bool
    auto_cancellation: bool
    auto_thanks: bool
    auto_birthday: bool
    birthday_hour: int = Field(ge=6, le=20)


class TemplateUpdate(BaseModel):
    purpose: str | None = None
    parameters: list[str] = Field(default_factory=list)
    is_active: bool


class SendTemplateIn(BaseModel):
    customer_id: uuid.UUID
    template_id: uuid.UUID
    appointment_id: uuid.UUID | None = None


class SendTextIn(BaseModel):
    customer_id: uuid.UUID
    body: str = Field(min_length=1, max_length=4000)


def _webhook_url() -> str:
    return get_settings().public_base_url.rstrip("/") + "/api/v1/whatsapp/webhook"


@router.get("/settings")
def read_settings(db: Session = Depends(get_db), user: User = Depends(require("whatsapp.settings"))):
    g = get_group(db, "whatsapp.")
    return {
        **{k.split(".", 1)[1]: v for k, v in g.items()},
        "access_token_set": has_secret(db, "whatsapp.access_token"),
        "app_secret_set": has_secret(db, "whatsapp.app_secret"),
        "verify_token_set": has_secret(db, "whatsapp.verify_token"),
        "webhook_url": _webhook_url(),
        "purposes": svc.PURPOSES,
        "variables": svc.ALLOWED_VARIABLES,
    }


@router.put("/settings")
def update_settings(data: WhatsAppSettingsIn, db: Session = Depends(get_db), user: User = Depends(require("whatsapp.settings"))):
    plain = data.model_dump(exclude={"access_token", "app_secret", "verify_token"})
    for k, v in plain.items():
        set_setting(db, f"whatsapp.{k}", v if v is not None else "", user.id)
    for secret in ("access_token", "app_secret", "verify_token"):
        value = getattr(data, secret)
        if value:
            set_setting(db, f"whatsapp.{secret}", value.strip(), user.id)
    if data.enabled and not (has_secret(db, "whatsapp.access_token") and get_setting(db, "whatsapp.phone_number_id")):
        raise AppError("Para ativar, informe ao menos o Access Token e o Phone Number ID.")
    audit(db, "whatsapp_configurado", user=user, entity="settings", entity_id="whatsapp",
          details={**plain, "token_alterado": bool(data.access_token), "secret_alterado": bool(data.app_secret)})
    db.commit()
    return {"message": "Configurações do WhatsApp salvas."}


@router.post("/test")
def test_connection(db: Session = Depends(get_db), user: User = Depends(require("whatsapp.settings"))):
    try:
        with svc.make_client(db) as client:
            info = client.phone_info()
    except WhatsAppError as exc:
        raise IntegrationError(f"Falha na conexão com a Meta: {exc.message}") from exc
    audit(db, "whatsapp_teste_conexao", user=user, entity="settings", entity_id="whatsapp")
    db.commit()
    return {"message": "Conexão com a WhatsApp Cloud API realizada com sucesso.", "phone": info}


@router.get("/status")
def integration_status(db: Session = Depends(get_db), user: User = Depends(require("whatsapp.read"))):
    counts = dict(db.execute(select(WhatsappMessage.status, func.count()).group_by(WhatsappMessage.status)).all())
    last_in = db.scalar(select(func.max(WhatsappMessage.created_at)).where(WhatsappMessage.direction == "entrada"))
    return {
        "enabled": svc.is_enabled(db),
        "configured": has_secret(db, "whatsapp.access_token") and bool(get_setting(db, "whatsapp.phone_number_id")),
        "webhook_configured": has_secret(db, "whatsapp.verify_token") and has_secret(db, "whatsapp.app_secret"),
        "approved_templates": db.scalar(select(func.count()).select_from(WhatsappTemplate).where(
            WhatsappTemplate.meta_status == "APPROVED", WhatsappTemplate.is_active.is_(True))) or 0,
        "queue": counts,
        "last_inbound_at": last_in,
    }


@router.get("/templates")
def list_templates(db: Session = Depends(get_db), user: User = Depends(require("whatsapp.read"))):
    rows = db.scalars(select(WhatsappTemplate).order_by(WhatsappTemplate.name)).all()
    return [{"id": str(t.id), "name": t.name, "language": t.language, "category": t.category, "purpose": t.purpose,
             "body_text": t.body_text, "parameters": t.parameters, "meta_status": t.meta_status,
             "is_active": t.is_active, "synced_at": t.synced_at} for t in rows]


@router.post("/templates/sync")
def sync_templates(db: Session = Depends(get_db), user: User = Depends(require("whatsapp.settings"))):
    try:
        result = svc.sync_templates(db)
    except WhatsAppError as exc:
        raise IntegrationError(f"Não foi possível sincronizar: {exc.message}") from exc
    audit(db, "whatsapp_templates_sincronizados", user=user, details=result)
    db.commit()
    return {"message": f"Templates sincronizados: {result['total']} ({result['created']} novos).", **result}


@router.put("/templates/{template_id}")
def update_template(template_id: uuid.UUID, data: TemplateUpdate, db: Session = Depends(get_db),
                    user: User = Depends(require("whatsapp.settings"))):
    t = db.get(WhatsappTemplate, template_id)
    if t is None:
        raise NotFound("Template")
    if data.purpose and data.purpose not in svc.PURPOSES:
        raise AppError("Finalidade inválida.")
    bad = [p for p in data.parameters if p not in svc.ALLOWED_VARIABLES]
    if bad:
        raise AppError(f"Variáveis não permitidas: {', '.join(bad)}. Dados de saúde nunca podem ser enviados.")
    expected = (t.body_text or "").count("{{")
    if t.body_text and len(data.parameters) != expected:
        raise AppError(f"O template possui {expected} variável(is); mapeie todas.")
    if data.purpose in ("aniversario", "retorno", "campanha") and t.category != "MARKETING":
        raise AppError("Finalidades de relacionamento/campanha exigem template da categoria MARKETING.")
    t.purpose, t.parameters, t.is_active = data.purpose, data.parameters, data.is_active
    audit(db, "whatsapp_template_mapeado", user=user, entity="whatsapp_template", entity_id=t.id,
          details=data.model_dump())
    db.commit()
    return {"message": "Template atualizado."}


@router.get("/messages", response_model=Page[dict])
def list_messages(status: str | None = None, customer_id: uuid.UUID | None = None, direction: str | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(50, le=200), db: Session = Depends(get_db),
                  user: User = Depends(require("whatsapp.read"))):
    stmt = select(WhatsappMessage, Customer.full_name).outerjoin(Customer, Customer.id == WhatsappMessage.customer_id)
    if status:
        stmt = stmt.where(WhatsappMessage.status == status)
    if customer_id:
        stmt = stmt.where(WhatsappMessage.customer_id == customer_id)
    if direction:
        stmt = stmt.where(WhatsappMessage.direction == direction)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(WhatsappMessage.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = [{"id": str(m.id), "customer_id": str(m.customer_id) if m.customer_id else None, "customer_name": name,
              "phone": m.phone, "direction": m.direction, "kind": m.kind, "purpose": m.purpose, "content": m.content,
              "status": m.status, "attempts": m.attempts, "last_error": m.last_error, "created_at": m.created_at,
              "sent_at": m.sent_at, "delivered_at": m.delivered_at, "read_at": m.read_at} for m, name in rows]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/messages/template", status_code=201)
def send_template(data: SendTemplateIn, db: Session = Depends(get_db), user: User = Depends(require("whatsapp.send"))):
    c = get_customer_for(db, user, data.customer_id)
    tpl = db.get(WhatsappTemplate, data.template_id)
    if tpl is None or not tpl.is_active or tpl.meta_status != "APPROVED":
        raise AppError("Template inexistente, inativo ou não aprovado pela Meta.")
    from app.models.schedule import Appointment

    appt = db.get(Appointment, data.appointment_id) if data.appointment_id else None
    if not svc.is_enabled(db):
        raise AppError("Integração WhatsApp desativada.")
    m = svc.enqueue(db, customer=c, purpose=tpl.purpose or "campanha", template=tpl, appointment=appt,
                    user_id=user.id, automatic=False)
    audit(db, "whatsapp_envio_manual", user=user, entity="customer", entity_id=c.id, details={"template": tpl.name})
    db.commit()
    if m is None or m.status == "bloqueada":
        raise AppError(m.last_error if m else "Mensagem não enfileirada.")
    return {"message": "Mensagem colocada na fila de envio.", "id": str(m.id)}


@router.post("/messages/text", status_code=201)
def send_text(data: SendTextIn, db: Session = Depends(get_db), user: User = Depends(require("whatsapp.send"))):
    c = get_customer_for(db, user, data.customer_id)
    m = svc.enqueue_text(db, customer=c, body=data.body, user_id=user.id)
    audit(db, "whatsapp_texto_enviado", user=user, entity="customer", entity_id=c.id)
    db.commit()
    return {"message": "Mensagem colocada na fila de envio.", "id": str(m.id)}


@router.post("/messages/{message_id}/retry")
def retry(message_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("whatsapp.send"))):
    m = db.get(WhatsappMessage, message_id)
    if m is None or m.direction != "saida":
        raise NotFound("Mensagem")
    if m.status not in ("falhou",):
        raise AppError("Somente mensagens com falha podem ser reenviadas.")
    m.status, m.attempts, m.next_attempt_at, m.last_error = "pendente", 0, utcnow(), None
    db.commit()
    return {"message": "Mensagem reenfileirada."}


@router.post("/messages/{message_id}/cancel")
def cancel(message_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("whatsapp.send"))):
    m = db.get(WhatsappMessage, message_id)
    if m is None or m.status != "pendente":
        raise AppError("Somente mensagens pendentes podem ser canceladas.")
    m.status, m.next_attempt_at = "cancelada", None
    db.commit()
    return {"message": "Envio cancelado."}


# ---------------------------------------------------------------- Webhook (público, validado)
@router.get("/webhook", include_in_schema=False)
def webhook_verify(request: Request, db: Session = Depends(get_db)):
    params = request.query_params
    expected = get_setting(db, "whatsapp.verify_token")
    if params.get("hub.mode") == "subscribe" and expected and params.get("hub.verify_token") == expected:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)


@router.post("/webhook", include_in_schema=False)
async def webhook_receive(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    secret = get_setting(db, "whatsapp.app_secret")
    if not verify_signature(secret or "", raw, request.headers.get("x-hub-signature-256")):
        log.warning("Webhook WhatsApp com assinatura inválida rejeitado.")
        return PlainTextResponse("Invalid signature", status_code=401)
    try:
        payload = json.loads(raw)
    except ValueError:
        return PlainTextResponse("Bad request", status_code=400)
    try:
        stats = svc.process_webhook(db, payload)
        db.commit()
    except Exception:  # nunca devolver erro 5xx em loop para a Meta sem registrar
        db.rollback()
        log.exception("Erro ao processar webhook do WhatsApp")
        return PlainTextResponse("Error", status_code=500)
    return {"received": True, **stats}
