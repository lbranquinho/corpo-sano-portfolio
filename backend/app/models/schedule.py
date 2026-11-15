from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk
from app.models.catalog import Service
from app.models.clinic import Professional, Room
from app.models.customer import Customer

APPOINTMENT_STATUSES = ("agendado", "confirmado", "em_atendimento", "concluido", "cancelado", "falta")
INACTIVE_STATUSES = ("cancelado", "falta")


class Appointment(UUIDPk, Timestamps, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="time_order"),
        CheckConstraint("price >= 0 AND discount >= 0 AND discount <= price", name="amounts"),
        CheckConstraint(
            "status IN ('agendado','confirmado','em_atendimento','concluido','cancelado','falta')", name="status"
        ),
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), index=True)
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), index=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("professionals.id", ondelete="RESTRICT"), index=True
    )
    room_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), index=True)
    start_at: Mapped[datetime] = mapped_column(index=True)
    end_at: Mapped[datetime]
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal]
    discount: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_methods.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="agendado", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    is_evaluation: Mapped[bool] = mapped_column(Boolean, default=False)
    package_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("packages.id", ondelete="SET NULL"), index=True)
    recurrence_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    confirmed_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    reminder_sent_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    customer: Mapped[Customer] = relationship(lazy="joined")
    service: Mapped[Service] = relationship(lazy="joined")
    professional: Mapped[Professional] = relationship(lazy="joined")
    room: Mapped[Room | None] = relationship(lazy="joined")

    @property
    def net_price(self) -> Decimal:
        return (self.price or Decimal("0")) - (self.discount or Decimal("0"))


class AppointmentStatusHistory(UUIDPk, Base):
    __tablename__ = "appointment_status_history"
    appointment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(300))
    old_start_at: Mapped[datetime | None]
    new_start_at: Mapped[datetime | None]
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())
