from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk

TRANSACTIONAL_PURPOSES = ("confirmacao", "lembrete", "remarcacao", "cancelamento", "agradecimento")
MARKETING_PURPOSES = ("aniversario", "retorno", "campanha")


class WhatsappTemplate(UUIDPk, Timestamps, Base):
    """Modelo de mensagem. Mensagens iniciadas pela empresa usam templates aprovados pela Meta."""

    __tablename__ = "whatsapp_templates"
    __table_args__ = (UniqueConstraint("name", "language", name="uq_whatsapp_templates_name_language"),)
    name: Mapped[str] = mapped_column(String(512))
    language: Mapped[str] = mapped_column(String(15), default="pt_BR")
    category: Mapped[str] = mapped_column(String(20), default="UTILITY")  # UTILITY | MARKETING | AUTHENTICATION
    purpose: Mapped[str | None] = mapped_column(String(30), index=True)
    body_text: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[list] = mapped_column(default=list)  # ex.: ["cliente_nome", "data", "hora"]
    meta_status: Mapped[str] = mapped_column(String(20), default="NAO_SINCRONIZADO")
    meta_id: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime | None]


class WhatsappMessage(UUIDPk, Base):
    __tablename__ = "whatsapp_messages"
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), index=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # saida | entrada
    kind: Mapped[str] = mapped_column(String(10))  # template | texto
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_templates.id", ondelete="SET NULL"))
    purpose: Mapped[str | None] = mapped_column(String(30))
    content: Mapped[str | None] = mapped_column(Text)
    variables: Mapped[dict | None]
    # pendente | enviando | enviada | entregue | lida | falhou | cancelada | bloqueada | recebida
    status: Mapped[str] = mapped_column(String(20), index=True)
    wa_message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime | None] = mapped_column(index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(20))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crm_campaigns.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    sent_at: Mapped[datetime | None]
    delivered_at: Mapped[datetime | None]
    read_at: Mapped[datetime | None]
    failed_at: Mapped[datetime | None]
