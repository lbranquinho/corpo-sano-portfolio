from __future__ import annotations

import datetime as dt
import uuid
from datetime import datetime, time

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class Professional(UUIDPk, Timestamps, Base):
    __tablename__ = "professionals"
    name: Mapped[str] = mapped_column(String(120))
    cpf: Mapped[str | None] = mapped_column(String(11))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(200))
    registration: Mapped[str | None] = mapped_column(String(60))
    specialties: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(9), default="#2563EB")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Room(UUIDPk, Timestamps, Base):
    __tablename__ = "rooms"
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(String(300))
    color: Mapped[str] = mapped_column(String(9), default="#8B5CF6")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BusinessHour(UUIDPk, Base):
    """Funcionamento da clínica por dia da semana (0 = segunda ... 6 = domingo)."""

    __tablename__ = "business_hours"
    __table_args__ = (CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),)
    weekday: Mapped[int] = mapped_column(Integer, unique=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    open_time: Mapped[time | None] = mapped_column(Time)
    close_time: Mapped[time | None] = mapped_column(Time)
    break_start: Mapped[time | None] = mapped_column(Time)
    break_end: Mapped[time | None] = mapped_column(Time)


class ProfessionalAvailability(UUIDPk, Base):
    """Disponibilidade específica do profissional. Sem registros = segue o horário da clínica."""

    __tablename__ = "professional_availability"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="time_order"),
    )
    professional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("professionals.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)


class Holiday(UUIDPk, Base):
    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("date", name="uq_holidays_date"),)
    date: Mapped[dt.date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(120))
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)


class ScheduleBlock(UUIDPk, Timestamps, Base):
    """Bloqueio de horário: de um profissional, de uma sala ou da clínica inteira (ambos nulos)."""

    __tablename__ = "schedule_blocks"
    __table_args__ = (CheckConstraint("end_at > start_at", name="time_order"),)
    professional_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("professionals.id", ondelete="CASCADE"), index=True
    )
    room_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    start_at: Mapped[datetime] = mapped_column(index=True)
    end_at: Mapped[datetime]
    reason: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
