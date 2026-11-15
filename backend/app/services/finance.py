"""Regras financeiras.

Distinções obrigatórias:
- Receita CONTRATADA: contas a receber geradas (competência) — atendimento concluído, pacote vendido, avulso.
- Receita FATURADA: NFS-e autorizadas (competência).
- Receita RECEBIDA: entradas efetivas de caixa (data do pagamento), líquidas de estornos.
- Receita PENDENTE: saldo em aberto das contas a receber.
Agendamento nunca é receita.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.core.settings_store import get_setting
from app.core.utils import local_today, money, split_installments, to_local
from app.models.finance import (
    AccountsPayable,
    AccountsReceivable,
    CashClosing,
    FinancialAccount,
    FinancialCategory,
    FinancialTransaction,
    PaymentMethod,
)
from app.models.schedule import Appointment

ZERO = Decimal("0.00")


def category_id(db: Session, name: str, kind: str) -> uuid.UUID | None:
    return db.scalar(select(FinancialCategory.id).where(FinancialCategory.name == name, FinancialCategory.kind == kind))


def default_account(db: Session) -> FinancialAccount:
    acc_id = get_setting(db, "finance.default_account_id")
    acc = db.get(FinancialAccount, uuid.UUID(acc_id)) if acc_id else None
    if acc is None:
        acc = db.scalar(select(FinancialAccount).where(FinancialAccount.is_active.is_(True)).order_by(FinancialAccount.created_at))
    if acc is None:
        raise AppError("Cadastre uma conta financeira (Configurações > Financeiro).")
    return acc


def ensure_day_open(db: Session, account_id: uuid.UUID, day: date) -> None:
    closed = db.scalar(select(CashClosing.id).where(CashClosing.account_id == account_id, CashClosing.closing_date >= day))
    if closed:
        raise AppError(f"O caixa desta conta já foi fechado em {day:%d/%m/%Y} ou depois. Lançamentos retroativos não são permitidos.")


def refresh_receivable_status(r: AccountsReceivable) -> None:
    if r.status == "cancelado":
        return
    if r.amount_paid <= ZERO:
        r.status = "aberto"
    elif r.amount_paid < r.net_amount:
        r.status = "parcial"
    else:
        r.status = "pago"


def refresh_payable_status(p: AccountsPayable) -> None:
    if p.status == "cancelado":
        return
    if p.amount_paid <= ZERO:
        p.status = "aberto"
    elif p.amount_paid < p.amount:
        p.status = "parcial"
    else:
        p.status = "pago"


def create_receivables(
    db: Session, *, customer_id: uuid.UUID | None, description: str, origin: str, total: Decimal,
    discount: Decimal = ZERO, competence_date: date, first_due: date, installments: int = 1,
    appointment_id: uuid.UUID | None = None, package_id: uuid.UUID | None = None,
    category_id_: uuid.UUID | None = None, cost_center_id: uuid.UUID | None = None, notes: str | None = None,
    user_id: uuid.UUID | None = None,
) -> list[AccountsReceivable]:
    from app.core.utils import add_months

    total, discount = money(total), money(discount)
    if total <= ZERO:
        raise AppError("O valor deve ser maior que zero.")
    if discount < ZERO or discount >= total:
        raise AppError("Desconto inválido.")
    if installments < 1 or installments > 24:
        raise AppError("Parcelamento deve ter entre 1 e 24 parcelas.")
    group = uuid.uuid4() if installments > 1 else None
    amounts = split_installments(total, installments)
    discounts = split_installments(discount, installments) if discount > ZERO else [ZERO] * installments
    if category_id_ is None:
        category_id_ = category_id(db, "Pacotes" if origin == "pacote" else "Atendimentos", "receita")
    out = []
    for i, (amt, disc) in enumerate(zip(amounts, discounts), start=1):
        r = AccountsReceivable(
            customer_id=customer_id,
            description=description if installments == 1 else f"{description} ({i}/{installments})",
            origin=origin, appointment_id=appointment_id, package_id=package_id, category_id=category_id_,
            cost_center_id=cost_center_id, competence_date=competence_date, due_date=add_months(first_due, i - 1),
            amount=amt, discount=disc, amount_paid=ZERO, status="aberto", installment_number=i,
            installment_count=installments, group_id=group, notes=notes, created_by=user_id,
        )
        db.add(r)
        out.append(r)
    db.flush()
    return out


def receivable_for_appointment(db: Session, appt: Appointment, user_id: uuid.UUID | None) -> AccountsReceivable | None:
    """Gera a conta a receber do atendimento avulso concluído (nunca para atendimentos de pacote)."""
    if appt.package_id or appt.net_price <= ZERO:
        return None
    existing = db.scalar(select(AccountsReceivable).where(
        AccountsReceivable.appointment_id == appt.id, AccountsReceivable.status != "cancelado"))
    if existing:
        return existing
    day = to_local(appt.start_at).date()
    return create_receivables(
        db, customer_id=appt.customer_id, description=f"{appt.service.name} — {day:%d/%m/%Y}", origin="atendimento",
        total=appt.price, discount=appt.discount, competence_date=day, first_due=day, appointment_id=appt.id,
        user_id=user_id,
    )[0]


def register_receipt(
    db: Session, receivable: AccountsReceivable, *, amount: Decimal, payment_date: date,
    payment_method_id: uuid.UUID | None, account_id: uuid.UUID | None, user_id: uuid.UUID | None,
    document_ref: str | None = None, notes: str | None = None,
) -> FinancialTransaction:
    db.refresh(receivable, with_for_update={"of": AccountsReceivable})
    amount = money(amount)
    if receivable.status == "cancelado":
        raise AppError("Conta a receber cancelada.")
    if amount <= ZERO:
        raise AppError("Informe um valor maior que zero.")
    if amount > receivable.balance:
        raise AppError(f"Valor maior que o saldo em aberto (R$ {receivable.balance:.2f}).")
    if payment_date > local_today():
        raise AppError("A data do pagamento não pode ser futura.")
    if payment_method_id and db.get(PaymentMethod, payment_method_id) is None:
        raise NotFound("Forma de pagamento")
    account = db.get(FinancialAccount, account_id) if account_id else default_account(db)
    if account is None or not account.is_active:
        raise AppError("Conta financeira inválida ou inativa.")
    ensure_day_open(db, account.id, payment_date)
    tx = FinancialTransaction(
        kind="entrada", amount=amount, transaction_date=payment_date, competence_date=receivable.competence_date,
        account_id=account.id, payment_method_id=payment_method_id, receivable_id=receivable.id,
        category_id=receivable.category_id, cost_center_id=receivable.cost_center_id,
        description=f"Recebimento: {receivable.description}", document_ref=document_ref, notes=notes, created_by=user_id,
    )
    db.add(tx)
    receivable.amount_paid = money(receivable.amount_paid + amount)
    refresh_receivable_status(receivable)
    db.flush()
    return tx


def register_payment(
    db: Session, payable: AccountsPayable, *, amount: Decimal, payment_date: date,
    payment_method_id: uuid.UUID | None, account_id: uuid.UUID | None, user_id: uuid.UUID | None,
    document_ref: str | None = None, notes: str | None = None,
) -> FinancialTransaction:
    db.refresh(payable, with_for_update={"of": AccountsPayable})
    amount = money(amount)
    if payable.status == "cancelado":
        raise AppError("Conta a pagar cancelada.")
    if amount <= ZERO or amount > payable.balance:
        raise AppError(f"Valor inválido. Saldo em aberto: R$ {payable.balance:.2f}.")
    if payment_date > local_today():
        raise AppError("A data do pagamento não pode ser futura.")
    account = db.get(FinancialAccount, account_id) if account_id else default_account(db)
    if account is None or not account.is_active:
        raise AppError("Conta financeira inválida ou inativa.")
    ensure_day_open(db, account.id, payment_date)
    tx = FinancialTransaction(
        kind="saida", amount=amount, transaction_date=payment_date, competence_date=payable.competence_date,
        account_id=account.id, payment_method_id=payment_method_id, payable_id=payable.id,
        category_id=payable.category_id, cost_center_id=payable.cost_center_id,
        description=f"Pagamento: {payable.description}", document_ref=document_ref, notes=notes, created_by=user_id,
    )
    db.add(tx)
    payable.amount_paid = money(payable.amount_paid + amount)
    refresh_payable_status(payable)
    db.flush()
    return tx


def reverse_transaction(db: Session, tx: FinancialTransaction, *, reason: str, user_id: uuid.UUID | None) -> FinancialTransaction:
    """Estorno: cria movimento inverso vinculado e reabre o saldo do título."""
    if tx.is_reversal:
        raise AppError("Não é possível estornar um estorno.")
    if tx.reversed:
        raise AppError("Lançamento já estornado.")
    today = local_today()
    ensure_day_open(db, tx.account_id, today)
    rev = FinancialTransaction(
        kind="saida" if tx.kind == "entrada" else "entrada", amount=tx.amount, transaction_date=today,
        competence_date=tx.competence_date, account_id=tx.account_id, payment_method_id=tx.payment_method_id,
        receivable_id=tx.receivable_id, payable_id=tx.payable_id, category_id=tx.category_id,
        cost_center_id=tx.cost_center_id, description=f"Estorno: {tx.description}", is_reversal=True,
        reversal_of_id=tx.id, notes=reason, created_by=user_id,
    )
    db.add(rev)
    tx.reversed = True
    if tx.receivable_id:
        r = db.get(AccountsReceivable, tx.receivable_id)
        r.amount_paid = money(r.amount_paid - tx.amount)
        refresh_receivable_status(r)
    if tx.payable_id:
        p = db.get(AccountsPayable, tx.payable_id)
        p.amount_paid = money(p.amount_paid - tx.amount)
        refresh_payable_status(p)
    db.flush()
    return rev


def account_balance(db: Session, account: FinancialAccount, until: date | None = None) -> Decimal:
    stmt_in = select(func.coalesce(func.sum(FinancialTransaction.amount), 0)).where(
        FinancialTransaction.account_id == account.id, FinancialTransaction.kind == "entrada")
    stmt_out = select(func.coalesce(func.sum(FinancialTransaction.amount), 0)).where(
        FinancialTransaction.account_id == account.id, FinancialTransaction.kind == "saida")
    if until:
        stmt_in = stmt_in.where(FinancialTransaction.transaction_date <= until)
        stmt_out = stmt_out.where(FinancialTransaction.transaction_date <= until)
    return money(account.opening_balance + Decimal(db.scalar(stmt_in)) - Decimal(db.scalar(stmt_out)))


def day_totals(db: Session, account_id: uuid.UUID, day: date) -> tuple[Decimal, Decimal]:
    def total(kind: str) -> Decimal:
        return Decimal(db.scalar(select(func.coalesce(func.sum(FinancialTransaction.amount), 0)).where(
            FinancialTransaction.account_id == account_id, FinancialTransaction.kind == kind,
            FinancialTransaction.transaction_date == day)))
    return money(total("entrada")), money(total("saida"))


def revenue_summary(db: Session, start: date, end: date) -> dict[str, Decimal]:
    from app.models.fiscal import FiscalInvoice

    contracted = db.scalar(select(func.coalesce(func.sum(AccountsReceivable.amount - AccountsReceivable.discount), 0)).where(
        AccountsReceivable.status != "cancelado", AccountsReceivable.competence_date.between(start, end)))
    invoiced = db.scalar(select(func.coalesce(func.sum(FiscalInvoice.net_amount), 0)).where(
        FiscalInvoice.status == "autorizada", FiscalInvoice.competence_date.between(start, end)))
    rec_in = db.scalar(select(func.coalesce(func.sum(FinancialTransaction.amount), 0)).where(
        FinancialTransaction.receivable_id.is_not(None), FinancialTransaction.kind == "entrada",
        FinancialTransaction.transaction_date.between(start, end)))
    rec_rev = db.scalar(select(func.coalesce(func.sum(FinancialTransaction.amount), 0)).where(
        FinancialTransaction.receivable_id.is_not(None), FinancialTransaction.kind == "saida",
        FinancialTransaction.is_reversal.is_(True), FinancialTransaction.transaction_date.between(start, end)))
    pending = db.scalar(select(func.coalesce(func.sum(AccountsReceivable.amount - AccountsReceivable.discount - AccountsReceivable.amount_paid), 0)).where(
        AccountsReceivable.status.in_(("aberto", "parcial")), AccountsReceivable.competence_date.between(start, end)))
    overdue = db.scalar(select(func.coalesce(func.sum(AccountsReceivable.amount - AccountsReceivable.discount - AccountsReceivable.amount_paid), 0)).where(
        AccountsReceivable.status.in_(("aberto", "parcial")), AccountsReceivable.due_date < local_today()))
    pay_out = db.scalar(select(func.coalesce(func.sum(FinancialTransaction.amount), 0)).where(
        FinancialTransaction.payable_id.is_not(None), FinancialTransaction.kind == "saida",
        FinancialTransaction.transaction_date.between(start, end)))
    pay_rev = db.scalar(select(func.coalesce(func.sum(FinancialTransaction.amount), 0)).where(
        FinancialTransaction.payable_id.is_not(None), FinancialTransaction.kind == "entrada",
        FinancialTransaction.is_reversal.is_(True), FinancialTransaction.transaction_date.between(start, end)))
    expenses_comp = db.scalar(select(func.coalesce(func.sum(AccountsPayable.amount), 0)).where(
        AccountsPayable.status != "cancelado", AccountsPayable.competence_date.between(start, end)))
    received = money(Decimal(rec_in) - Decimal(rec_rev))
    paid = money(Decimal(pay_out) - Decimal(pay_rev))
    return {
        "contracted": money(contracted),
        "invoiced": money(invoiced),
        "received": received,
        "pending": money(pending),
        "overdue": money(overdue),
        "expenses_paid": paid,
        "expenses_competence": money(expenses_comp),
        "operating_result_cash": money(received - paid),
        "operating_result_competence": money(Decimal(contracted) - Decimal(expenses_comp)),
        "not_invoiced": money(max(Decimal(contracted) - Decimal(invoiced), ZERO)),
    }


def overdue_condition():
    return and_(AccountsReceivable.status.in_(("aberto", "parcial")), AccountsReceivable.due_date < local_today())
