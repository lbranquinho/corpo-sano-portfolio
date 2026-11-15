from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import has_perm, require, require_any
from app.core.errors import AppError, Forbidden, NotFound
from app.core.utils import day_bounds, local_today
from app.models.auth import User
from app.models.catalog import Service
from app.models.clinic import ScheduleBlock
from app.models.finance import AccountsReceivable
from app.models.schedule import Appointment, AppointmentStatusHistory
from app.schemas.common import ORM, Money
from app.services import agenda as svc
from app.services import finance as fin

router = APIRouter(prefix="/agenda", tags=["Agenda"])


class AppointmentIn(BaseModel):
    customer_id: uuid.UUID
    service_id: uuid.UUID
    professional_id: uuid.UUID
    room_id: uuid.UUID | None = None
    start_at: datetime
    duration_minutes: int | None = Field(default=None, ge=5, le=600)
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    payment_method_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)
    is_evaluation: bool = False
    package_id: uuid.UUID | None = None
    recurrence: str | None = Field(default=None, pattern=r"^(semanal|quinzenal|mensal)$")
    occurrences: int = Field(default=1, ge=1, le=52)
    skip_conflicts: bool = False
    override_hours: bool = False


class AppointmentUpdate(BaseModel):
    start_at: datetime
    professional_id: uuid.UUID
    room_id: uuid.UUID | None = None
    duration_minutes: int = Field(ge=5, le=600)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    payment_method_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=300)
    override_hours: bool = False


class PaymentNow(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_method_id: uuid.UUID
    account_id: uuid.UUID | None = None


class StatusIn(BaseModel):
    action: str = Field(pattern=r"^(confirmar|iniciar|concluir|falta|cancelar)$")
    reason: str | None = Field(default=None, max_length=300)
    payment: PaymentNow | None = None


class AppointmentOut(ORM):
    id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str = ""
    customer_phone: str | None = None
    service_id: uuid.UUID
    service_name: str = ""
    professional_id: uuid.UUID
    professional_name: str = ""
    professional_color: str = "#2563EB"
    room_id: uuid.UUID | None
    room_name: str | None = None
    start_at: datetime
    end_at: datetime
    duration_minutes: int
    price: Money
    discount: Money
    payment_method_id: uuid.UUID | None
    status: str
    notes: str | None
    is_evaluation: bool
    package_id: uuid.UUID | None
    recurrence_id: uuid.UUID | None
    cancel_reason: str | None
    receivable_id: uuid.UUID | None = None
    receivable_status: str | None = None


class BlockIn(BaseModel):
    professional_id: uuid.UUID | None = None
    room_id: uuid.UUID | None = None
    start_at: datetime
    end_at: datetime
    reason: str | None = Field(default=None, max_length=200)


class BlockOut(ORM):
    id: uuid.UUID
    professional_id: uuid.UUID | None
    room_id: uuid.UUID | None
    start_at: datetime
    end_at: datetime
    reason: str | None


def _out(db: Session, a: Appointment, with_finance: bool = True) -> AppointmentOut:
    o = AppointmentOut.model_validate(a)
    o.customer_name, o.customer_phone = a.customer.full_name, a.customer.whatsapp or a.customer.phone
    o.service_name = a.service.name
    o.professional_name, o.professional_color = a.professional.name, a.professional.color
    o.room_name = a.room.name if a.room else None
    if with_finance:
        r = db.scalar(select(AccountsReceivable).where(AccountsReceivable.appointment_id == a.id,
                                                       AccountsReceivable.status != "cancelado"))
        if r:
            o.receivable_id, o.receivable_status = r.id, r.status
    return o


def _check_access(user: User, a: Appointment) -> None:
    if not has_perm(user, "agenda.read_all") and a.professional_id != user.professional_id:
        raise Forbidden("Agendamento de outro profissional.")


def _get(db: Session, user: User, appointment_id: uuid.UUID) -> Appointment:
    a = db.get(Appointment, appointment_id)
    if a is None:
        raise NotFound("Agendamento")
    _check_access(user, a)
    return a


@router.get("/appointments", response_model=list[AppointmentOut])
def list_appointments(
    start: date, end: date,
    professional_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("agenda.read")),
):
    if (end - start).days > 62:
        raise AppError("Intervalo máximo de 62 dias.")
    lo, _ = day_bounds(start)
    _, hi = day_bounds(end)
    stmt = select(Appointment).where(Appointment.start_at >= lo, Appointment.start_at < hi)
    if not has_perm(user, "agenda.read_all"):
        if not user.professional_id:
            return []
        stmt = stmt.where(Appointment.professional_id == user.professional_id)
    elif professional_id:
        stmt = stmt.where(Appointment.professional_id == professional_id)
    if room_id:
        stmt = stmt.where(Appointment.room_id == room_id)
    if status:
        stmt = stmt.where(Appointment.status.in_(status.split(",")))
    if customer_id:
        stmt = stmt.where(Appointment.customer_id == customer_id)
    rows = db.scalars(stmt.order_by(Appointment.start_at)).all()
    fin_ok = has_perm(user, "finance.read") or has_perm(user, "finance.payments")
    return [_out(db, a, fin_ok) for a in rows]


@router.get("/appointments/{appointment_id}")
def get_appointment(appointment_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("agenda.read"))):
    a = _get(db, user, appointment_id)
    history = db.scalars(select(AppointmentStatusHistory).where(AppointmentStatusHistory.appointment_id == a.id)
                         .order_by(AppointmentStatusHistory.changed_at)).all()
    fin_ok = has_perm(user, "finance.read") or has_perm(user, "finance.payments")
    return {
        "appointment": _out(db, a, fin_ok).model_dump(mode="json"),
        "history": [{"action": h.action, "from_status": h.from_status, "to_status": h.to_status, "reason": h.reason,
                     "old_start_at": h.old_start_at, "new_start_at": h.new_start_at, "changed_at": h.changed_at}
                    for h in history],
    }


@router.post("/appointments", status_code=201)
def create_appointment(data: AppointmentIn, db: Session = Depends(get_db), user: User = Depends(require("agenda.write"))):
    override = data.override_hours and has_perm(user, "agenda.override")
    if data.override_hours and not override:
        raise Forbidden("Sem permissão para agendar fora do horário de funcionamento.")
    req = svc.SlotRequest(
        customer_id=data.customer_id, service_id=data.service_id, professional_id=data.professional_id,
        room_id=data.room_id, start_at=data.start_at, duration_minutes=data.duration_minutes, price=data.price,
        discount=data.discount, payment_method_id=data.payment_method_id, notes=data.notes,
        is_evaluation=data.is_evaluation, package_id=data.package_id,
    )
    created, skipped = svc.create_appointments(
        db, req, user_id=user.id, override_hours=override, allow_past=override, recurrence=data.recurrence,
        occurrences=data.occurrences, skip_conflicts=data.skip_conflicts,
    )
    audit(db, "agendamento_criado", user=user, entity="appointment", entity_id=created[0].id,
          details={"quantidade": len(created), "ignorados": len(skipped)})
    db.commit()
    return {
        "message": f"{len(created)} agendamento(s) criado(s)." + (f" {len(skipped)} horário(s) ignorado(s) por conflito." if skipped else ""),
        "created": [_out(db, a, False).model_dump(mode="json") for a in created],
        "skipped": skipped,
    }


@router.put("/appointments/{appointment_id}", response_model=AppointmentOut)
def update_appointment(appointment_id: uuid.UUID, data: AppointmentUpdate, db: Session = Depends(get_db),
                       user: User = Depends(require("agenda.write"))):
    a = _get(db, user, appointment_id)
    override = data.override_hours and has_perm(user, "agenda.override")
    if a.status not in ("agendado", "confirmado"):
        raise AppError("Somente agendamentos ativos podem ser editados.")
    if data.discount > data.price:
        raise AppError("Desconto maior que o valor.")
    if not a.package_id:
        a.price, a.discount = data.price, data.discount
    a.payment_method_id, a.notes = data.payment_method_id, data.notes
    svc.reschedule(db, a, start_at=data.start_at, professional_id=data.professional_id, room_id=data.room_id,
                   duration_minutes=data.duration_minutes, reason=data.reason, user_id=user.id, override_hours=override)
    audit(db, "agendamento_alterado", user=user, entity="appointment", entity_id=a.id)
    db.commit()
    db.refresh(a)
    return _out(db, a)


@router.post("/appointments/{appointment_id}/status", response_model=AppointmentOut)
def change_status(appointment_id: uuid.UUID, data: StatusIn, db: Session = Depends(get_db),
                  user: User = Depends(require_any("agenda.write", "clinical.write"))):
    a = _get(db, user, appointment_id)
    # massoterapeuta (sem agenda.write) pode iniciar/concluir os próprios atendimentos
    if not has_perm(user, "agenda.write") and data.action not in ("iniciar", "concluir"):
        raise Forbidden()
    svc.change_status(db, a, data.action, user_id=user.id, reason=data.reason)
    if data.payment and data.action == "concluir":
        if not has_perm(user, "finance.payments"):
            raise Forbidden("Sem permissão para registrar pagamentos.")
        r = db.scalar(select(AccountsReceivable).where(AccountsReceivable.appointment_id == a.id,
                                                       AccountsReceivable.status != "cancelado"))
        if r is None:
            raise AppError("Este atendimento não gera cobrança (pacote ou valor zero).")
        fin.register_receipt(db, r, amount=data.payment.amount, payment_date=local_today(),
                             payment_method_id=data.payment.payment_method_id, account_id=data.payment.account_id,
                             user_id=user.id)
    audit(db, f"agendamento_{data.action}", user=user, entity="appointment", entity_id=a.id,
          details={"motivo": data.reason, "pagamento": bool(data.payment)})
    db.commit()
    db.refresh(a)
    return _out(db, a)


@router.get("/availability")
def availability(day: date, service_id: uuid.UUID, professional_id: uuid.UUID, room_id: uuid.UUID | None = None,
                 db: Session = Depends(get_db), user: User = Depends(require("agenda.read"))):
    service = db.get(Service, service_id)
    if service is None:
        raise NotFound("Serviço")
    return {"day": day, "slots": svc.free_slots(db, day=day, service=service, professional_id=professional_id,
                                                room_id=room_id)}


@router.post("/check")
def check_slot(data: AppointmentIn, db: Session = Depends(get_db), user: User = Depends(require("agenda.read"))):
    """Pré-validação usada pelo formulário (não grava)."""
    service = db.get(Service, data.service_id)
    if service is None:
        raise NotFound("Serviço")
    from datetime import timedelta

    from app.core.utils import clinic_tz

    start = data.start_at if data.start_at.tzinfo else data.start_at.replace(tzinfo=clinic_tz())
    end = start + timedelta(minutes=data.duration_minutes or service.duration_minutes)
    problems = svc.hours_problems(db, data.professional_id, start, end)
    conflicts = svc.find_conflicts(db, professional_id=data.professional_id, room_id=data.room_id, start=start, end=end,
                                   buffer=svc.buffer_for(db, service))
    return {"ok": not problems and not conflicts, "hours_problems": problems, "conflicts": conflicts}


# ---------------------------------------------------------------- Bloqueios
@router.get("/blocks", response_model=list[BlockOut])
def list_blocks(start: date, end: date, db: Session = Depends(get_db), user: User = Depends(require("agenda.read"))):
    lo, _ = day_bounds(start)
    _, hi = day_bounds(end)
    return db.scalars(select(ScheduleBlock).where(ScheduleBlock.start_at < hi, ScheduleBlock.end_at > lo)
                      .order_by(ScheduleBlock.start_at)).all()


@router.post("/blocks", response_model=BlockOut, status_code=201)
def create_block(data: BlockIn, db: Session = Depends(get_db),
                 user: User = Depends(require_any("agenda.settings", "agenda.write"))):
    if data.end_at <= data.start_at:
        raise AppError("O fim do bloqueio deve ser posterior ao início.")
    existing = svc.find_conflicts(db, professional_id=data.professional_id or uuid.UUID(int=0), room_id=data.room_id,
                                  start=data.start_at, end=data.end_at, buffer=0) if (data.professional_id or data.room_id) else []
    existing = [c for c in existing if c["type"] != "bloqueio"]
    if not data.professional_id and not data.room_id:
        lo, hi = data.start_at, data.end_at
        n = db.scalar(select(Appointment.id).where(Appointment.status.in_(svc.BLOCKING_STATUSES),
                                                   Appointment.start_at < hi, Appointment.end_at > lo).limit(1))
        if n:
            raise AppError("Existem agendamentos neste período. Remarque-os antes de bloquear a clínica.")
    if existing:
        raise AppError("Existem agendamentos neste período: " + existing[0]["message"])
    b = ScheduleBlock(**data.model_dump(), created_by=user.id)
    db.add(b)
    audit(db, "bloqueio_criado", user=user, entity="schedule_block", details=data.model_dump(mode="json"))
    db.commit()
    db.refresh(b)
    return b


@router.delete("/blocks/{block_id}")
def delete_block(block_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(require_any("agenda.settings", "agenda.write"))):
    b = db.get(ScheduleBlock, block_id)
    if b is None:
        raise NotFound("Bloqueio")
    db.delete(b)
    audit(db, "bloqueio_removido", user=user, entity="schedule_block", entity_id=block_id)
    db.commit()
    return {"message": "Bloqueio removido."}
