"""Painel gerencial — indicadores calculados em tempo real a partir dos dados."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import has_perm, require
from app.core.utils import add_months, clinic_tz, day_bounds, local_today, money, to_local, utcnow
from app.models.auth import User
from app.models.clinic import BusinessHour, Professional
from app.models.customer import Customer
from app.models.crm import CrmTask
from app.models.finance import AccountsPayable, AccountsReceivable, Expense, FinancialTransaction, PaymentMethod
from app.models.fiscal import AccountingExport, DigitalCertificate, FiscalInvoice, TaxAssessment, TaxObligation
from app.models.schedule import Appointment
from app.models.system import BackupHistory, StoredFile
from app.models.whatsapp import WhatsappMessage
from app.services import finance as fin
from app.services.customers import filter_condition
from app.services.packages import package_alerts

router = APIRouter(prefix="/dashboard", tags=["Painel"])


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _occupancy(db: Session, day: date, professional_id=None) -> float | None:
    bh = db.scalar(select(BusinessHour).where(BusinessHour.weekday == day.weekday()))
    if bh is None or not bh.is_open:
        return None
    profs = 1 if professional_id else (db.scalar(select(func.count()).select_from(Professional).where(Professional.is_active.is_(True))) or 0)
    if not profs:
        return None
    minutes = (datetime.combine(day, bh.close_time) - datetime.combine(day, bh.open_time)).seconds / 60
    if bh.break_start and bh.break_end:
        minutes -= (datetime.combine(day, bh.break_end) - datetime.combine(day, bh.break_start)).seconds / 60
    lo, hi = day_bounds(day)
    stmt = select(func.coalesce(func.sum(Appointment.duration_minutes), 0)).where(
        Appointment.start_at >= lo, Appointment.start_at < hi,
        Appointment.status.in_(("agendado", "confirmado", "em_atendimento", "concluido")))
    if professional_id:
        stmt = stmt.where(Appointment.professional_id == professional_id)
    booked = db.scalar(stmt) or 0
    return round(min(booked / (minutes * profs) * 100, 100), 1) if minutes > 0 else None


@router.get("")
def dashboard(db: Session = Depends(get_db), user: User = Depends(require("dashboard.view"))):
    today = local_today()
    m_start = _month_start(today)
    prev_start = add_months(m_start, -1)
    prev_end = m_start - timedelta(days=1)
    lo_m, _ = day_bounds(m_start)
    lo_t, hi_t = day_bounds(today)
    own = None if has_perm(user, "agenda.read_all") else user.professional_id
    now = utcnow()

    def appt_count(statuses, start_dt, end_dt):
        stmt = select(func.count()).select_from(Appointment).where(Appointment.start_at >= start_dt, Appointment.start_at < end_dt,
                                                                    Appointment.status.in_(statuses))
        if own:
            stmt = stmt.where(Appointment.professional_id == own)
        return db.scalar(stmt) or 0

    _, hi_month = day_bounds(today)
    lo_prev, _ = day_bounds(prev_start)
    _, hi_prev = day_bounds(prev_end)
    upcoming_stmt = select(Appointment).where(Appointment.start_at >= now, Appointment.status.in_(("agendado", "confirmado")))
    today_stmt = select(Appointment).where(Appointment.start_at >= lo_t, Appointment.start_at < hi_t,
                                           Appointment.status != "cancelado")
    if own:
        upcoming_stmt = upcoming_stmt.where(Appointment.professional_id == own)
        today_stmt = today_stmt.where(Appointment.professional_id == own)
    today_list = db.scalars(today_stmt.order_by(Appointment.start_at)).all()
    upcoming = db.scalars(upcoming_stmt.order_by(Appointment.start_at).limit(6)).all()

    # taxa de retorno: clientes atendidos nos últimos 180 dias com 2+ atendimentos
    since = now - timedelta(days=180)
    visits = db.execute(select(Appointment.customer_id, func.count()).where(
        Appointment.status == "concluido", Appointment.start_at >= since).group_by(Appointment.customer_id)).all()
    return_rate = round(sum(1 for _, n in visits if n >= 2) / len(visits) * 100, 1) if visits else None

    op = {
        "total_customers": db.scalar(select(func.count()).select_from(Customer).where(Customer.status != "anonimizado")) or 0,
        "active_customers": db.scalar(select(func.count()).select_from(Customer).where(filter_condition(db, "ativos"))) or 0,
        "new_customers_month": db.scalar(select(func.count()).select_from(Customer).where(Customer.created_at >= lo_m)) or 0,
        "appointments_today": len(today_list),
        "completed_month": appt_count(("concluido",), lo_m, hi_month),
        "completed_prev_month": appt_count(("concluido",), lo_prev, hi_prev),
        "cancellations_month": appt_count(("cancelado",), lo_m, hi_month),
        "no_shows_month": appt_count(("falta",), lo_m, hi_month),
        "occupancy_today": _occupancy(db, today, own),
        "occupancy_week": None,
        "return_rate": return_rate,
    }
    week = [today + timedelta(days=i) for i in range(7)]
    occ = [o for o in (_occupancy(db, d, own) for d in week) if o is not None]
    op["occupancy_week"] = round(sum(occ) / len(occ), 1) if occ else None

    def appt_brief(a: Appointment) -> dict:
        return {"id": str(a.id), "start_at": a.start_at, "customer": a.customer.full_name, "service": a.service.name,
                "professional": a.professional.name, "status": a.status, "color": a.professional.color}

    out: dict = {"operational": op, "today": [appt_brief(a) for a in today_list],
                 "upcoming": [appt_brief(a) for a in upcoming], "alerts": [], "charts": {}}

    # gráficos operacionais
    lo_12, _ = day_bounds(add_months(m_start, -11))
    per_prof = db.execute(select(Professional.name, Professional.color, func.count()).join(
        Appointment, Appointment.professional_id == Professional.id).where(
        Appointment.status == "concluido", Appointment.start_at >= lo_m).group_by(Professional.name, Professional.color)).all()
    out["charts"]["by_professional"] = [{"name": n, "color": c, "value": v} for n, c, v in per_prof]
    from app.models.catalog import Service

    top = db.execute(select(Service.name, func.count()).join(Appointment, Appointment.service_id == Service.id).where(
        Appointment.status == "concluido", Appointment.start_at >= day_bounds(add_months(m_start, -2))[0])
        .group_by(Service.name).order_by(func.count().desc()).limit(6)).all()
    out["charts"]["top_services"] = [{"name": n, "value": v} for n, v in top]
    months = [add_months(m_start, -i) for i in range(11, -1, -1)]
    new_by_month = defaultdict(int)
    for (created,) in db.execute(select(Customer.created_at).where(Customer.created_at >= lo_12)).all():
        lc = to_local(created)
        new_by_month[(lc.year, lc.month)] += 1
    base_total = db.scalar(select(func.count()).select_from(Customer).where(Customer.created_at < lo_12)) or 0
    evo, acc = [], base_total
    for m in months:
        acc += new_by_month[(m.year, m.month)]
        evo.append({"month": f"{m:%m/%Y}", "new": new_by_month[(m.year, m.month)], "total": acc})
    out["charts"]["customers"] = evo

    if has_perm(user, "dashboard.financial"):
        s_month = fin.revenue_summary(db, m_start, today)
        s_prev = fin.revenue_summary(db, prev_start, prev_end)
        s_today = fin.revenue_summary(db, today, today)
        completed_avulsos = db.scalars(select(Appointment).where(Appointment.status == "concluido", Appointment.start_at >= lo_m,
                                                                 Appointment.package_id.is_(None))).all()
        values = [a.net_price for a in completed_avulsos if a.net_price > 0]
        out["financial"] = {
            "received_today": float(s_today["received"]), "contracted_today": float(s_today["contracted"]),
            "contracted_month": float(s_month["contracted"]), "received_month": float(s_month["received"]),
            "pending_month": float(s_month["pending"]), "overdue": float(s_month["overdue"]),
            "expenses_month": float(s_month["expenses_competence"]), "expenses_paid_month": float(s_month["expenses_paid"]),
            "result_month": float(s_month["operating_result_competence"]),
            "ticket_avg": float(money(sum(values, Decimal("0")) / len(values))) if values else None,
            "prev": {"contracted": float(s_prev["contracted"]), "received": float(s_prev["received"]),
                     "expenses": float(s_prev["expenses_competence"]), "result": float(s_prev["operating_result_competence"])},
        }
        series = []
        for m in months:
            end = add_months(m, 1) - timedelta(days=1)
            s = fin.revenue_summary(db, m, min(end, today) if m == m_start else end)
            series.append({"month": f"{m:%m/%Y}", "contracted": float(s["contracted"]), "received": float(s["received"]),
                           "invoiced": float(s["invoiced"]), "expenses": float(s["expenses_competence"])})
        out["charts"]["revenue"] = series
        pm = db.execute(select(PaymentMethod.name, func.sum(FinancialTransaction.amount)).join(
            FinancialTransaction, FinancialTransaction.payment_method_id == PaymentMethod.id).where(
            FinancialTransaction.kind == "entrada", FinancialTransaction.is_reversal.is_(False),
            FinancialTransaction.receivable_id.is_not(None), FinancialTransaction.transaction_date >= m_start)
            .group_by(PaymentMethod.name)).all()
        out["charts"]["payment_methods"] = [{"name": n, "value": float(v)} for n, v in pm]
        overdue_n = db.scalar(select(func.count()).select_from(AccountsReceivable).where(fin.overdue_condition())) or 0
        if overdue_n:
            out["alerts"].append({"level": "warning", "module": "financeiro", "text": f"{overdue_n} conta(s) a receber em atraso.", "url": "/financeiro?aba=receber&atraso=1"})
        pay_due = db.scalar(select(func.count()).select_from(AccountsPayable).where(
            AccountsPayable.status.in_(("aberto", "parcial")), AccountsPayable.due_date <= today + timedelta(days=3))) or 0
        if pay_due:
            out["alerts"].append({"level": "info", "module": "financeiro", "text": f"{pay_due} conta(s) a pagar vencendo em até 3 dias ou vencidas.", "url": "/financeiro?aba=pagar"})

    if has_perm(user, "dashboard.fiscal"):
        inv_month = db.execute(select(FiscalInvoice.status, func.count(), func.coalesce(func.sum(FiscalInvoice.net_amount), 0))
                               .where(FiscalInvoice.competence_date.between(m_start, today)).group_by(FiscalInvoice.status)).all()
        by = {s: (n, v) for s, n, v in inv_month}
        period = f"{today.year}-{today.month:02d}"
        taxes = db.scalar(select(func.coalesce(func.sum(TaxAssessment.estimated_amount), 0)).where(TaxAssessment.period == period)) or 0
        due_soon = db.scalars(select(TaxObligation).where(TaxObligation.status.in_(("pendente", "em_preparacao", "atrasado")),
                                                          TaxObligation.due_date <= today + timedelta(days=15))
                              .order_by(TaxObligation.due_date)).all()
        contracted = fin.revenue_summary(db, m_start, today)
        last_month_export = db.scalar(select(AccountingExport.id).where(AccountingExport.period_start <= prev_start,
                                                                         AccountingExport.period_end >= prev_end).limit(1))
        exp_ids = db.scalars(select(Expense.id).where(Expense.competence_date.between(prev_start, today))).all()
        with_file = set(db.scalars(select(StoredFile.expense_id).where(StoredFile.expense_id.in_(exp_ids))).all()) if exp_ids else set()
        pending_docs = (len(exp_ids) - len(with_file)) + (0 if last_month_export else 1)
        out["fiscal"] = {
            "authorized_month": by.get("autorizada", (0, 0))[0],
            "pending": sum(by.get(s, (0, 0))[0] for s in ("rascunho", "aguardando_transmissao", "transmitindo", "rejeitada")),
            "cancelled_month": by.get("cancelada", (0, 0))[0] + by.get("substituida", (0, 0))[0],
            "invoiced_month": float(by.get("autorizada", (0, Decimal("0")))[1]),
            "not_invoiced_month": float(contracted["not_invoiced"]),
            "taxes_estimated_month": float(taxes),
            "obligations_due": [{"id": str(o.id), "name": o.name, "due_date": o.due_date, "status": o.status} for o in due_soon[:8]],
            "pending_accounting_docs": pending_docs,
            "last_month_exported": bool(last_month_export),
        }
        cert = db.scalar(select(DigitalCertificate).where(DigitalCertificate.is_active.is_(True)))
        if cert and cert.valid_to - now < timedelta(days=30):
            out["alerts"].append({"level": "danger", "module": "fiscal", "text": f"Certificado digital vence em {cert.valid_to:%d/%m/%Y}.", "url": "/fiscal/configuracoes"})
        late = sum(1 for o in due_soon if o.status == "atrasado")
        if late:
            out["alerts"].append({"level": "danger", "module": "fiscal", "text": f"{late} obrigação(ões) fiscal(is) atrasada(s).", "url": "/fiscal/obrigacoes"})
        waiting = db.scalar(select(func.count()).select_from(FiscalInvoice).where(FiscalInvoice.status.in_(("aguardando_transmissao", "transmitindo")))) or 0
        if waiting:
            out["alerts"].append({"level": "warning", "module": "fiscal", "text": f"{waiting} NFS-e aguardando confirmação do serviço fiscal (reprocessar).", "url": "/fiscal/notas?status=aguardando_transmissao"})

    if has_perm(user, "packages.read"):
        pa = package_alerts(db)
        if pa["low_balance"]:
            out["alerts"].append({"level": "info", "module": "pacotes", "text": f"{len(pa['low_balance'])} pacote(s) com saldo baixo de sessões.", "url": "/pacotes?alerta=low_balance"})
        if pa["expiring"]:
            out["alerts"].append({"level": "warning", "module": "pacotes", "text": f"{len(pa['expiring'])} pacote(s) vencendo em breve.", "url": "/pacotes?alerta=expiring"})
    if has_perm(user, "crm.read"):
        overdue_tasks = db.scalar(select(func.count()).select_from(CrmTask).where(CrmTask.status == "pendente", CrmTask.due_at < now)) or 0
        if overdue_tasks:
            out["alerts"].append({"level": "info", "module": "crm", "text": f"{overdue_tasks} tarefa(s) de relacionamento vencida(s).", "url": "/crm?aba=tarefas"})
    if has_perm(user, "whatsapp.read"):
        failed = db.scalar(select(func.count()).select_from(WhatsappMessage).where(
            WhatsappMessage.status == "falhou", WhatsappMessage.created_at >= now - timedelta(days=2))) or 0
        if failed:
            out["alerts"].append({"level": "warning", "module": "whatsapp", "text": f"{failed} mensagem(ns) WhatsApp com falha nas últimas 48 h.", "url": "/whatsapp?status=falhou"})
    if has_perm(user, "backups.manage"):
        last_ok = db.scalar(select(func.max(BackupHistory.finished_at)).where(BackupHistory.status == "sucesso"))
        if last_ok is None or now - last_ok > timedelta(hours=26):
            out["alerts"].append({"level": "danger", "module": "backup", "text": "Nenhum backup bem-sucedido nas últimas 26 horas.", "url": "/configuracoes?aba=backups"})
    return out
