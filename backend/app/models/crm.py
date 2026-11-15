from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk
from app.models.customer import Customer

CRM_STAGES = (
    "novo_contato",
    "interessado",
    "avaliacao_agendada",
    "primeiro_atendimento",
    "cliente_recorrente",
    "pacote_contratado",
    "cliente_inativo",
)


class CrmLead(UUIDPk, Timestamps, Base):
    """Cartão do funil de relacionamento. Um por cliente (ou contato ainda sem cadastro completo)."""

    __tablename__ = "crm_leads"
    __table_args__ = (
        Index("uq_crm_leads_customer", "customer_id", unique=True, postgresql_where=text("customer_id IS NOT NULL")),
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str | None] = mapped_column(String(60))
    stage: Mapped[str] = mapped_column(String(30), default="novo_contato", index=True)
    interest_service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("services.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    next_contact_at: Mapped[datetime | None]
    stage_changed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    lost_reason: Mapped[str | None] = mapped_column(String(300))

    customer: Mapped[Customer | None] = relationship(lazy="joined")


class CrmInteraction(UUIDPk, Base):
    __tablename__ = "crm_interactions"
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crm_leads.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # ligacao | mensagem | whatsapp | email | presencial | nota | sistema
    direction: Mapped[str | None] = mapped_column(String(10))  # entrada | saida
    subject: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    whatsapp_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("whatsapp_messages.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class CrmTask(UUIDPk, Timestamps, Base):
    __tablename__ = "crm_tasks"
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="follow_up")  # retorno | lembrete | follow_up | aniversario | outro
    due_at: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(20), default="pendente", index=True)  # pendente | concluida | cancelada
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crm_leads.id", ondelete="CASCADE"))
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    completed_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class CrmCampaign(UUIDPk, Timestamps, Base):
    __tablename__ = "crm_campaigns"
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_templates.id", ondelete="RESTRICT"))
    audience: Mapped[dict] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="rascunho")  # rascunho | enviando | concluida | cancelada
    scheduled_at: Mapped[datetime | None]
    total_recipients: Mapped[int] = mapped_column(Integer, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
