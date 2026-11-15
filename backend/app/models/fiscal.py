"""Corpo Sano Contábil — cadastro fiscal, NFS-e, tributos, obrigações e exportações."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk

INVOICE_STATUSES = (
    "rascunho",
    "aguardando_transmissao",
    "transmitindo",
    "autorizada",
    "rejeitada",
    "cancelada",
    "substituida",
)
ACTIVE_INVOICE_STATUSES = ("rascunho", "aguardando_transmissao", "transmitindo", "autorizada")
TAX_REGIMES = ("mei", "simples_nacional", "lucro_presumido", "lucro_real")


class TaxCompanySettings(UUIDPk, Base):
    __tablename__ = "tax_company_settings"
    legal_name: Mapped[str | None] = mapped_column(String(150))
    trade_name: Mapped[str | None] = mapped_column(String(150))
    cnpj: Mapped[str | None] = mapped_column(String(14))
    municipal_registration: Mapped[str | None] = mapped_column(String(20))
    state_registration: Mapped[str | None] = mapped_column(String(20))
    zip_code: Mapped[str | None] = mapped_column(String(8))
    street: Mapped[str | None] = mapped_column(String(200))
    number: Mapped[str | None] = mapped_column(String(20))
    complement: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100))
    municipality_name: Mapped[str | None] = mapped_column(String(100))
    uf: Mapped[str | None] = mapped_column(String(2))
    ibge_code: Mapped[str | None] = mapped_column(String(7))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(200))
    cnae_main: Mapped[str | None] = mapped_column(String(10))
    cnaes_secondary: Mapped[list] = mapped_column(default=list)
    tax_regime: Mapped[str | None] = mapped_column(String(30))
    regime_details: Mapped[str | None] = mapped_column(Text)  # enquadramento (anexo, fator R...) informado pelo contador
    op_simples_nacional: Mapped[int | None] = mapped_column(Integer)  # DPS: opSimpNac (1, 2 ou 3)
    reg_ap_trib_sn: Mapped[int | None] = mapped_column(Integer)  # DPS: regApTribSN (quando opSimpNac = 3)
    reg_esp_trib: Mapped[int] = mapped_column(Integer, default=0)  # DPS: regEspTrib
    opening_date: Mapped[date | None] = mapped_column(Date)
    legal_representative: Mapped[str | None] = mapped_column(String(150))
    legal_representative_cpf: Mapped[str | None] = mapped_column(String(11))
    accountant_name: Mapped[str | None] = mapped_column(String(150))
    accountant_crc: Mapped[str | None] = mapped_column(String(30))
    accountant_email: Mapped[str | None] = mapped_column(String(200))
    accountant_phone: Mapped[str | None] = mapped_column(String(20))
    accountant_document: Mapped[str | None] = mapped_column(String(14))
    has_employees: Mapped[bool] = mapped_column(Boolean, default=False)
    nfse_provider: Mapped[str] = mapped_column(String(30), default="nacional")
    nfse_environment: Mapped[str] = mapped_column(String(20), default="homologacao")  # homologacao | producao
    dps_series: Mapped[str] = mapped_column(String(5), default="1")
    next_dps_number: Mapped[int] = mapped_column(BigInteger, default=1)
    layout_version: Mapped[str] = mapped_column(String(5), default="1.01")
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validated_at: Mapped[datetime | None]
    validated_by_name: Mapped[str | None] = mapped_column(String(150))
    validation_notes: Mapped[str | None] = mapped_column(Text)
    production_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class DigitalCertificate(UUIDPk, Base):
    __tablename__ = "digital_certificates"
    alias: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(5), default="A1")
    subject: Mapped[str] = mapped_column(String(500))
    issuer: Mapped[str] = mapped_column(String(500))
    serial_number: Mapped[str] = mapped_column(String(80))
    document: Mapped[str | None] = mapped_column(String(14))  # CNPJ/CPF extraído do certificado
    valid_from: Mapped[datetime]
    valid_to: Mapped[datetime]
    thumbprint_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    pfx_enc: Mapped[str] = mapped_column(Text)
    password_enc: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TaxRate(UUIDPk, Timestamps, Base):
    """Regra tributária parametrizável com vigência. Usada apenas para ESTIMATIVAS."""

    __tablename__ = "tax_rates"
    __table_args__ = (CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity"),)
    tax: Mapped[str] = mapped_column(String(20), index=True)
    regime: Mapped[str] = mapped_column(String(30))  # regime ao qual se aplica
    description: Mapped[str | None] = mapped_column(String(300))
    rate: Mapped[Decimal] = mapped_column(Numeric(7, 4))  # percentual
    base: Mapped[str] = mapped_column(String(30), default="receita_bruta")  # receita_bruta | presuncao
    presumption_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    tax_service_code_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tax_service_codes.id", ondelete="SET NULL")
    )
    municipality_ibge: Mapped[str | None] = mapped_column(String(7))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    due_day: Mapped[int | None] = mapped_column(Integer)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validated_by: Mapped[str | None] = mapped_column(String(150))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TaxAssessment(UUIDPk, Timestamps, Base):
    """Apuração (estimada ou validada) de um tributo em uma competência."""

    __tablename__ = "tax_assessments"
    __table_args__ = (UniqueConstraint("period", "tax", name="uq_tax_assessments_period_tax"),)
    period: Mapped[str] = mapped_column(String(7), index=True)  # AAAA-MM
    tax: Mapped[str] = mapped_column(String(20))
    regime: Mapped[str | None] = mapped_column(String(30))
    base_amount: Mapped[Decimal]
    rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    estimated_amount: Mapped[Decimal]
    final_amount: Mapped[Decimal | None]
    status: Mapped[str] = mapped_column(String(20), default="estimado")  # estimado | validado | pago | cancelado
    due_date: Mapped[date | None] = mapped_column(Date)
    paid_at: Mapped[date | None] = mapped_column(Date)
    paid_amount: Mapped[Decimal | None]
    payable_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts_payable.id", ondelete="SET NULL"))
    calculation_notes: Mapped[str | None] = mapped_column(Text)
    validated_by: Mapped[str | None] = mapped_column(String(150))
    notes: Mapped[str | None] = mapped_column(Text)


class FiscalInvoice(UUIDPk, Timestamps, Base):
    __tablename__ = "fiscal_invoices"
    __table_args__ = (
        CheckConstraint("gross_amount > 0", name="gross_positive"),
        Index(
            "uq_fiscal_invoices_source_active",
            "source_key",
            unique=True,
            postgresql_where=text(
                "source_key IS NOT NULL AND status IN ('rascunho','aguardando_transmissao','transmitindo','autorizada')"
            ),
        ),
        UniqueConstraint("environment", "dps_series", "dps_number", name="uq_fiscal_invoices_dps"),
    )
    status: Mapped[str] = mapped_column(String(30), default="rascunho", index=True)
    environment: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(30), default="nacional")
    dps_series: Mapped[str | None] = mapped_column(String(5))
    dps_number: Mapped[int | None] = mapped_column(BigInteger)
    dps_id: Mapped[str | None] = mapped_column(String(45), unique=True)
    access_key: Mapped[str | None] = mapped_column(String(50), unique=True)
    nfse_number: Mapped[str | None] = mapped_column(String(20), index=True)
    verification_code: Mapped[str | None] = mapped_column(String(60))
    protocol: Mapped[str | None] = mapped_column(String(60))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), index=True)
    taker_document: Mapped[str | None] = mapped_column(String(14))
    taker_name: Mapped[str | None] = mapped_column(String(150))
    taker_email: Mapped[str | None] = mapped_column(String(200))
    taker_phone: Mapped[str | None] = mapped_column(String(20))
    taker_address: Mapped[dict | None]
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("services.id", ondelete="SET NULL"))
    tax_service_code_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tax_service_codes.id", ondelete="SET NULL")
    )
    national_code: Mapped[str | None] = mapped_column(String(6))
    municipal_code: Mapped[str | None] = mapped_column(String(20))
    nbs_code: Mapped[str | None] = mapped_column(String(9))
    description: Mapped[str] = mapped_column(Text)
    competence_date: Mapped[date] = mapped_column(Date, index=True)
    gross_amount: Mapped[Decimal]
    unconditional_discount: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    conditional_discount: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    deductions: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    net_amount: Mapped[Decimal]
    incidence_ibge: Mapped[str | None] = mapped_column(String(7))
    iss_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    iss_amount: Mapped[Decimal | None]
    iss_withheld: Mapped[bool] = mapped_column(Boolean, default=False)
    retentions: Mapped[dict] = mapped_column(default=dict)
    tax_info: Mapped[dict] = mapped_column(default=dict)
    additional_info: Mapped[str | None] = mapped_column(Text)
    receivable_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts_receivable.id", ondelete="SET NULL"), index=True
    )
    package_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("packages.id", ondelete="SET NULL"))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"))
    source_key: Mapped[str | None] = mapped_column(String(80), index=True)
    replaces_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fiscal_invoices.id", ondelete="SET NULL"))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fiscal_invoices.id", ondelete="SET NULL"))
    substitution_reason_code: Mapped[str | None] = mapped_column(String(2))
    substitution_reason: Mapped[str | None] = mapped_column(String(255))
    cancel_reason_code: Mapped[str | None] = mapped_column(String(2))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    issued_at: Mapped[datetime | None]
    authorized_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    dps_xml: Mapped[str | None] = mapped_column(Text)
    nfse_xml: Mapped[str | None] = mapped_column(Text)
    danfse_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stored_files.id", ondelete="SET NULL", use_alter=True)
    )
    query_url: Mapped[str | None] = mapped_column(String(300))
    last_error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    events: Mapped[list["FiscalInvoiceEvent"]] = relationship(
        back_populates="invoice", order_by="FiscalInvoiceEvent.created_at", lazy="selectin"
    )


class FiscalInvoiceEvent(UUIDPk, Base):
    __tablename__ = "fiscal_invoice_events"
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fiscal_invoices.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    event_code: Mapped[str | None] = mapped_column(String(10))
    http_status: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None]
    xml: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    invoice: Mapped[FiscalInvoice] = relationship(back_populates="events")


class FiscalDocument(UUIDPk, Timestamps, Base):
    """Documentos fiscais recebidos (serviços tomados, notas de compra) e outros comprovantes."""

    __tablename__ = "fiscal_documents"
    direction: Mapped[str] = mapped_column(String(20), default="recebido")  # recebido | emitido_externo
    doc_type: Mapped[str] = mapped_column(String(20))  # nfse | nfe | nfce | cte | recibo | fatura | outro
    number: Mapped[str | None] = mapped_column(String(30))
    series: Mapped[str | None] = mapped_column(String(10))
    access_key: Mapped[str | None] = mapped_column(String(60))
    issuer_name: Mapped[str] = mapped_column(String(150))
    issuer_document: Mapped[str | None] = mapped_column(String(14))
    issue_date: Mapped[date] = mapped_column(Date, index=True)
    competence_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal]
    retentions: Mapped[dict] = mapped_column(default=dict)
    retention_total: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    service_taken: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    xml: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class TaxObligationTemplate(UUIDPk, Timestamps, Base):
    """Modelo do calendário de obrigações. Nada vem ativo por padrão: o contador define o que se aplica."""

    __tablename__ = "tax_obligation_templates"
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str] = mapped_column(String(30))
    frequency: Mapped[str] = mapped_column(String(10))  # mensal | anual
    due_day: Mapped[int] = mapped_column(Integer)
    due_month: Mapped[int | None] = mapped_column(Integer)
    reference_offset_months: Mapped[int] = mapped_column(Integer, default=1)
    applicable_regimes: Mapped[list] = mapped_column(default=list)
    requires_employees: Mapped[bool] = mapped_column(Boolean, default=False)
    responsible: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


class TaxObligation(UUIDPk, Timestamps, Base):
    __tablename__ = "tax_obligations"
    __table_args__ = (
        UniqueConstraint("template_id", "reference_period", name="uq_tax_obligations_template_period"),
        CheckConstraint(
            "status IN ('pendente','em_preparacao','enviado','concluido','atrasado','nao_aplicavel')", name="status"
        ),
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tax_obligation_templates.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str] = mapped_column(String(30))
    reference_period: Mapped[str] = mapped_column(String(7), index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    responsible: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="pendente", index=True)
    delivered_at: Mapped[date | None] = mapped_column(Date)
    receipt_number: Mapped[str | None] = mapped_column(String(80))
    related_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fiscal_documents.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AccountingExport(UUIDPk, Base):
    __tablename__ = "accounting_exports"
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    formats: Mapped[list] = mapped_column(default=list)
    contents: Mapped[dict] = mapped_column(default=dict)
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stored_files.id", ondelete="SET NULL", use_alter=True))
    status: Mapped[str] = mapped_column(String(20), default="gerado")  # gerado | disponibilizado | enviado | baixado
    sent_at: Mapped[datetime | None]
    sent_to: Mapped[str | None] = mapped_column(String(200))
    sent_method: Mapped[str | None] = mapped_column(String(60))
    downloaded_at: Mapped[datetime | None]
    downloaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
