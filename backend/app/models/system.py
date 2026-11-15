from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class Clinic(UUIDPk, Timestamps, Base):
    __tablename__ = "clinics"
    name: Mapped[str] = mapped_column(String(150))
    trade_name: Mapped[str | None] = mapped_column(String(150))
    document: Mapped[str | None] = mapped_column(String(14))
    phone: Mapped[str | None] = mapped_column(String(20))
    whatsapp: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(String(200))
    zip_code: Mapped[str | None] = mapped_column(String(8))
    street: Mapped[str | None] = mapped_column(String(200))
    number: Mapped[str | None] = mapped_column(String(20))
    complement: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(2))
    timezone: Mapped[str] = mapped_column(String(50), default="America/Sao_Paulo")
    logo: Mapped[bytes | None] = mapped_column(LargeBinary)
    logo_content_type: Mapped[str | None] = mapped_column(String(50))


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any | None] = mapped_column(JSON)
    value_enc: Mapped[str | None] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    user_name: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str | None] = mapped_column(String(60), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[dict | None]


class BackupHistory(UUIDPk, Base):
    __tablename__ = "backup_history"
    kind: Mapped[str] = mapped_column(String(20))  # automatico | manual
    status: Mapped[str] = mapped_column(String(20), index=True)  # pendente | executando | sucesso | falha
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    file_name: Mapped[str | None] = mapped_column(String(200))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    offsite_status: Mapped[str | None] = mapped_column(String(20))  # nao_configurado | enviado | falha
    offsite_key: Mapped[str | None] = mapped_column(String(300))
    verified_at: Mapped[datetime | None]
    verify_status: Mapped[str | None] = mapped_column(String(20))  # ok | falha
    error: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class StoredFile(UUIDPk, Base):
    """Arquivo anexado (criptografado em disco). Vinculado a uma entidade por chaves opcionais."""

    __tablename__ = "stored_files"
    category: Mapped[str] = mapped_column(String(40), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(String(300))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    treatment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("treatments.id", ondelete="CASCADE"))
    health_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customer_health_records.id", ondelete="CASCADE")
    )
    fiscal_invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fiscal_invoices.id", ondelete="CASCADE"))
    fiscal_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fiscal_documents.id", ondelete="CASCADE")
    )
    tax_obligation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tax_obligations.id", ondelete="CASCADE"))
    tax_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tax_assessments.id", ondelete="CASCADE")
    )
    expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id", ondelete="CASCADE"))
    accounting_export_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounting_exports.id", ondelete="CASCADE")
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, default=1)
