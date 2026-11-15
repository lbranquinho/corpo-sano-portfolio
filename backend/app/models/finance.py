from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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
from app.models.customer import Customer

ZERO = Decimal("0.00")


class PaymentMethod(UUIDPk, Base):
    __tablename__ = "payment_methods"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    fee_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=ZERO)
    settlement_days: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class FinancialAccount(UUIDPk, Timestamps, Base):
    __tablename__ = "financial_accounts"
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="banco")  # caixa | banco | carteira | outro
    bank_name: Mapped[str | None] = mapped_column(String(80))
    agency: Mapped[str | None] = mapped_column(String(20))
    account_number: Mapped[str | None] = mapped_column(String(30))
    opening_balance: Mapped[Decimal] = mapped_column(default=ZERO)
    opening_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class FinancialCategory(UUIDPk, Base):
    __tablename__ = "financial_categories"
    __table_args__ = (UniqueConstraint("name", "kind", name="uq_financial_categories_name_kind"),)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))  # receita | despesa
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CostCenter(UUIDPk, Base):
    __tablename__ = "cost_centers"
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AccountsReceivable(UUIDPk, Timestamps, Base):
    """Conta a receber. Gerada na conclusão de atendimento avulso, na venda de pacote ou manualmente.
    Um agendamento NÃO gera receita: só o atendimento concluído/venda efetiva."""

    __tablename__ = "accounts_receivable"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("discount >= 0 AND discount < amount", name="discount_range"),
        CheckConstraint("amount_paid >= 0 AND amount_paid <= amount - discount", name="paid_range"),
        CheckConstraint("status IN ('aberto','parcial','pago','cancelado')", name="status"),
        Index(
            "uq_accounts_receivable_appointment",
            "appointment_id",
            unique=True,
            postgresql_where=text("appointment_id IS NOT NULL AND status <> 'cancelado'"),
        ),
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), index=True)
    description: Mapped[str] = mapped_column(String(300))
    origin: Mapped[str] = mapped_column(String(20))  # atendimento | pacote | avulso
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"))
    package_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("packages.id", ondelete="SET NULL"), index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_categories.id", ondelete="SET NULL"))
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_centers.id", ondelete="SET NULL"))
    competence_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal]
    discount: Mapped[Decimal] = mapped_column(default=ZERO)
    amount_paid: Mapped[Decimal] = mapped_column(default=ZERO)
    status: Mapped[str] = mapped_column(String(20), default="aberto", index=True)
    installment_number: Mapped[int] = mapped_column(Integer, default=1)
    installment_count: Mapped[int] = mapped_column(Integer, default=1)
    group_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    customer: Mapped[Customer | None] = relationship(lazy="joined")

    @property
    def net_amount(self) -> Decimal:
        return self.amount - self.discount

    @property
    def balance(self) -> Decimal:
        return self.amount - self.discount - self.amount_paid


class Expense(UUIDPk, Timestamps, Base):
    __tablename__ = "expenses"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)
    description: Mapped[str] = mapped_column(String(300))
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_categories.id", ondelete="RESTRICT"))
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_centers.id", ondelete="SET NULL"))
    supplier_name: Mapped[str | None] = mapped_column(String(150))
    supplier_document: Mapped[str | None] = mapped_column(String(14))
    competence_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal]
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_methods.id", ondelete="SET NULL"))
    fiscal_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fiscal_documents.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AccountsPayable(UUIDPk, Timestamps, Base):
    __tablename__ = "accounts_payable"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("amount_paid >= 0 AND amount_paid <= amount", name="paid_range"),
        CheckConstraint("status IN ('aberto','parcial','pago','cancelado')", name="status"),
    )
    expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(String(300))
    supplier_name: Mapped[str | None] = mapped_column(String(150))
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_categories.id", ondelete="SET NULL"))
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_centers.id", ondelete="SET NULL"))
    competence_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal]
    amount_paid: Mapped[Decimal] = mapped_column(default=ZERO)
    status: Mapped[str] = mapped_column(String(20), default="aberto", index=True)
    installment_number: Mapped[int] = mapped_column(Integer, default=1)
    installment_count: Mapped[int] = mapped_column(Integer, default=1)
    group_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    @property
    def balance(self) -> Decimal:
        return self.amount - self.amount_paid


class FinancialTransaction(UUIDPk, Base):
    """Movimento de caixa efetivo (dinheiro que entrou ou saiu). Estornos geram movimento inverso."""

    __tablename__ = "financial_transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("kind IN ('entrada','saida')", name="kind"),
    )
    kind: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal]
    transaction_date: Mapped[date] = mapped_column(Date, index=True)
    competence_date: Mapped[date | None] = mapped_column(Date)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_accounts.id", ondelete="RESTRICT"), index=True)
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_methods.id", ondelete="SET NULL"))
    receivable_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts_receivable.id", ondelete="RESTRICT"), index=True
    )
    payable_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts_payable.id", ondelete="RESTRICT"), index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_categories.id", ondelete="SET NULL"))
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_centers.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(String(300))
    document_ref: Mapped[str | None] = mapped_column(String(100))
    is_reversal: Mapped[bool] = mapped_column(Boolean, default=False)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("financial_transactions.id", ondelete="RESTRICT"), unique=True
    )
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    reconciled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reconciled_at: Mapped[datetime | None]
    reconciled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reconciliation_ref: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CashClosing(UUIDPk, Base):
    __tablename__ = "cash_closings"
    __table_args__ = (UniqueConstraint("account_id", "closing_date", name="uq_cash_closings_account_date"),)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_accounts.id", ondelete="RESTRICT"))
    closing_date: Mapped[date] = mapped_column(Date, index=True)
    opening_balance: Mapped[Decimal]
    total_in: Mapped[Decimal]
    total_out: Mapped[Decimal]
    expected_balance: Mapped[Decimal]
    counted_balance: Mapped[Decimal | None]
    difference: Mapped[Decimal | None]
    notes: Mapped[str | None] = mapped_column(Text)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    closed_at: Mapped[datetime] = mapped_column(server_default=func.now())
