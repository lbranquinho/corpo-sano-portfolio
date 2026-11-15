"""Estimativas tributárias parametrizáveis e calendário de obrigações.

Nada é presumido: só são calculados os tributos com regra cadastrada (e vigente) para o regime
configurado. Todo resultado é ESTIMATIVA até validação pelo contador.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.utils import add_months, local_today, money, month_bounds
from app.models.fiscal import FiscalInvoice, TaxAssessment, TaxCompanySettings, TaxObligation, TaxObligationTemplate, TaxRate
from app.models.finance import AccountsReceivable

TAXES = {
    "ISS": "Imposto sobre Serviços",
    "IRPJ": "Imposto de Renda Pessoa Jurídica",
    "CSLL": "Contribuição Social sobre o Lucro Líquido",
    "PIS": "PIS",
    "COFINS": "COFINS",
    "CPP": "Contribuição Previdenciária Patronal",
    "IBS": "Imposto sobre Bens e Serviços (Reforma Tributária)",
    "CBS": "Contribuição sobre Bens e Serviços (Reforma Tributária)",
    "SIMPLES": "Simples Nacional (DAS) — alíquota efetiva",
    "DAS_MEI": "DAS-MEI (valor fixo mensal)",
    "RETENCOES": "Retenções sofridas/efetuadas",
}


def safe_date(year: int, month: int, day: int) -> date:
    import calendar

    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def revenue_base(db: Session, period: str, source: str = "faturada") -> Decimal:
    start, end = month_bounds(period)
    if source == "faturada":
        v = db.scalar(select(func.coalesce(func.sum(FiscalInvoice.net_amount), 0)).where(
            FiscalInvoice.status == "autorizada", FiscalInvoice.competence_date.between(start, end)))
    else:
        v = db.scalar(select(func.coalesce(func.sum(AccountsReceivable.amount - AccountsReceivable.discount), 0)).where(
            AccountsReceivable.status != "cancelado", AccountsReceivable.competence_date.between(start, end)))
    return money(v)


def applicable_rates(db: Session, regime: str, period: str) -> list[TaxRate]:
    start, end = month_bounds(period)
    return db.scalars(select(TaxRate).where(
        TaxRate.is_active.is_(True), TaxRate.regime == regime, TaxRate.valid_from <= end,
        or_(TaxRate.valid_to.is_(None), TaxRate.valid_to >= start),
    ).order_by(TaxRate.tax)).all()


def estimate_period(db: Session, period: str, source: str = "faturada") -> list[TaxAssessment]:
    s = db.scalar(select(TaxCompanySettings).limit(1))
    if s is None or not s.tax_regime:
        raise AppError("Defina o regime tributário no cadastro fiscal antes de estimar tributos.")
    base = revenue_base(db, period, source)
    rates = applicable_rates(db, s.tax_regime, period)
    if not rates:
        raise AppError("Nenhuma regra tributária vigente cadastrada para o regime configurado. "
                       "Cadastre as alíquotas validadas pelo contador em Contábil > Tributos > Regras.")
    out = []
    start, _ = month_bounds(period)
    for r in rates:
        if r.base == "presuncao":
            calc_base = money(base * (r.presumption_percent or 0) / 100)
            note = f"Base presumida {r.presumption_percent}% × alíquota {r.rate}%"
        elif r.base == "fixo":
            calc_base = base
            note = "Valor fixo mensal"
        else:
            calc_base = base
            note = f"Receita {source} × alíquota {r.rate}%"
        amount = money(r.rate) if r.base == "fixo" else money(calc_base * r.rate / 100)
        row = db.scalar(select(TaxAssessment).where(TaxAssessment.period == period, TaxAssessment.tax == r.tax))
        due = None
        if r.due_day:
            nxt = add_months(start, 1)
            due = safe_date(nxt.year, nxt.month, r.due_day)
        if row is None:
            row = TaxAssessment(period=period, tax=r.tax, regime=s.tax_regime, base_amount=calc_base, rate=r.rate,
                                estimated_amount=amount, status="estimado", due_date=due)
            db.add(row)
        elif row.status == "estimado":
            row.base_amount, row.rate, row.estimated_amount, row.regime = calc_base, r.rate, amount, s.tax_regime
            row.due_date = row.due_date or due
        row.calculation_notes = (f"ESTIMATIVA — {note}. Regra vigente desde {r.valid_from:%d/%m/%Y}"
                                 + (" (validada pelo contador)" if r.validated else " (regra NÃO validada)") + ".")
        out.append(row)
    db.flush()
    return out


def generate_obligations(db: Session, period: str) -> int:
    """Gera as obrigações do período a partir dos modelos ATIVOS aplicáveis ao regime configurado."""
    s = db.scalar(select(TaxCompanySettings).limit(1))
    if s is None or not s.tax_regime:
        raise AppError("Defina o regime tributário antes de gerar o calendário de obrigações.")
    year, month = (int(p) for p in period.split("-"))
    created = 0
    for t in db.scalars(select(TaxObligationTemplate).where(TaxObligationTemplate.is_active.is_(True))).all():
        if t.applicable_regimes and s.tax_regime not in t.applicable_regimes:
            continue
        if t.requires_employees and not s.has_employees:
            continue
        if t.frequency == "anual":
            if t.due_month != month:
                continue
            ref = str(year - 1)
            due = safe_date(year, month, t.due_day)
        else:
            ref_date = add_months(date(year, month, 1), -t.reference_offset_months)
            ref = f"{ref_date.year}-{ref_date.month:02d}"
            due = safe_date(year, month, t.due_day)
        if db.scalar(select(TaxObligation.id).where(TaxObligation.template_id == t.id, TaxObligation.reference_period == ref)):
            continue
        db.add(TaxObligation(template_id=t.id, name=t.name, code=t.code, reference_period=ref, due_date=due,
                             responsible=t.responsible or s.accountant_name, status="pendente"))
        created += 1
    db.flush()
    return created


def mark_late_obligations(db: Session) -> int:
    rows = db.scalars(select(TaxObligation).where(TaxObligation.status.in_(("pendente", "em_preparacao")),
                                                  TaxObligation.due_date < local_today())).all()
    for o in rows:
        o.status = "atrasado"
    return len(rows)
