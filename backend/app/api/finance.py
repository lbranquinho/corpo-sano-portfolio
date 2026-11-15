from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import require, require_any
from app.core.errors import AppError, NotFound
from app.core.storage import save_file
from app.core.utils import local_today, money, only_digits, split_installments, utcnow
from app.models.auth import User
from app.models.customer import Customer
from app.models.finance import (
    AccountsPayable,
    AccountsReceivable,
    CashClosing,
    Expense,
    FinancialAccount,
    FinancialTransaction,
)
from app.models.fiscal import FiscalInvoice
from app.schemas.common import ORM, Money, Page, StrippedModel
from app.services import finance as svc

router = APIRouter(prefix="/finance", tags=["Financeiro"])


class ReceivableIn(StrippedModel):
    customer_id: uuid.UUID | None = None
    description: str = Field(min_length=3, max_length=300)
    total: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    competence_date: date
    first_due_date: date
    installments: int = Field(default=1, ge=1, le=24)
    category_id: uuid.UUID | None = None
    cost_center_id: uuid.UUID | None = None
    notes: str | None = None


class ReceivableOut(ORM):
    id: uuid.UUID
    customer_id: uuid.UUID | None
    customer_name: str | None = None
    description: str
    origin: str
    appointment_id: uuid.UUID | None
    package_id: uuid.UUID | None
    category_id: uuid.UUID | None
    cost_center_id: uuid.UUID | None
    competence_date: date
    due_date: date
    amount: Money
    discount: Money
    amount_paid: Money
    net_amount: Money
    balance: Money
    status: str
    overdue: bool = False
    installment_number: int
    installment_count: int
    notes: str | None
    invoice_status: str | None = None
    invoice_number: str | None = None


class PaymentIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_date: date
    payment_method_id: uuid.UUID
    account_id: uuid.UUID | None = None
    document_ref: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=500)


class CancelIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


class ExpenseIn(StrippedModel):
    description: str = Field(min_length=3, max_length=300)
    category_id: uuid.UUID
    cost_center_id: uuid.UUID | None = None
    supplier_name: str | None = Field(default=None, max_length=150)
    supplier_document: str | None = None
    competence_date: date
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    first_due_date: date
    installments: int = Field(default=1, ge=1, le=24)
    payment_method_id: uuid.UUID | None = None
    paid_now: bool = False
    account_id: uuid.UUID | None = None
    notes: str | None = None


class PayableOut(ORM):
    id: uuid.UUID
    expense_id: uuid.UUID | None
    description: str
    supplier_name: str | None
    category_id: uuid.UUID | None
    cost_center_id: uuid.UUID | None
    competence_date: date
    due_date: date
    amount: Money
    amount_paid: Money
    balance: Money
    status: str
    overdue: bool = False
    installment_number: int
    installment_count: int
    notes: str | None


class TransactionOut(ORM):
    id: uuid.UUID
    kind: str
    amount: Money
    transaction_date: date
    competence_date: date | None
    account_id: uuid.UUID
    payment_method_id: uuid.UUID | None
    receivable_id: uuid.UUID | None
    payable_id: uuid.UUID | None
    category_id: uuid.UUID | None
    cost_center_id: uuid.UUID | None
    description: str
    document_ref: str | None
    is_reversal: bool
    reversed: bool
    reconciled: bool
    reconciliation_ref: str | None
    created_at: datetime


class ReconcileIn(BaseModel):
    transaction_ids: list[uuid.UUID]
    reconciled: bool = True
    reference: str | None = Field(default=None, max_length=120)


class ClosingIn(BaseModel):
    account_id: uuid.UUID
    closing_date: date
    counted_balance: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    notes: str | None = Field(default=None, max_length=1000)


def _rec_out(db: Session, r: AccountsReceivable) -> ReceivableOut:
    o = ReceivableOut.model_validate(r)
    o.customer_name = r.customer.full_name if r.customer else None
    o.overdue = r.status in ("aberto", "parcial") and r.due_date < local_today()
    inv = db.scalar(select(FiscalInvoice).where(FiscalInvoice.receivable_id == r.id).order_by(FiscalInvoice.created_at.desc()).limit(1))
    if inv:
        o.invoice_status, o.invoice_number = inv.status, inv.nfse_number
    return o


def _pay_out(p: AccountsPayable) -> PayableOut:
    o = PayableOut.model_validate(p)
    o.overdue = p.status in ("aberto", "parcial") and p.due_date < local_today()
    return o


# ---------------------------------------------------------------- Resumo
@router.get("/summary")
def summary(start: date, end: date, db: Session = Depends(get_db), user: User = Depends(require("finance.read"))):
    data = svc.revenue_summary(db, start, end)
    accounts = db.scalars(select(FinancialAccount).where(FinancialAccount.is_active.is_(True))).all()
    return {
        **{k: float(v) for k, v in data.items()},
        "accounts": [{"id": str(a.id), "name": a.name, "balance": float(svc.account_balance(db, a))} for a in accounts],
        "notes": {
            "contracted": "Contas a receber geradas no período (competência): atendimentos concluídos, pacotes e avulsos.",
            "invoiced": "NFS-e autorizadas no período (competência).",
            "received": "Dinheiro efetivamente recebido no período (data do pagamento), líquido de estornos.",
            "pending": "Saldo em aberto das contas com competência no período.",
        },
    }


# ---------------------------------------------------------------- Contas a receber
@router.get("/receivables", response_model=Page[ReceivableOut])
def list_receivables(
    status: str | None = None, customer_id: uuid.UUID | None = None, overdue: bool = False,
    due_from: date | None = None, due_to: date | None = None, q: str | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, le=200),
    db: Session = Depends(get_db), user: User = Depends(require_any("finance.read", "finance.payments")),
):
    stmt = select(AccountsReceivable).outerjoin(Customer, Customer.id == AccountsReceivable.customer_id)
    if status:
        stmt = stmt.where(AccountsReceivable.status.in_(status.split(",")))
    if customer_id:
        stmt = stmt.where(AccountsReceivable.customer_id == customer_id)
    if overdue:
        stmt = stmt.where(svc.overdue_condition())
    if due_from:
        stmt = stmt.where(AccountsReceivable.due_date >= due_from)
    if due_to:
        stmt = stmt.where(AccountsReceivable.due_date <= due_to)
    if q:
        stmt = stmt.where(AccountsReceivable.description.ilike(f"%{q}%") | Customer.full_name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AccountsReceivable.due_date.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[_rec_out(db, r) for r in rows], total=total, page=page, page_size=page_size)


@router.post("/receivables", status_code=201)
def create_receivable(data: ReceivableIn, db: Session = Depends(get_db), user: User = Depends(require("finance.write"))):
    if data.customer_id and db.get(Customer, data.customer_id) is None:
        raise NotFound("Cliente")
    rows = svc.create_receivables(
        db, customer_id=data.customer_id, description=data.description, origin="avulso", total=data.total,
        discount=data.discount, competence_date=data.competence_date, first_due=data.first_due_date,
        installments=data.installments, category_id_=data.category_id, cost_center_id=data.cost_center_id,
        notes=data.notes, user_id=user.id,
    )
    audit(db, "conta_receber_criada", user=user, entity="receivable", entity_id=rows[0].id,
          details={"valor": str(data.total), "parcelas": data.installments})
    db.commit()
    return {"message": f"{len(rows)} conta(s) a receber criada(s).", "ids": [str(r.id) for r in rows]}


@router.post("/receivables/{receivable_id}/payments", status_code=201)
def receive(receivable_id: uuid.UUID, data: PaymentIn, db: Session = Depends(get_db),
            user: User = Depends(require("finance.payments"))):
    r = db.get(AccountsReceivable, receivable_id)
    if r is None:
        raise NotFound("Conta a receber")
    tx = svc.register_receipt(db, r, amount=data.amount, payment_date=data.payment_date,
                              payment_method_id=data.payment_method_id, account_id=data.account_id, user_id=user.id,
                              document_ref=data.document_ref, notes=data.notes)
    audit(db, "pagamento_recebido", user=user, entity="receivable", entity_id=r.id,
          details={"valor": str(data.amount), "transacao": str(tx.id)})
    db.commit()
    return {"message": "Pagamento registrado." + (" Título quitado." if r.status == "pago" else ""),
            "transaction_id": str(tx.id), "status": r.status}


@router.post("/receivables/{receivable_id}/cancel")
def cancel_receivable(receivable_id: uuid.UUID, data: CancelIn, db: Session = Depends(get_db),
                      user: User = Depends(require("finance.reverse"))):
    r = db.get(AccountsReceivable, receivable_id)
    if r is None:
        raise NotFound("Conta a receber")
    if r.status == "cancelado":
        raise AppError("Já cancelada.")
    if r.amount_paid > 0:
        raise AppError("Há pagamentos registrados: estorne-os antes de cancelar.")
    if db.scalar(select(FiscalInvoice.id).where(FiscalInvoice.receivable_id == r.id, FiscalInvoice.status == "autorizada")):
        raise AppError("Existe NFS-e autorizada para esta conta: cancele a nota no módulo fiscal antes.")
    r.status, r.cancelled_at, r.cancel_reason = "cancelado", utcnow(), data.reason
    audit(db, "conta_receber_cancelada", user=user, entity="receivable", entity_id=r.id, details={"motivo": data.reason})
    db.commit()
    return {"message": "Conta a receber cancelada."}


# ---------------------------------------------------------------- Despesas e contas a pagar
@router.post("/expenses", status_code=201)
def create_expense(data: ExpenseIn, db: Session = Depends(get_db), user: User = Depends(require("finance.write"))):
    doc = only_digits(data.supplier_document) if data.supplier_document else None
    if doc and len(doc) not in (11, 14):
        raise AppError("Documento do fornecedor deve ser CPF ou CNPJ.")
    e = Expense(description=data.description, category_id=data.category_id, cost_center_id=data.cost_center_id,
                supplier_name=data.supplier_name, supplier_document=doc, competence_date=data.competence_date,
                amount=money(data.amount), payment_method_id=data.payment_method_id, notes=data.notes, created_by=user.id)
    db.add(e)
    db.flush()
    from app.core.utils import add_months

    group = uuid.uuid4() if data.installments > 1 else None
    payables = []
    for i, amt in enumerate(split_installments(data.amount, data.installments), start=1):
        p = AccountsPayable(
            expense_id=e.id, description=data.description if data.installments == 1 else f"{data.description} ({i}/{data.installments})",
            supplier_name=data.supplier_name, category_id=data.category_id, cost_center_id=data.cost_center_id,
            competence_date=data.competence_date, due_date=add_months(data.first_due_date, i - 1), amount=amt,
            installment_number=i, installment_count=data.installments, group_id=group, created_by=user.id,
        )
        db.add(p)
        payables.append(p)
    db.flush()
    if data.paid_now:
        if data.payment_method_id is None:
            raise AppError("Informe a forma de pagamento.")
        svc.register_payment(db, payables[0], amount=payables[0].amount, payment_date=min(data.first_due_date, local_today()),
                             payment_method_id=data.payment_method_id, account_id=data.account_id, user_id=user.id)
    audit(db, "despesa_criada", user=user, entity="expense", entity_id=e.id, details={"valor": str(data.amount)})
    db.commit()
    return {"message": "Despesa registrada.", "expense_id": str(e.id), "payables": [str(p.id) for p in payables]}


@router.get("/payables", response_model=Page[PayableOut])
def list_payables(status: str | None = None, overdue: bool = False, due_from: date | None = None,
                  due_to: date | None = None, q: str | None = None, page: int = Query(1, ge=1),
                  page_size: int = Query(50, le=200), db: Session = Depends(get_db),
                  user: User = Depends(require("finance.read"))):
    stmt = select(AccountsPayable)
    if status:
        stmt = stmt.where(AccountsPayable.status.in_(status.split(",")))
    if overdue:
        stmt = stmt.where(AccountsPayable.status.in_(("aberto", "parcial")), AccountsPayable.due_date < local_today())
    if due_from:
        stmt = stmt.where(AccountsPayable.due_date >= due_from)
    if due_to:
        stmt = stmt.where(AccountsPayable.due_date <= due_to)
    if q:
        stmt = stmt.where(AccountsPayable.description.ilike(f"%{q}%") | AccountsPayable.supplier_name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AccountsPayable.due_date).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[_pay_out(p) for p in rows], total=total, page=page, page_size=page_size)


@router.post("/payables/{payable_id}/payments", status_code=201)
def pay(payable_id: uuid.UUID, data: PaymentIn, db: Session = Depends(get_db), user: User = Depends(require("finance.write"))):
    p = db.get(AccountsPayable, payable_id)
    if p is None:
        raise NotFound("Conta a pagar")
    tx = svc.register_payment(db, p, amount=data.amount, payment_date=data.payment_date,
                              payment_method_id=data.payment_method_id, account_id=data.account_id, user_id=user.id,
                              document_ref=data.document_ref, notes=data.notes)
    audit(db, "conta_paga", user=user, entity="payable", entity_id=p.id, details={"valor": str(data.amount)})
    db.commit()
    return {"message": "Pagamento registrado.", "transaction_id": str(tx.id), "status": p.status}


@router.post("/payables/{payable_id}/cancel")
def cancel_payable(payable_id: uuid.UUID, data: CancelIn, db: Session = Depends(get_db),
                   user: User = Depends(require("finance.reverse"))):
    p = db.get(AccountsPayable, payable_id)
    if p is None:
        raise NotFound("Conta a pagar")
    if p.amount_paid > 0:
        raise AppError("Há pagamentos registrados: estorne-os antes de cancelar.")
    p.status, p.cancelled_at = "cancelado", utcnow()
    p.notes = ((p.notes or "") + f"\nCancelada: {data.reason}").strip()
    audit(db, "conta_pagar_cancelada", user=user, entity="payable", entity_id=p.id, details={"motivo": data.reason})
    db.commit()
    return {"message": "Conta a pagar cancelada."}


@router.post("/expenses/{expense_id}/files", status_code=201)
async def attach_expense_file(expense_id: uuid.UUID, file: UploadFile = File(...), description: str | None = Form(None),
                              db: Session = Depends(get_db), user: User = Depends(require("finance.write"))):
    if db.get(Expense, expense_id) is None:
        raise NotFound("Despesa")
    rec = save_file(db, await file.read(), filename=file.filename or "comprovante", content_type=file.content_type,
                    category="expense", user_id=user.id, description=description, expense_id=expense_id)
    audit(db, "comprovante_despesa_anexado", user=user, entity="expense", entity_id=expense_id)
    db.commit()
    return {"message": "Comprovante anexado.", "id": str(rec.id)}


# ---------------------------------------------------------------- Movimentações, estorno, conciliação
@router.get("/transactions", response_model=Page[TransactionOut])
def list_transactions(start: date, end: date, account_id: uuid.UUID | None = None, kind: str | None = None,
                      reconciled: bool | None = None, page: int = Query(1, ge=1), page_size: int = Query(100, le=500),
                      db: Session = Depends(get_db), user: User = Depends(require("finance.read"))):
    stmt = select(FinancialTransaction).where(FinancialTransaction.transaction_date.between(start, end))
    if account_id:
        stmt = stmt.where(FinancialTransaction.account_id == account_id)
    if kind:
        stmt = stmt.where(FinancialTransaction.kind == kind)
    if reconciled is not None:
        stmt = stmt.where(FinancialTransaction.reconciled.is_(reconciled))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(FinancialTransaction.transaction_date.desc(), FinancialTransaction.created_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[TransactionOut.model_validate(t) for t in rows], total=total, page=page, page_size=page_size)


@router.post("/transactions/{transaction_id}/reverse")
def reverse(transaction_id: uuid.UUID, data: CancelIn, db: Session = Depends(get_db),
            user: User = Depends(require("finance.reverse"))):
    tx = db.get(FinancialTransaction, transaction_id)
    if tx is None:
        raise NotFound("Lançamento")
    rev = svc.reverse_transaction(db, tx, reason=data.reason, user_id=user.id)
    audit(db, "lancamento_estornado", user=user, entity="transaction", entity_id=tx.id,
          details={"motivo": data.reason, "estorno": str(rev.id)})
    db.commit()
    return {"message": "Estorno registrado.", "reversal_id": str(rev.id)}


@router.post("/reconcile")
def reconcile(data: ReconcileIn, db: Session = Depends(get_db), user: User = Depends(require("finance.close"))):
    n = 0
    for tid in data.transaction_ids:
        tx = db.get(FinancialTransaction, tid)
        if tx is None:
            continue
        tx.reconciled = data.reconciled
        tx.reconciled_at = utcnow() if data.reconciled else None
        tx.reconciled_by = user.id if data.reconciled else None
        tx.reconciliation_ref = data.reference if data.reconciled else None
        n += 1
    audit(db, "conciliacao", user=user, details={"quantidade": n, "conciliado": data.reconciled, "ref": data.reference})
    db.commit()
    return {"message": f"{n} lançamento(s) atualizado(s)."}


@router.get("/reconciliation/overview")
def reconciliation_overview(start: date, end: date, db: Session = Depends(get_db), user: User = Depends(require("finance.read"))):
    """Cruza contas a receber × pagamentos × notas fiscais e aponta divergências."""
    rows = db.scalars(select(AccountsReceivable).where(AccountsReceivable.competence_date.between(start, end),
                                                       AccountsReceivable.status != "cancelado")).all()
    out = []
    for r in rows:
        invs = db.scalars(select(FiscalInvoice).where(FiscalInvoice.receivable_id == r.id)).all()
        if not invs and r.package_id:
            invs = db.scalars(select(FiscalInvoice).where(FiscalInvoice.package_id == r.package_id,
                                                          FiscalInvoice.receivable_id.is_(None))).all()
        authorized = [i for i in invs if i.status == "autorizada"]
        invoiced = sum((i.net_amount for i in authorized), Decimal("0"))
        issues = []
        if r.status == "pago" and not authorized:
            issues.append("Recebido sem NFS-e autorizada")
        if authorized and r.status in ("aberto", "parcial") and r.due_date < local_today():
            issues.append("Nota emitida com pagamento em atraso")
        if authorized and r.installment_count == 1 and invoiced != r.net_amount:
            issues.append("Valor da nota difere do título")
        out.append({"receivable_id": str(r.id), "description": r.description,
                    "customer": r.customer.full_name if r.customer else None, "competence_date": r.competence_date,
                    "amount": float(r.net_amount), "paid": float(r.amount_paid), "status": r.status,
                    "invoices": [{"id": str(i.id), "number": i.nfse_number, "status": i.status,
                                  "amount": float(i.net_amount)} for i in invs],
                    "issues": issues})
    unreconciled = db.scalar(select(func.count()).select_from(FinancialTransaction).where(
        FinancialTransaction.transaction_date.between(start, end), FinancialTransaction.reconciled.is_(False))) or 0
    return {"items": out, "unreconciled_transactions": unreconciled,
            "with_issues": sum(1 for o in out if o["issues"])}


# ---------------------------------------------------------------- Fluxo de caixa e fechamento
@router.get("/cash-flow")
def cash_flow(start: date, end: date, account_id: uuid.UUID | None = None, db: Session = Depends(get_db),
              user: User = Depends(require("finance.read"))):
    if (end - start).days > 400:
        raise AppError("Período máximo de 400 dias.")
    accounts = [db.get(FinancialAccount, account_id)] if account_id else db.scalars(select(FinancialAccount)).all()
    opening = sum((svc.account_balance(db, a, start - timedelta(days=1)) for a in accounts if a), Decimal("0"))
    ids = [a.id for a in accounts if a]
    rows = db.execute(select(FinancialTransaction.transaction_date, FinancialTransaction.kind,
                             func.sum(FinancialTransaction.amount))
                      .where(FinancialTransaction.transaction_date.between(start, end), FinancialTransaction.account_id.in_(ids))
                      .group_by(FinancialTransaction.transaction_date, FinancialTransaction.kind)).all()
    by_day: dict[date, dict[str, Decimal]] = {}
    for d, kind, total in rows:
        by_day.setdefault(d, {"entrada": Decimal("0"), "saida": Decimal("0")})[kind] = Decimal(total)
    days, balance = [], opening
    d = start
    while d <= end:
        v = by_day.get(d, {"entrada": Decimal("0"), "saida": Decimal("0")})
        balance += v["entrada"] - v["saida"]
        days.append({"date": d, "in": float(v["entrada"]), "out": float(v["saida"]), "balance": float(money(balance))})
        d += timedelta(days=1)
    # projeção: títulos em aberto por vencimento
    proj_in = db.execute(select(AccountsReceivable.due_date, func.sum(AccountsReceivable.amount - AccountsReceivable.discount - AccountsReceivable.amount_paid))
                         .where(AccountsReceivable.status.in_(("aberto", "parcial")), AccountsReceivable.due_date.between(start, end))
                         .group_by(AccountsReceivable.due_date)).all()
    proj_out = db.execute(select(AccountsPayable.due_date, func.sum(AccountsPayable.amount - AccountsPayable.amount_paid))
                          .where(AccountsPayable.status.in_(("aberto", "parcial")), AccountsPayable.due_date.between(start, end))
                          .group_by(AccountsPayable.due_date)).all()
    return {
        "opening_balance": float(money(opening)), "closing_balance": float(money(balance)), "days": days,
        "projection": {"receivables": [{"date": d, "amount": float(v)} for d, v in proj_in],
                       "payables": [{"date": d, "amount": float(v)} for d, v in proj_out]},
    }


@router.get("/closings")
def list_closings(account_id: uuid.UUID | None = None, db: Session = Depends(get_db), user: User = Depends(require("finance.read"))):
    stmt = select(CashClosing).order_by(CashClosing.closing_date.desc()).limit(120)
    if account_id:
        stmt = stmt.where(CashClosing.account_id == account_id)
    return [{"id": str(c.id), "account_id": str(c.account_id), "closing_date": c.closing_date,
             "opening_balance": float(c.opening_balance), "total_in": float(c.total_in), "total_out": float(c.total_out),
             "expected_balance": float(c.expected_balance),
             "counted_balance": float(c.counted_balance) if c.counted_balance is not None else None,
             "difference": float(c.difference) if c.difference is not None else None, "notes": c.notes,
             "closed_at": c.closed_at} for c in db.scalars(stmt).all()]


@router.get("/closings/preview")
def closing_preview(account_id: uuid.UUID, closing_date: date, db: Session = Depends(get_db),
                    user: User = Depends(require("finance.close"))):
    acc = db.get(FinancialAccount, account_id)
    if acc is None:
        raise NotFound("Conta")
    opening = svc.account_balance(db, acc, closing_date - timedelta(days=1))
    t_in, t_out = svc.day_totals(db, acc.id, closing_date)
    return {"opening_balance": float(opening), "total_in": float(t_in), "total_out": float(t_out),
            "expected_balance": float(opening + t_in - t_out)}


@router.post("/closings", status_code=201)
def close_day(data: ClosingIn, db: Session = Depends(get_db), user: User = Depends(require("finance.close"))):
    acc = db.get(FinancialAccount, data.account_id)
    if acc is None:
        raise NotFound("Conta")
    if data.closing_date > local_today():
        raise AppError("Não é possível fechar um dia futuro.")
    if db.scalar(select(CashClosing.id).where(CashClosing.account_id == acc.id, CashClosing.closing_date == data.closing_date)):
        raise AppError("Este dia já foi fechado para a conta selecionada.")
    opening = svc.account_balance(db, acc, data.closing_date - timedelta(days=1))
    t_in, t_out = svc.day_totals(db, acc.id, data.closing_date)
    expected = money(opening + t_in - t_out)
    diff = money(data.counted_balance - expected) if data.counted_balance is not None else None
    c = CashClosing(account_id=acc.id, closing_date=data.closing_date, opening_balance=opening, total_in=t_in,
                    total_out=t_out, expected_balance=expected, counted_balance=data.counted_balance, difference=diff,
                    notes=data.notes, closed_by=user.id)
    db.add(c)
    audit(db, "caixa_fechado", user=user, entity="cash_closing", details={"conta": acc.name, "data": str(data.closing_date),
                                                                        "esperado": str(expected), "diferenca": str(diff)})
    db.commit()
    return {"message": "Fechamento registrado." + (f" Diferença apurada: R$ {diff:.2f}." if diff else ""), "id": str(c.id)}


@router.delete("/closings/{closing_id}")
def reopen_day(closing_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("finance.reverse", "finance.close"))):
    c = db.get(CashClosing, closing_id)
    if c is None:
        raise NotFound("Fechamento")
    later = db.scalar(select(CashClosing.id).where(CashClosing.account_id == c.account_id, CashClosing.closing_date > c.closing_date))
    if later:
        raise AppError("Reabra primeiro os fechamentos posteriores.")
    db.delete(c)
    audit(db, "caixa_reaberto", user=user, entity="cash_closing", entity_id=closing_id, details={"data": str(c.closing_date)})
    db.commit()
    return {"message": "Dia reaberto."}


@router.get("/delinquency")
def delinquency(db: Session = Depends(get_db), user: User = Depends(require("finance.read"))):
    rows = db.scalars(select(AccountsReceivable).where(svc.overdue_condition()).order_by(AccountsReceivable.due_date)).all()
    by_customer: dict[str, dict] = {}
    for r in rows:
        key = str(r.customer_id) if r.customer_id else "sem_cliente"
        item = by_customer.setdefault(key, {"customer_id": key if r.customer_id else None,
                                            "name": r.customer.full_name if r.customer else "Sem cliente",
                                            "phone": (r.customer.whatsapp or r.customer.phone) if r.customer else None,
                                            "total": 0.0, "oldest_due": r.due_date, "items": 0})
        item["total"] += float(r.balance)
        item["items"] += 1
    total = sum(v["total"] for v in by_customer.values())
    return {"total": total, "customers": sorted(by_customer.values(), key=lambda x: -x["total"])}
