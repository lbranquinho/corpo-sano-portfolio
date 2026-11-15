from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class Customer(UUIDPk, Timestamps, Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index("uq_customers_cpf", "cpf", unique=True, postgresql_where=text("cpf IS NOT NULL")),
    )
    full_name: Mapped[str] = mapped_column(String(150))
    name_search: Mapped[str] = mapped_column(String(150), index=True)  # minúsculo e sem acentos
    cpf: Mapped[str | None] = mapped_column(String(11))
    birth_date: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    whatsapp: Mapped[str | None] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(200))
    zip_code: Mapped[str | None] = mapped_column(String(8))
    street: Mapped[str | None] = mapped_column(String(200))
    number: Mapped[str | None] = mapped_column(String(20))
    complement: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(2))
    ibge_code: Mapped[str | None] = mapped_column(String(7))
    source: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)
    preferences: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="ativo", index=True)  # ativo | inativo | anonimizado
    last_inbound_whatsapp_at: Mapped[datetime | None]
    anonymized_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class CustomerConsent(UUIDPk, Base):
    """Registro imutável de consentimentos (LGPD). O estado vigente é o registro mais recente por tipo."""

    __tablename__ = "customer_consents"
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    consent_type: Mapped[str] = mapped_column(String(40))
    granted: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(40), default="sistema")
    notes: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
