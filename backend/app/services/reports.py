"""Central de relatórios — todos calculados a partir dos dados reais do banco."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.settings_store import get_setting
from app.core.utils import day_bounds, local_today, money, to_local
from app.models.catalog import Service
from app.models.clinic import Professional
from app.models.customer import Customer
from app.models.finance import (
    AccountsPayable,
    AccountsReceivable,
    CostCenter,
    FinancialAccount,
    FinancialCategory,
    FinancialTransaction,
    PaymentMethod,
)
from app.models.fiscal import FiscalDocument, FiscalInvoice, TaxAssessment, TaxObligation
from app.models.package import Package
from app.models.schedule import Appointment
from app.services.exporters import Column as C
from app.services.exporters import ReportData

ReportFn = Callable[[Session, date, date], ReportData]
REGISTRY: dict[str, dict] = {}


def report(key: str, title: str, category: str):
    def deco(fn: ReportFn) -> ReportFn:
        REGISTRY[key] = {"key": key, "title": title, "category": category, "fn": fn}
        return fn
    return deco


def _period(start: date, end: date) -> str:
    return f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"


def _appts(db: Session, start: date, end: date, statuses: tuple[str, ...]) -> list[Appointment]:
    lo, _ = day_bounds(start)
    _, hi = day_bounds(end)
    return db.scalars(select(Appointment).where(Appointment.start_at >= lo, Appointment.start_at < hi,
                                                Appointment.status.in_(statuses)).order_by(Appointment.start_at)).all()


def _lookup(db: Session, model) -> dict:
    return {r.id: r.name for r in db.scalars(select(model)).all()}


# ------------------------------------------------------------------ Operacionais
@report("atendimentos", "Atendimentos realizados", "operacional")
def r_atendimentos(db, start, end):
    rows = [{"data": to_local(a.start_at).replace(tzinfo=None), "cliente": a.customer.full_name, "servico": a.service.name,
             "profissional": a.professional.name, "sala": a.room.name if a.room else "", "pacote": "Sim" if a.package_id else "Não",
             "valor": a.net_price} for a in _appts(db, start, end, ("concluido",))]
    return ReportData("Atendimentos realizados", [C("data", "Data/hora", "datetime"), C("cliente", "Cliente"),
                      C("servico", "Serviço"), C("profissional", "Profissional"), C("sala", "Sala"),
                      C("pacote", "Pacote"), C("valor", "Valor", "money")], rows,
                      {"valor": money(sum((r["valor"] for r in rows), Decimal("0")))}, period=_period(start, end))


@report("cancelamentos", "Cancelamentos", "operacional")
def r_cancel(db, start, end):
    rows = [{"data": to_local(a.start_at).replace(tzinfo=None), "cliente": a.customer.full_name, "servico": a.service.name,
             "profissional": a.professional.name, "motivo": a.cancel_reason or ""} for a in _appts(db, start, end, ("cancelado",))]
    return ReportData("Cancelamentos", [C("data", "Data/hora", "datetime"), C("cliente", "Cliente"), C("servico", "Serviço"),
                      C("profissional", "Profissional"), C("motivo", "Motivo")], rows, {"cliente": len(rows)},
                      period=_period(start, end))


@report("faltas", "Faltas", "operacional")
def r_faltas(db, start, end):
    rows = [{"data": to_local(a.start_at).replace(tzinfo=None), "cliente": a.customer.full_name, "telefone": a.customer.whatsapp or a.customer.phone or "",
             "servico": a.service.name, "profissional": a.professional.name} for a in _appts(db, start, end, ("falta",))]
    return ReportData("Faltas", [C("data", "Data/hora", "datetime"), C("cliente", "Cliente"), C("telefone", "Telefone"),
                      C("servico", "Serviço"), C("profissional", "Profissional")], rows, {"cliente": len(rows)},
                      period=_period(start, end))


@report("clientes_novos", "Clientes novos", "operacional")
def r_new_customers(db, start, end):
    lo, _ = day_bounds(start)
    _, hi = day_bounds(end)
    cs = db.scalars(select(Customer).where(Customer.created_at >= lo, Customer.created_at < hi,
                                           Customer.status != "anonimizado").order_by(Customer.created_at)).all()
    rows = [{"cadastro": to_local(c.created_at).replace(tzinfo=None), "nome": c.full_name, "telefone": c.whatsapp or c.phone or "",
             "origem": c.source or ""} for c in cs]
    return ReportData("Clientes novos", [C("cadastro", "Cadastro", "datetime"), C("nome", "Nome"),
                      C("telefone", "Telefone"), C("origem", "Origem")], rows, {"nome": len(rows)}, period=_period(start, end))


@report("clientes_recorrentes", "Clientes recorrentes", "operacional")
def r_recurring(db, start, end):
    min_visits = int(get_setting(db, "crm.recurring_min_visits") or 2)
    counts: dict = defaultdict(lambda: {"visitas": 0, "valor": Decimal("0"), "ultima": None})
    for a in _appts(db, start, end, ("concluido",)):
        d = counts[a.customer_id]
        d["nome"], d["visitas"] = a.customer.full_name, d["visitas"] + 1
        d["valor"] += a.net_price
        d["ultima"] = to_local(a.start_at).replace(tzinfo=None)
    rows = sorted([v for v in counts.values() if v["visitas"] >= min_visits], key=lambda x: -x["visitas"])
    return ReportData("Clientes recorrentes", [C("nome", "Cliente"), C("visitas", "Atendimentos", "int"),
                      C("valor", "Valor avulso", "money"), C("ultima", "Último atendimento", "datetime")], rows,
                      notes=[f"Recorrente = {min_visits} ou mais atendimentos no período."], period=_period(start, end))


@report("servicos_mais_procurados", "Serviços mais procurados", "operacional")
def r_top_services(db, start, end):
    agg: dict = defaultdict(lambda: {"quantidade": 0, "valor": Decimal("0")})
    for a in _appts(db, start, end, ("concluido",)):
        agg[a.service.name]["quantidade"] += 1
        agg[a.service.name]["valor"] += a.net_price
    rows = sorted([{"servico": k, **v} for k, v in agg.items()], key=lambda x: -x["quantidade"])
    return ReportData("Serviços mais procurados", [C("servico", "Serviço"), C("quantidade", "Atendimentos", "int"),
                      C("valor", "Valor avulso", "money")], rows, period=_period(start, end),
                      notes=["Valores de atendimentos de pacote aparecem na venda do pacote."])


@report("pacotes_vendidos", "Pacotes vendidos", "operacional")
def r_packages(db, start, end):
    ps = db.scalars(select(Package).where(Package.purchased_at.between(start, end)).order_by(Package.purchased_at)).all()
    rows = [{"data": p.purchased_at, "cliente": p.customer.full_name, "pacote": p.name, "sessoes": p.sessions_total,
             "usadas": p.sessions_used, "valor": p.price, "status": p.status} for p in ps]
    return ReportData("Pacotes vendidos", [C("data", "Data", "date"), C("cliente", "Cliente"), C("pacote", "Pacote"),
                      C("sessoes", "Sessões", "int"), C("usadas", "Utilizadas", "int"), C("valor", "Valor", "money"),
                      C("status", "Situação")], rows, {"valor": money(sum((r["valor"] for r in rows), Decimal("0")))},
                      period=_period(start, end))


@report("produtividade", "Produtividade por profissional", "operacional")
def r_productivity(db, start, end):
    agg: dict = defaultdict(lambda: {"concluidos": 0, "minutos": 0, "faltas": 0, "cancelados": 0, "valor": Decimal("0")})
    for a in _appts(db, start, end, ("concluido", "falta", "cancelado")):
        d = agg[a.professional.name]
        if a.status == "concluido":
            d["concluidos"] += 1
            d["minutos"] += a.duration_minutes
            d["valor"] += a.net_price
        elif a.status == "falta":
            d["faltas"] += 1
        else:
            d["cancelados"] += 1
    rows = [{"profissional": k, **v, "horas": round(v["minutos"] / 60, 1)} for k, v in sorted(agg.items())]
    return ReportData("Produtividade por profissional", [C("profissional", "Profissional"), C("concluidos", "Atendimentos", "int"),
                      C("horas", "Horas"), C("faltas", "Faltas", "int"), C("cancelados", "Cancelamentos", "int"),
                      C("valor", "Valor avulso", "money")], rows, period=_period(start, end))


# ------------------------------------------------------------------ Financeiros
@report("faturamento", "Faturamento (receita contratada por competência)", "financeiro")
def r_billing(db, start, end):
    rs = db.scalars(select(AccountsReceivable).where(AccountsReceivable.competence_date.between(start, end),
                                                     AccountsReceivable.status != "cancelado").order_by(AccountsReceivable.competence_date)).all()
    rows = [{"competencia": r.competence_date, "cliente": r.customer.full_name if r.customer else "", "descricao": r.description,
             "origem": r.origin, "valor": r.net_amount, "recebido": r.amount_paid, "saldo": r.balance, "status": r.status} for r in rs]
    tot = {k: money(sum((r[k] for r in rows), Decimal("0"))) for k in ("valor", "recebido", "saldo")}
    return ReportData("Faturamento (receita contratada)", [C("competencia", "Competência", "date"), C("cliente", "Cliente"),
                      C("descricao", "Descrição"), C("origem", "Origem"), C("valor", "Valor", "money"),
                      C("recebido", "Recebido", "money"), C("saldo", "Saldo", "money"), C("status", "Situação")], rows, tot,
                      notes=["Receita contratada: atendimentos concluídos, pacotes vendidos e lançamentos avulsos. Agendamentos não entram."],
                      period=_period(start, end))


@report("receitas_recebidas", "Receitas recebidas", "financeiro")
def r_received(db, start, end):
    methods, accounts = _lookup(db, PaymentMethod), _lookup(db, FinancialAccount)
    txs = db.scalars(select(FinancialTransaction).where(FinancialTransaction.transaction_date.between(start, end),
                                                        FinancialTransaction.receivable_id.is_not(None))
                     .order_by(FinancialTransaction.transaction_date)).all()
    rows = [{"data": t.transaction_date, "descricao": t.description, "forma": methods.get(t.payment_method_id, ""),
             "conta": accounts.get(t.account_id, ""), "valor": t.amount if t.kind == "entrada" else -t.amount,
             "tipo": "Estorno" if t.is_reversal else "Recebimento"} for t in txs]
    return ReportData("Receitas recebidas", [C("data", "Data", "date"), C("descricao", "Descrição"), C("tipo", "Tipo"),
                      C("forma", "Forma de pagamento"), C("conta", "Conta"), C("valor", "Valor", "money")], rows,
                      {"valor": money(sum((r["valor"] for r in rows), Decimal("0")))}, period=_period(start, end))


@report("receitas_pendentes", "Receitas pendentes", "financeiro")
def r_pending(db, start, end):
    rs = db.scalars(select(AccountsReceivable).where(AccountsReceivable.status.in_(("aberto", "parcial")),
                                                     AccountsReceivable.due_date <= end).order_by(AccountsReceivable.due_date)).all()
    today = local_today()
    rows = [{"vencimento": r.due_date, "cliente": r.customer.full_name if r.customer else "", "descricao": r.description,
             "saldo": r.balance, "atraso": max((today - r.due_date).days, 0)} for r in rs]
    return ReportData("Receitas pendentes", [C("vencimento", "Vencimento", "date"), C("cliente", "Cliente"),
                      C("descricao", "Descrição"), C("saldo", "Saldo", "money"), C("atraso", "Dias em atraso", "int")], rows,
                      {"saldo": money(sum((r["saldo"] for r in rows), Decimal("0")))}, period=f"vencimentos até {end:%d/%m/%Y}")


@report("despesas", "Despesas", "financeiro")
def r_expenses(db, start, end):
    cats, ccs = _lookup(db, FinancialCategory), _lookup(db, CostCenter)
    ps = db.scalars(select(AccountsPayable).where(AccountsPayable.competence_date.between(start, end),
                                                  AccountsPayable.status != "cancelado").order_by(AccountsPayable.competence_date)).all()
    rows = [{"competencia": p.competence_date, "vencimento": p.due_date, "descricao": p.description,
             "fornecedor": p.supplier_name or "", "categoria": cats.get(p.category_id, ""), "centro": ccs.get(p.cost_center_id, ""),
             "valor": p.amount, "pago": p.amount_paid, "status": p.status} for p in ps]
    return ReportData("Despesas", [C("competencia", "Competência", "date"), C("vencimento", "Vencimento", "date"),
                      C("descricao", "Descrição"), C("fornecedor", "Fornecedor"), C("categoria", "Categoria"),
                      C("centro", "Centro de custo"), C("valor", "Valor", "money"), C("pago", "Pago", "money"),
                      C("status", "Situação")], rows,
                      {k: money(sum((r[k] for r in rows), Decimal("0"))) for k in ("valor", "pago")}, period=_period(start, end))


@report("fluxo_caixa", "Fluxo de caixa", "financeiro")
def r_cashflow(db, start, end):
    from app.services.finance import account_balance

    accounts = db.scalars(select(FinancialAccount)).all()
    balance = sum((account_balance(db, a, start - timedelta(days=1)) for a in accounts), Decimal("0"))
    data = db.execute(select(FinancialTransaction.transaction_date, FinancialTransaction.kind, func.sum(FinancialTransaction.amount))
                      .where(FinancialTransaction.transaction_date.between(start, end))
                      .group_by(FinancialTransaction.transaction_date, FinancialTransaction.kind)).all()
    by_day: dict = defaultdict(lambda: {"entrada": Decimal("0"), "saida": Decimal("0")})
    for d, k, v in data:
        by_day[d][k] = Decimal(v)
    rows = []
    for d in sorted(by_day):
        balance += by_day[d]["entrada"] - by_day[d]["saida"]
        rows.append({"data": d, "entradas": by_day[d]["entrada"], "saidas": by_day[d]["saida"], "saldo": money(balance)})
    return ReportData("Fluxo de caixa", [C("data", "Data", "date"), C("entradas", "Entradas", "money"),
                      C("saidas", "Saídas", "money"), C("saldo", "Saldo acumulado", "money")], rows,
                      {k: money(sum((r[k] for r in rows), Decimal("0"))) for k in ("entradas", "saidas")}, period=_period(start, end))


@report("resultado_operacional", "Resultado operacional estimado", "financeiro")
def r_result(db, start, end):
    from app.services.finance import revenue_summary

    s = revenue_summary(db, start, end)
    rows = [
        {"indicador": "Receita contratada (competência)", "valor": s["contracted"]},
        {"indicador": "Despesas (competência)", "valor": -s["expenses_competence"]},
        {"indicador": "Resultado por competência (estimado)", "valor": s["operating_result_competence"]},
        {"indicador": "Receita recebida (caixa)", "valor": s["received"]},
        {"indicador": "Despesas pagas (caixa)", "valor": -s["expenses_paid"]},
        {"indicador": "Resultado de caixa", "valor": s["operating_result_cash"]},
        {"indicador": "Receita faturada (NFS-e autorizadas)", "valor": s["invoiced"]},
        {"indicador": "Receita pendente", "valor": s["pending"]},
    ]
    return ReportData("Resultado operacional estimado", [C("indicador", "Indicador"), C("valor", "Valor", "money")], rows,
                      notes=["Resultado gerencial estimado, sem tributos sobre o lucro. Não é demonstração contábil."],
                      period=_period(start, end))


@report("ticket_medio", "Ticket médio", "financeiro")
def r_ticket(db, start, end):
    appts = _appts(db, start, end, ("concluido",))
    avulsos = [a.net_price for a in appts if not a.package_id and a.net_price > 0]
    pkgs = db.scalars(select(Package).where(Package.purchased_at.between(start, end), Package.status != "cancelado")).all()
    customers = {a.customer_id for a in appts}
    revenue = sum(avulsos, Decimal("0")) + sum((p.price for p in pkgs), Decimal("0"))
    rows = [
        {"indicador": "Atendimentos concluídos", "valor": len(appts)},
        {"indicador": "Ticket médio do atendimento avulso", "valor": _fmtm(sum(avulsos, Decimal("0")) / len(avulsos)) if avulsos else "—"},
        {"indicador": "Ticket médio por pacote", "valor": _fmtm(sum((p.price for p in pkgs), Decimal("0")) / len(pkgs)) if pkgs else "—"},
        {"indicador": "Receita média por cliente atendido", "valor": _fmtm(revenue / len(customers)) if customers else "—"},
    ]
    return ReportData("Ticket médio", [C("indicador", "Indicador"), C("valor", "Valor")], rows, period=_period(start, end))


def _fmtm(v: Decimal) -> str:
    return "R$ " + f"{money(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@report("inadimplencia", "Inadimplência", "financeiro")
def r_delinquency(db, start, end):
    today = local_today()
    rs = db.scalars(select(AccountsReceivable).where(AccountsReceivable.status.in_(("aberto", "parcial")),
                                                     AccountsReceivable.due_date < today).order_by(AccountsReceivable.due_date)).all()
    rows = [{"vencimento": r.due_date, "cliente": r.customer.full_name if r.customer else "",
             "telefone": (r.customer.whatsapp or r.customer.phone or "") if r.customer else "", "descricao": r.description,
             "saldo": r.balance, "atraso": (today - r.due_date).days} for r in rs]
    return ReportData("Inadimplência", [C("vencimento", "Vencimento", "date"), C("cliente", "Cliente"), C("telefone", "Telefone"),
                      C("descricao", "Descrição"), C("saldo", "Saldo", "money"), C("atraso", "Dias", "int")], rows,
                      {"saldo": money(sum((r["saldo"] for r in rows), Decimal("0")))}, period=f"posição em {today:%d/%m/%Y}")


# ------------------------------------------------------------------ Fiscais
def _invoices(db, start, end, statuses):
    return db.scalars(select(FiscalInvoice).where(FiscalInvoice.competence_date.between(start, end),
                                                  FiscalInvoice.status.in_(statuses)).order_by(FiscalInvoice.competence_date)).all()


def _inv_report(title, invs, extra_col=None):
    rows = [{"numero": i.nfse_number or "", "competencia": i.competence_date, "tomador": i.taker_name or "Não identificado",
             "documento": i.taker_document or "", "codigo": i.national_code or "", "valor": i.gross_amount,
             "liquido": i.net_amount, "iss": i.iss_amount, "retido": "Sim" if i.iss_withheld else "Não",
             "ambiente": i.environment, "chave": i.access_key or "", "status": i.status,
             "erro": (i.last_error or "")[:200], "motivo": i.cancel_reason or ""} for i in invs]
    cols = [C("numero", "Número"), C("competencia", "Competência", "date"), C("tomador", "Tomador"), C("documento", "CPF/CNPJ"),
            C("codigo", "Cód. serviço"), C("valor", "Valor serviço", "money"), C("liquido", "Base (após desc. incond.)", "money"),
            C("iss", "ISS estimado", "money"), C("retido", "ISS retido"), C("ambiente", "Ambiente")]
    if extra_col:
        cols.append(extra_col)
    else:
        cols.append(C("chave", "Chave de acesso"))
    return ReportData(title, cols, rows, {"valor": money(sum((r["valor"] for r in rows), Decimal("0"))),
                                          "liquido": money(sum((r["liquido"] for r in rows), Decimal("0")))})


@report("notas_emitidas", "Notas emitidas (autorizadas)", "fiscal")
def r_inv_ok(db, start, end):
    r = _inv_report("Notas fiscais emitidas (autorizadas)", _invoices(db, start, end, ("autorizada",)))
    r.period = _period(start, end)
    return r


@report("notas_canceladas", "Notas canceladas/substituídas", "fiscal")
def r_inv_cancel(db, start, end):
    r = _inv_report("Notas canceladas/substituídas", _invoices(db, start, end, ("cancelada", "substituida")), C("motivo", "Motivo"))
    r.period = _period(start, end)
    return r


@report("notas_rejeitadas", "Notas rejeitadas", "fiscal")
def r_inv_rej(db, start, end):
    r = _inv_report("Notas rejeitadas", _invoices(db, start, end, ("rejeitada",)), C("erro", "Retorno"))
    r.period = _period(start, end)
    return r


@report("faturamento_competencia", "Faturamento por competência", "fiscal")
def r_by_month(db, start, end):
    agg: dict = defaultdict(lambda: {"notas": 0, "valor": Decimal("0"), "iss": Decimal("0")})
    for i in _invoices(db, start, end, ("autorizada",)):
        k = i.competence_date.strftime("%Y-%m")
        agg[k]["notas"] += 1
        agg[k]["valor"] += i.net_amount
        agg[k]["iss"] += i.iss_amount or 0
    rows = [{"competencia": k, **v} for k, v in sorted(agg.items())]
    return ReportData("Faturamento por competência (NFS-e autorizadas)", [C("competencia", "Competência"),
                      C("notas", "Notas", "int"), C("valor", "Valor", "money"), C("iss", "ISS estimado", "money")], rows,
                      {"valor": money(sum((r["valor"] for r in rows), Decimal("0")))}, period=_period(start, end))


@report("faturamento_servico", "Faturamento por serviço", "fiscal")
def r_by_service(db, start, end):
    services = _lookup(db, Service)
    agg: dict = defaultdict(lambda: {"notas": 0, "valor": Decimal("0")})
    for i in _invoices(db, start, end, ("autorizada",)):
        k = (services.get(i.service_id, "Outros"), i.national_code or "")
        agg[k]["notas"] += 1
        agg[k]["valor"] += i.net_amount
    rows = [{"servico": k[0], "codigo": k[1], **v} for k, v in sorted(agg.items(), key=lambda kv: -kv[1]["valor"])]
    return ReportData("Faturamento por serviço", [C("servico", "Serviço"), C("codigo", "Cód. tributação nacional"),
                      C("notas", "Notas", "int"), C("valor", "Valor", "money")], rows, period=_period(start, end))


@report("retencoes", "Retenções", "fiscal")
def r_retentions(db, start, end):
    rows = []
    for i in _invoices(db, start, end, ("autorizada",)):
        ret = dict(i.retentions or {})
        if i.iss_withheld and i.iss_amount:
            ret["iss"] = i.iss_amount
        for k, v in ret.items():
            if v and Decimal(str(v)) > 0:
                rows.append({"tipo": "Sofrida (NFS-e emitida)", "documento": i.nfse_number or "", "data": i.competence_date,
                             "parte": i.taker_name or "", "tributo": k.upper(), "valor": Decimal(str(v))})
    for d in db.scalars(select(FiscalDocument).where(FiscalDocument.issue_date.between(start, end))).all():
        for k, v in (d.retentions or {}).items():
            if v and Decimal(str(v)) > 0:
                rows.append({"tipo": "Efetuada (serviço tomado)", "documento": d.number or "", "data": d.issue_date,
                             "parte": d.issuer_name, "tributo": k.upper(), "valor": Decimal(str(v))})
    return ReportData("Retenções", [C("tipo", "Tipo"), C("documento", "Documento"), C("data", "Data", "date"),
                      C("parte", "Tomador/Prestador"), C("tributo", "Tributo"), C("valor", "Valor", "money")], rows,
                      {"valor": money(sum((r["valor"] for r in rows), Decimal("0")))}, period=_period(start, end))


@report("tributos_estimados", "Tributos estimados", "fiscal")
def r_taxes(db, start, end):
    periods = {f"{d.year}-{d.month:02d}" for d in (start + timedelta(days=i) for i in range((end - start).days + 1))}
    rows = [{"competencia": t.period, "tributo": t.tax, "base": t.base_amount, "aliquota": t.rate, "estimado": t.estimated_amount,
             "final": t.final_amount, "vencimento": t.due_date, "status": t.status}
            for t in db.scalars(select(TaxAssessment).where(TaxAssessment.period.in_(periods)).order_by(TaxAssessment.period, TaxAssessment.tax)).all()]
    return ReportData("Tributos estimados", [C("competencia", "Competência"), C("tributo", "Tributo"), C("base", "Base", "money"),
                      C("aliquota", "Alíquota", "percent"), C("estimado", "Estimado", "money"), C("final", "Validado/Final", "money"),
                      C("vencimento", "Vencimento", "date"), C("status", "Situação")], rows,
                      {"estimado": money(sum((r["estimado"] for r in rows), Decimal("0")))},
                      notes=["Valores ESTIMADOS a partir das regras cadastradas. Confirme a apuração oficial com o contador."],
                      period=_period(start, end))


@report("obrigacoes_pendentes", "Obrigações pendentes", "fiscal")
def r_obligations(db, start, end):
    os_ = db.scalars(select(TaxObligation).where(TaxObligation.status.in_(("pendente", "em_preparacao", "atrasado")))
                     .order_by(TaxObligation.due_date)).all()
    rows = [{"obrigacao": o.name, "referencia": o.reference_period, "prazo": o.due_date, "responsavel": o.responsible or "",
             "status": o.status} for o in os_]
    return ReportData("Obrigações pendentes", [C("obrigacao", "Obrigação"), C("referencia", "Referência"),
                      C("prazo", "Prazo", "date"), C("responsavel", "Responsável"), C("status", "Situação")], rows,
                      period=f"posição em {local_today():%d/%m/%Y}")


@report("documentos_recebidos", "Documentos fiscais recebidos", "fiscal")
def r_docs(db, start, end):
    ds = db.scalars(select(FiscalDocument).where(FiscalDocument.issue_date.between(start, end)).order_by(FiscalDocument.issue_date)).all()
    rows = [{"data": d.issue_date, "tipo": d.doc_type.upper(), "numero": d.number or "", "emitente": d.issuer_name,
             "documento": d.issuer_document or "", "valor": d.amount, "retencoes": d.retention_total,
             "tomado": "Sim" if d.service_taken else "Não"} for d in ds]
    return ReportData("Documentos fiscais recebidos", [C("data", "Emissão", "date"), C("tipo", "Tipo"), C("numero", "Número"),
                      C("emitente", "Emitente"), C("documento", "CPF/CNPJ"), C("valor", "Valor", "money"),
                      C("retencoes", "Retenções", "money"), C("tomado", "Serviço tomado")], rows,
                      {"valor": money(sum((r["valor"] for r in rows), Decimal("0")))}, period=_period(start, end))


@report("receitas_despesas", "Receitas e despesas (escrituração auxiliar)", "fiscal")
def r_ledger(db, start, end):
    cats, ccs, methods = _lookup(db, FinancialCategory), _lookup(db, CostCenter), _lookup(db, PaymentMethod)
    rows = []
    for r in db.scalars(select(AccountsReceivable).where(AccountsReceivable.competence_date.between(start, end),
                                                         AccountsReceivable.status != "cancelado")).all():
        pays = db.scalars(select(FinancialTransaction).where(FinancialTransaction.receivable_id == r.id,
                                                             FinancialTransaction.is_reversal.is_(False),
                                                             FinancialTransaction.reversed.is_(False))).all()
        inv = db.scalar(select(FiscalInvoice).where(FiscalInvoice.receivable_id == r.id, FiscalInvoice.status == "autorizada"))
        rows.append({"tipo": "Receita", "competencia": r.competence_date,
                     "pagamento": max((p.transaction_date for p in pays), default=None), "descricao": r.description,
                     "categoria": cats.get(r.category_id, ""), "centro": ccs.get(r.cost_center_id, ""),
                     "documento": f"NFS-e {inv.nfse_number}" if inv else "", "forma": ", ".join(sorted({methods.get(p.payment_method_id, "") for p in pays})),
                     "valor": r.net_amount})
    for p in db.scalars(select(AccountsPayable).where(AccountsPayable.competence_date.between(start, end),
                                                      AccountsPayable.status != "cancelado")).all():
        pays = db.scalars(select(FinancialTransaction).where(FinancialTransaction.payable_id == p.id,
                                                             FinancialTransaction.is_reversal.is_(False),
                                                             FinancialTransaction.reversed.is_(False))).all()
        rows.append({"tipo": "Despesa", "competencia": p.competence_date,
                     "pagamento": max((t.transaction_date for t in pays), default=None), "descricao": p.description,
                     "categoria": cats.get(p.category_id, ""), "centro": ccs.get(p.cost_center_id, ""), "documento": "",
                     "forma": ", ".join(sorted({methods.get(t.payment_method_id, "") for t in pays})), "valor": -p.amount})
    rows.sort(key=lambda r: (r["competencia"], r["tipo"]))
    return ReportData("Receitas e despesas (escrituração auxiliar)", [C("tipo", "Tipo"), C("competencia", "Competência", "date"),
                      C("pagamento", "Pagamento", "date"), C("descricao", "Descrição"), C("categoria", "Categoria"),
                      C("centro", "Centro de custo"), C("documento", "Documento"), C("forma", "Forma"), C("valor", "Valor", "money")],
                      rows, {"valor": money(sum((r["valor"] for r in rows), Decimal("0")))},
                      notes=["Controle auxiliar gerencial. Não constitui escrituração contábil oficial."], period=_period(start, end))


CATEGORY_PERMS = {"operacional": "reports.operational", "financeiro": "reports.financial", "fiscal": "reports.fiscal"}


def run(db: Session, key: str, start: date, end: date) -> ReportData:
    return REGISTRY[key]["fn"](db, start, end)
