"""Fila de mensagens WhatsApp (outbox no banco), consentimento, templates e webhooks.

Fluxo: evento → registro → preparação → envio pela API → registro do resultado → status.
Nenhum dado de saúde/anamnese é enviado: as variáveis permitidas são uma lista fechada.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_store import get_setting
from app.core.utils import local_today, normalize_phone, to_local, utcnow
from app.integrations.whatsapp.client import WhatsAppClient, WhatsAppError
from app.models.customer import Customer
from app.models.schedule import Appointment
from app.models.system import Clinic
from app.models.whatsapp import MARKETING_PURPOSES, TRANSACTIONAL_PURPOSES, WhatsappMessage, WhatsappTemplate

log = logging.getLogger("corposano.whatsapp")

# Variáveis permitidas nos templates (lista fechada; nada de dados clínicos)
ALLOWED_VARIABLES = {
    "cliente_nome": "Primeiro nome do cliente",
    "data": "Data do agendamento (dd/mm/aaaa)",
    "hora": "Horário do agendamento (hh:mm)",
    "servico": "Nome do serviço",
    "profissional": "Nome do profissional",
    "clinica_nome": "Nome da clínica",
    "clinica_telefone": "Telefone da clínica",
    "clinica_endereco": "Endereço da clínica",
}
PURPOSES = {
    "confirmacao": "Confirmação de agendamento",
    "lembrete": "Lembrete de agendamento",
    "remarcacao": "Aviso de remarcação",
    "cancelamento": "Aviso de cancelamento",
    "agradecimento": "Agradecimento pós-atendimento",
    "aniversario": "Aniversário",
    "retorno": "Convite de retorno",
    "campanha": "Campanha",
}
AUTO_TOGGLES = {
    "confirmacao": "whatsapp.auto_confirmation",
    "lembrete": "whatsapp.auto_reminder",
    "remarcacao": "whatsapp.auto_reschedule",
    "cancelamento": "whatsapp.auto_cancellation",
    "agradecimento": "whatsapp.auto_thanks",
    "aniversario": "whatsapp.auto_birthday",
}
BACKOFF_MINUTES = [1, 5, 15, 60, 180]


def is_enabled(db: Session) -> bool:
    return bool(get_setting(db, "whatsapp.enabled"))


def make_client(db: Session) -> WhatsAppClient:
    return WhatsAppClient(
        access_token=get_setting(db, "whatsapp.access_token") or "",
        phone_number_id=get_setting(db, "whatsapp.phone_number_id") or "",
        waba_id=get_setting(db, "whatsapp.waba_id") or None,
        api_version=get_setting(db, "whatsapp.api_version") or "v24.0",
    )


def consent_allows(db: Session, customer_id: uuid.UUID, purpose: str) -> tuple[bool, str | None]:
    from app.services.customers import has_consent

    if purpose in TRANSACTIONAL_PURPOSES:
        if not has_consent(db, customer_id, "whatsapp_transacional"):
            return False, "Cliente sem consentimento para mensagens de agendamento no WhatsApp."
    elif purpose in MARKETING_PURPOSES:
        if not has_consent(db, customer_id, "whatsapp_marketing"):
            return False, "Cliente sem consentimento para mensagens promocionais/relacionamento."
    return True, None


def build_variables(db: Session, customer: Customer, appointment: Appointment | None) -> dict[str, str]:
    clinic = db.scalar(select(Clinic).limit(1))
    v = {
        "cliente_nome": (customer.full_name or "").split(" ")[0],
        "clinica_nome": (clinic.trade_name or clinic.name) if clinic else "",
        "clinica_telefone": (clinic.whatsapp or clinic.phone or "") if clinic else "",
        "clinica_endereco": ", ".join(p for p in [clinic.street, clinic.number, clinic.district, clinic.city] if p) if clinic else "",
    }
    if appointment:
        start = to_local(appointment.start_at)
        v.update(data=start.strftime("%d/%m/%Y"), hora=start.strftime("%H:%M"), servico=appointment.service.name,
                 profissional=appointment.professional.name.split(" ")[0])
    return v


def render(template: WhatsappTemplate, variables: dict[str, str]) -> tuple[list[str], str]:
    params = [str(variables.get(key, "")) for key in (template.parameters or [])]
    missing = [k for k in (template.parameters or []) if not variables.get(k)]
    if missing:
        raise WhatsAppError(f"Variáveis sem valor para o template: {', '.join(missing)}")
    text = template.body_text or ""
    for i, p in enumerate(params, start=1):
        text = text.replace("{{%d}}" % i, p)
    return params, text


def find_template(db: Session, purpose: str) -> WhatsappTemplate | None:
    return db.scalar(
        select(WhatsappTemplate)
        .where(WhatsappTemplate.purpose == purpose, WhatsappTemplate.is_active.is_(True),
               WhatsappTemplate.meta_status == "APPROVED")
        .order_by(WhatsappTemplate.updated_at.desc())
        .limit(1)
    )


def enqueue(
    db: Session, *, customer: Customer, purpose: str, appointment: Appointment | None = None,
    template: WhatsappTemplate | None = None, dedupe_key: str | None = None, campaign_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None, automatic: bool = True,
) -> WhatsappMessage | None:
    """Coloca a mensagem na fila. Retorna None quando a automação está desligada."""
    if not is_enabled(db):
        return None
    if automatic and purpose in AUTO_TOGGLES and not get_setting(db, AUTO_TOGGLES[purpose]):
        return None
    if dedupe_key and db.scalar(select(WhatsappMessage.id).where(WhatsappMessage.dedupe_key == dedupe_key)):
        return None
    phone = customer.whatsapp or customer.phone
    msg = WhatsappMessage(
        customer_id=customer.id, phone=phone or "", direction="saida", kind="template", purpose=purpose,
        appointment_id=appointment.id if appointment else None, campaign_id=campaign_id, created_by=user_id,
        dedupe_key=dedupe_key, status="pendente", next_attempt_at=utcnow(),
    )
    reason = None
    if not phone:
        reason = "Cliente sem número de WhatsApp cadastrado."
    else:
        ok, reason = consent_allows(db, customer.id, purpose)
    tpl = template or find_template(db, purpose)
    if reason is None and tpl is None:
        reason = f"Nenhum template APROVADO pela Meta vinculado à finalidade '{PURPOSES.get(purpose, purpose)}'."
    if reason is None:
        try:
            params, text = render(tpl, build_variables(db, customer, appointment))
            msg.template_id, msg.variables, msg.content = tpl.id, {"params": params}, text
        except WhatsAppError as exc:
            reason = exc.message
    if reason:
        msg.status, msg.last_error, msg.next_attempt_at = "bloqueada", reason, None
    db.add(msg)
    db.flush()
    return msg


def enqueue_text(db: Session, *, customer: Customer, body: str, user_id: uuid.UUID | None) -> WhatsappMessage:
    """Texto livre: só permitido dentro da janela de 24 h após a última mensagem do cliente."""
    from app.core.errors import AppError

    if not is_enabled(db):
        raise AppError("Integração WhatsApp desativada.")
    last = customer.last_inbound_whatsapp_at
    if not last or last < utcnow() - timedelta(hours=24):
        raise AppError("Fora da janela de 24 h de atendimento: utilize um template aprovado.")
    phone = customer.whatsapp or customer.phone
    if not phone:
        raise AppError("Cliente sem número de WhatsApp.")
    msg = WhatsappMessage(customer_id=customer.id, phone=phone, direction="saida", kind="texto", purpose="atendimento",
                          content=body, status="pendente", next_attempt_at=utcnow(), created_by=user_id)
    db.add(msg)
    db.flush()
    return msg


def _send_one(db: Session, client: WhatsAppClient, msg: WhatsappMessage) -> None:
    msg.attempts += 1
    try:
        if msg.kind == "template":
            tpl = db.get(WhatsappTemplate, msg.template_id) if msg.template_id else None
            if tpl is None or tpl.meta_status != "APPROVED" or not tpl.is_active:
                raise WhatsAppError("Template indisponível ou não aprovado.", retryable=False)
            wa_id = client.send_template(msg.phone, tpl.name, tpl.language, (msg.variables or {}).get("params", []))
        else:
            wa_id = client.send_text(msg.phone, msg.content or "")
        msg.status, msg.wa_message_id, msg.sent_at = "enviada", wa_id, utcnow()
        msg.last_error, msg.error_code, msg.next_attempt_at = None, None, None
        if msg.customer_id:
            from app.services.crm import log_interaction

            log_interaction(db, msg.customer_id, "whatsapp", f"WhatsApp: {PURPOSES.get(msg.purpose or '', msg.purpose)}",
                            msg.content, direction="saida", user_id=msg.created_by, whatsapp_message_id=msg.id)
    except WhatsAppError as exc:
        msg.last_error, msg.error_code = exc.message[:1000], exc.code
        if exc.retryable and msg.attempts < msg.max_attempts:
            delay = BACKOFF_MINUTES[min(msg.attempts - 1, len(BACKOFF_MINUTES) - 1)]
            msg.status, msg.next_attempt_at = "pendente", utcnow() + timedelta(minutes=delay)
        else:
            msg.status, msg.failed_at, msg.next_attempt_at = "falhou", utcnow(), None
        log.warning("Falha no envio WhatsApp %s (tentativa %s): %s", msg.id, msg.attempts, exc.code or exc.message[:80])


def process_queue(db: Session, limit: int = 30) -> int:
    """Executado pelo worker: envia mensagens pendentes com tentativas controladas."""
    if not is_enabled(db):
        return 0
    ids = db.scalars(
        select(WhatsappMessage.id)
        .where(WhatsappMessage.status == "pendente", WhatsappMessage.direction == "saida",
               WhatsappMessage.next_attempt_at <= utcnow())
        .order_by(WhatsappMessage.next_attempt_at)
        .limit(limit)
    ).all()
    if not ids:
        return 0
    try:
        client = make_client(db)
    except WhatsAppError as exc:
        log.warning("WhatsApp não configurado: %s", exc.message)
        return 0
    sent = 0
    with client:
        for mid in ids:
            msg = db.scalar(select(WhatsappMessage).where(WhatsappMessage.id == mid, WhatsappMessage.status == "pendente")
                            .with_for_update(skip_locked=True))
            if msg is None:
                continue
            msg.status = "enviando"
            db.flush()
            _send_one(db, client, msg)
            db.commit()
            sent += msg.status == "enviada"
    return sent


def schedule_reminders(db: Session) -> int:
    """Enfileira lembretes X horas antes do atendimento (sem duplicar)."""
    if not is_enabled(db) or not get_setting(db, "whatsapp.auto_reminder"):
        return 0
    hours = int(get_setting(db, "whatsapp.reminder_hours_before") or 24)
    now = utcnow()
    appts = db.scalars(
        select(Appointment).where(
            Appointment.status.in_(("agendado", "confirmado")),
            Appointment.start_at > now,
            Appointment.start_at <= now + timedelta(hours=hours),
            Appointment.reminder_sent_at.is_(None),
        )
    ).all()
    count = 0
    for a in appts:
        key = f"lembrete:{a.id}:{int(a.start_at.timestamp())}"
        m = enqueue(db, customer=a.customer, purpose="lembrete", appointment=a, dedupe_key=key)
        a.reminder_sent_at = now
        count += 1 if m is not None else 0
    return count


def schedule_birthdays(db: Session) -> int:
    if not is_enabled(db) or not get_setting(db, "whatsapp.auto_birthday"):
        return 0
    from app.services.customers import birthdays_between

    if to_local(utcnow()).hour < int(get_setting(db, "whatsapp.birthday_hour") or 9):
        return 0
    year = local_today().year
    n = 0
    for c in birthdays_between(db, 0, 1):
        if enqueue(db, customer=c, purpose="aniversario", dedupe_key=f"aniversario:{c.id}:{year}"):
            n += 1
    return n


def _ts(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return utcnow()


STATUS_MAP = {"sent": "enviada", "delivered": "entregue", "read": "lida", "failed": "falhou"}
STATUS_RANK = {"pendente": 0, "enviando": 1, "enviada": 2, "entregue": 3, "lida": 4, "falhou": 5}


def process_webhook(db: Session, payload: dict) -> dict[str, int]:
    """Processa statuses (entrega/leitura) e mensagens recebidas."""
    from app.services.crm import log_interaction
    from app.services.customers import find_by_phone, record_consent

    stats = {"statuses": 0, "messages": 0}
    optout = [k.upper() for k in (get_setting(db, "whatsapp.optout_keywords") or [])]
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            for st in value.get("statuses", []) or []:
                msg = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == st.get("id")))
                new = STATUS_MAP.get(st.get("status", ""))
                if msg is None or new is None:
                    continue
                when = _ts(st.get("timestamp"))
                if new == "falhou":
                    errs = st.get("errors") or [{}]
                    msg.status, msg.failed_at = "falhou", when
                    msg.error_code = str(errs[0].get("code") or "")
                    msg.last_error = (errs[0].get("title") or errs[0].get("message") or "Falha informada pela Meta")[:1000]
                elif STATUS_RANK.get(new, 0) > STATUS_RANK.get(msg.status, 0):
                    msg.status = new
                    if new == "entregue":
                        msg.delivered_at = when
                    if new == "lida":
                        msg.read_at = when
                        msg.delivered_at = msg.delivered_at or when
                stats["statuses"] += 1
            for m in value.get("messages", []) or []:
                wa_id = m.get("id")
                if wa_id and db.scalar(select(WhatsappMessage.id).where(WhatsappMessage.wa_message_id == wa_id)):
                    continue  # reentrega do webhook
                try:
                    phone = normalize_phone(m.get("from"))
                except ValueError:
                    phone = re.sub(r"\D", "", m.get("from") or "")[:20]
                customer = find_by_phone(db, phone) if phone else None
                mtype = m.get("type")
                body = (m.get("text") or {}).get("body") if mtype == "text" else \
                    (m.get("button") or {}).get("text") or f"[{mtype}]"
                inbound = WhatsappMessage(
                    customer_id=customer.id if customer else None, phone=phone or "", direction="entrada",
                    kind="texto", content=(body or "")[:4000], status="recebida", wa_message_id=wa_id,
                    created_at=_ts(m.get("timestamp")),
                )
                db.add(inbound)
                db.flush()
                if customer:
                    customer.last_inbound_whatsapp_at = _ts(m.get("timestamp"))
                    log_interaction(db, customer.id, "whatsapp", "Mensagem recebida no WhatsApp", body,
                                    direction="entrada", whatsapp_message_id=inbound.id)
                    if body and body.strip().upper() in optout:
                        record_consent(db, customer.id, "whatsapp_marketing", False, source="whatsapp",
                                       notes="Opt-out solicitado pelo cliente via WhatsApp")
                        log_interaction(db, customer.id, "sistema", "Opt-out de mensagens promocionais",
                                        "Cliente solicitou não receber campanhas pelo WhatsApp.")
                stats["messages"] += 1
    return stats


def sync_templates(db: Session) -> dict[str, int]:
    with make_client(db) as client:
        remote = client.list_templates()
    created = updated = 0
    for t in remote:
        body = next((c.get("text") for c in t.get("components", []) if c.get("type") == "BODY"), None)
        row = db.scalar(select(WhatsappTemplate).where(WhatsappTemplate.name == t.get("name"),
                                                       WhatsappTemplate.language == t.get("language")))
        if row is None:
            n_params = len(re.findall(r"\{\{\d+\}\}", body or ""))
            row = WhatsappTemplate(name=t["name"], language=t.get("language", "pt_BR"), parameters=[""] * n_params,
                                   is_active=False)
            db.add(row)
            created += 1
        else:
            updated += 1
        row.category = t.get("category", row.category)
        row.meta_status = t.get("status", "DESCONHECIDO")
        row.meta_id = t.get("id")
        row.body_text = body
        row.synced_at = utcnow()
    db.flush()
    return {"created": created, "updated": updated, "total": len(remote)}
