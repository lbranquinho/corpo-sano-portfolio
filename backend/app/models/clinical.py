"""Dados clínicos (anamnese e fichas de atendimento).

Todo o conteúdo sensível fica em ``data_enc`` (JSON criptografado com chave exclusiva de saúde).
O acesso exige a permissão ``clinical.read`` e é registrado em auditoria.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPk
from app.models.catalog import Service
from app.models.clinic import Professional
from app.models.customer import Customer


class CustomerHealthRecord(UUIDPk, Base):
    __tablename__ = "customer_health_records"
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data_enc: Mapped[str] = mapped_column(Text)
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_text: Mapped[str | None] = mapped_column(Text)
    consent_accepted_at: Mapped[datetime | None]
    consent_accepted_name: Mapped[str | None] = mapped_column(String(150))
    consent_accepted_document: Mapped[str | None] = mapped_column(String(14))
    consent_ip: Mapped[str | None] = mapped_column(String(64))
    consent_hash: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Treatment(UUIDPk, Base):
    """Atendimento realizado (vinculado ao agendamento quando houver)."""

    __tablename__ = "treatments"
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), unique=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), index=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("professionals.id", ondelete="RESTRICT"), index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"))
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(20), default="concluido")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    customer: Mapped[Customer] = relationship(lazy="joined")
    professional: Mapped[Professional] = relationship(lazy="joined")
    service: Mapped[Service] = relationship(lazy="joined")


class TreatmentRecord(UUIDPk, Base):
    """Ficha do atendimento (técnica, produtos, evolução...). Registros são imutáveis; correções geram novo registro."""

    __tablename__ = "treatment_records"
    treatment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("treatments.id", ondelete="CASCADE"), index=True)
    data_enc: Mapped[str] = mapped_column(Text)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    next_return_date: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
