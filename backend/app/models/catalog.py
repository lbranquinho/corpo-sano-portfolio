from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, Numeric, String, Table, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk
from app.models.clinic import Professional

service_professionals = Table(
    "service_professionals",
    Base.metadata,
    Column("service_id", Uuid, ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
    Column("professional_id", Uuid, ForeignKey("professionals.id", ondelete="CASCADE"), primary_key=True),
)


class ServiceCategory(UUIDPk, Timestamps, Base):
    __tablename__ = "service_categories"
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(String(300))
    color: Mapped[str] = mapped_column(String(9), default="#2563EB")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TaxServiceCode(UUIDPk, Timestamps, Base):
    """Código de serviço fiscal configurável. Nada é fixado: o contador informa e valida."""

    __tablename__ = "tax_service_codes"
    national_code: Mapped[str] = mapped_column(String(6))  # cTribNac (6 dígitos)
    municipal_code: Mapped[str | None] = mapped_column(String(20))  # cTribMun, se o município exigir
    lc116_item: Mapped[str | None] = mapped_column(String(10))  # subitem da lista de serviços
    nbs_code: Mapped[str | None] = mapped_column(String(9))
    description: Mapped[str] = mapped_column(String(300))
    iss_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    iss_withheld_default: Mapped[bool] = mapped_column(Boolean, default=False)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validated_by: Mapped[str | None] = mapped_column(String(120))
    validated_at: Mapped[datetime | None]
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Service(UUIDPk, Timestamps, Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        CheckConstraint("price >= 0", name="price_non_negative"),
    )
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("service_categories.id", ondelete="SET NULL"))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[Decimal]
    tax_service_code_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tax_service_codes.id", ondelete="SET NULL")
    )
    nfse_description: Mapped[str | None] = mapped_column(String(1000))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped[ServiceCategory | None] = relationship(lazy="joined")
    tax_service_code: Mapped[TaxServiceCode | None] = relationship(lazy="joined")
    professionals: Mapped[list[Professional]] = relationship(secondary=service_professionals, lazy="selectin")


class PackagePlan(UUIDPk, Timestamps, Base):
    """Modelo de pacote oferecido pela clínica (catálogo)."""

    __tablename__ = "package_plans"
    __table_args__ = (
        CheckConstraint("sessions_count > 0", name="sessions_positive"),
        CheckConstraint("price >= 0", name="price_non_negative"),
    )
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"))
    sessions_count: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal]
    validity_days: Mapped[int | None] = mapped_column(Integer)
    no_show_consumes: Mapped[bool] = mapped_column(Boolean, default=True)
    late_cancel_consumes: Mapped[bool] = mapped_column(Boolean, default=False)
    late_cancel_hours: Mapped[int] = mapped_column(Integer, default=24)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    service: Mapped[Service] = relationship(lazy="joined")
