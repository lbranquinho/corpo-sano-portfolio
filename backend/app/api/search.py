"""Pesquisa global (cabeçalho): clientes, agendamentos, notas fiscais e serviços — respeitando permissões."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, has_perm
from app.core.utils import only_digits, to_local, utcnow
from app.models.auth import User
from app.models.catalog import Service
from app.models.customer import Customer
from app.models.fiscal import FiscalInvoice
from app.models.schedule import Appointment
from app.services.customers import scope_condition, search_condition

router = APIRouter(tags=["Pesquisa"])


@router.get("/search")
def global_search(q: str = Query(..., min_length=2, max_length=80), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    results: list[dict] = []
    if has_perm(user, "customers.read"):
        stmt = select(Customer).where(search_condition(q), Customer.status != "anonimizado")
        cond = scope_condition(user)
        if cond is not None:
            stmt = stmt.where(cond)
        for c in db.scalars(stmt.order_by(Customer.name_search).limit(8)).all():
            results.append({"type": "cliente", "id": str(c.id), "title": c.full_name,
                            "subtitle": c.whatsapp or c.phone or "", "url": f"/clientes/{c.id}"})
    if has_perm(user, "agenda.read"):
        stmt = (select(Appointment).join(Customer, Customer.id == Appointment.customer_id)
                .where(search_condition(q), Appointment.start_at >= utcnow(),
                       Appointment.status.in_(("agendado", "confirmado"))))
        if not has_perm(user, "agenda.read_all"):
            stmt = stmt.where(Appointment.professional_id == user.professional_id)
        for a in db.scalars(stmt.order_by(Appointment.start_at).limit(5)).all():
            results.append({"type": "agendamento", "id": str(a.id), "title": f"{a.customer.full_name} — {a.service.name}",
                            "subtitle": to_local(a.start_at).strftime("%d/%m/%Y %H:%M"),
                            "url": f"/agenda?data={to_local(a.start_at).date().isoformat()}&agendamento={a.id}"})
    if has_perm(user, "fiscal.read"):
        digits = only_digits(q)
        conds = [FiscalInvoice.taker_name.ilike(f"%{q}%")]
        if digits:
            conds += [FiscalInvoice.nfse_number == digits, FiscalInvoice.taker_document == digits]
        for i in db.scalars(select(FiscalInvoice).where(or_(*conds)).order_by(FiscalInvoice.created_at.desc()).limit(5)).all():
            results.append({"type": "nota", "id": str(i.id), "title": f"NFS-e {i.nfse_number or '(rascunho)'} — {i.taker_name or ''}",
                            "subtitle": f"{i.status} · R$ {i.gross_amount:.2f}", "url": f"/fiscal/notas/{i.id}"})
    if has_perm(user, "services.read"):
        for s in db.scalars(select(Service).where(Service.name.ilike(f"%{q}%")).limit(5)).all():
            results.append({"type": "servico", "id": str(s.id), "title": s.name, "subtitle": f"{s.duration_minutes} min",
                            "url": "/servicos"})
    return results
