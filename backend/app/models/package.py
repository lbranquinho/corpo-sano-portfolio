from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk
from app.models.catalog import Service
from app.models.customer import Customer


class Package(UUIDPk, Timestamps, Base):
    """Pacote adquirido por um cliente."""

    __tablename__ = "packages"
    __table_args__ = (
        CheckConstraint("sessions_total > 0", name="sessions_positive"),
        CheckConstraint("sessions_used >= 0 AND sessions_used <= sessions_total", name="sessions_range"),
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("status IN ('ativo','concluido','expirado','cancelado')", name="status"),
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), index=True)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("package_plans.id", ondelete="SET NULL"))
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120))
    sessions_total: Mapped[int] = mapped_column(Integer)
    sessions_used: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[Decimal]
    purchased_at: Mapped[date] = mapped_column(Date)
    expires_at: Mapped[date | None] = mapped_column(Date)
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_methods.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="ativo", index=True)
    no_show_consumes: Mapped[bool] = mapped_column(Boolean, default=True)
    late_cancel_consumes: Mapped[bool] = mapped_column(Boolean, default=False)
    late_cancel_hours: Mapped[int] = mapped_column(Integer, default=24)
    notes: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    customer: Mapped[Customer] = relationship(lazy="joined")
    service: Mapped[Service] = relationship(lazy="joined")

    @property
    def sessions_remaining(self) -> int:
        return self.sessions_total - self.sessions_used


class PackageSession(UUIDPk, Base):
    """Baixa de sessão. Criada somente na conclusão do atendimento (ou por regra de falta/cancelamento)."""

    __tablename__ = "package_sessions"
    __table_args__ = (
        Index(
            "uq_package_sessions_appointment_active",
            "appointment_id",
            unique=True,
            postgresql_where=text("appointment_id IS NOT NULL AND reverted_at IS NULL"),
        ),
    )
    package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packages.id", ondelete="CASCADE"), index=True)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(String(30))  # atendimento | falta | cancelamento_tardio | ajuste
    consumed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    notes: Mapped[str | None] = mapped_column(String(300))
    reverted_at: Mapped[datetime | None]
    reverted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
