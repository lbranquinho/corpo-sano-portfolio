"""Agenda inteligente: disponibilidade, conflitos (profissional e sala), intervalos, feriados,
bloqueios, recorrência e transições de status com efeitos integrados (pacote, financeiro, CRM, WhatsApp)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import and_, extract, or_, select
from sqlalchemy.orm import Session

from app.core.database import advisory_lock
from app.core.errors import AppError, Conflict, NotFound
from app.core.settings_store import get_setting
from app.core.utils import add_months, clinic_tz, money, to_local, utcnow
from app.models.catalog import Service
from app.models.clinic import BusinessHour, Holiday, Professional, ProfessionalAvailability, Room, ScheduleBlock
from app.models.clinical import Treatment
from app.models.customer import Customer
from app.models.schedule import Appointment, AppointmentStatusHistory

BLOCKING_STATUSES = ("agendado", "confirmado", "em_atendimento", "concluido")
TRANSITIONS = {
    "confirmar": ({"agendado"}, "confirmado"),
    "iniciar": ({"agendado", "confirmado"}, "em_atendimento"),
    "concluir": ({"agendado", "confirmado", "em_atendimento"}, "concluido"),
    "falta": ({"agendado", "confirmado"}, "falta"),
    "cancelar": ({"agendado", "confirmado"}, "cancelado"),
}


@dataclass
class SlotRequest:
    customer_id: uuid.UUID
    service_id: uuid.UUID
    professional_id: uuid.UUID
    room_id: uuid.UUID | None
    start_at: datetime
    duration_minutes: int | None = None
    price: Decimal | None = None
    discount: Decimal = Decimal("0")
    payment_method_id: uuid.UUID | None = None
    notes: str | None = None
    is_evaluation: bool = False
    package_id: uuid.UUID | None = None


def buffer_for(db: Session, service: Service) -> int:
    return max(int(get_setting(db, "agenda.buffer_minutes") or 0), service.buffer_minutes or 0)


def is_holiday(db: Session, day: date) -> Holiday | None:
    return db.scalar(select(Holiday).where(or_(
        Holiday.date == day,
        and_(Holiday.recurring.is_(True), extract("month", Holiday.date) == day.month, extract("day", Holiday.date) == day.day),
    )).limit(1))


def hours_problems(db: Session, professional_id: uuid.UUID, start: datetime, end: datetime) -> list[str]:
    ls, le = to_local(start), to_local(end)
    if ls.date() != le.date() and not (le.time() == time(0) and le.date() == ls.date() + timedelta(days=1)):
        return ["O atendimento deve começar e terminar no mesmo dia."]
    day = ls.date()
    problems = []
    hol = is_holiday(db, day)
    if hol:
        problems.append(f"{day:%d/%m/%Y} é feriado/dia sem expediente ({hol.name}).")
    bh = db.scalar(select(BusinessHour).where(BusinessHour.weekday == day.weekday()))
    st, et = ls.time(), (le.time() if le.date() == day else time(23, 59, 59))
    if bh is None or not bh.is_open:
        problems.append("A clínica não funciona neste dia da semana.")
    else:
        if st < bh.open_time or et > bh.close_time:
            problems.append(f"Fora do horário de funcionamento ({bh.open_time:%H:%M}–{bh.close_time:%H:%M}).")
        if bh.break_start and bh.break_end and st < bh.break_end and et > bh.break_start:
            problems.append(f"Conflita com o intervalo da clínica ({bh.break_start:%H:%M}–{bh.break_end:%H:%M}).")
    windows = db.scalars(select(ProfessionalAvailability).where(
        ProfessionalAvailability.professional_id == professional_id)).all()
    if windows:
        today_w = [w for w in windows if w.weekday == day.weekday()]
        if not any(w.start_time <= st and et <= w.end_time for w in today_w):
            problems.append("Fora da disponibilidade do profissional neste dia.")
    return problems


def find_conflicts(db: Session, *, professional_id: uuid.UUID, room_id: uuid.UUID | None, start: datetime,
                   end: datetime, buffer: int, exclude_id: uuid.UUID | None = None) -> list[dict]:
    lo, hi = start - timedelta(minutes=buffer), end + timedelta(minutes=buffer)
    who = [Appointment.professional_id == professional_id]
    if room_id:
        who.append(Appointment.room_id == room_id)
    stmt = select(Appointment).where(
        Appointment.status.in_(BLOCKING_STATUSES), Appointment.start_at < hi, Appointment.end_at > lo, or_(*who)
    )
    if exclude_id:
        stmt = stmt.where(Appointment.id != exclude_id)
    out = []
    for a in db.scalars(stmt).all():
        same_prof = a.professional_id == professional_id
        out.append({
            "type": "profissional" if same_prof else "sala",
            "appointment_id": str(a.id),
            "start_at": a.start_at.isoformat(),
            "end_at": a.end_at.isoformat(),
            "message": (f"{a.professional.name} já atende {a.customer.full_name} das "
                        f"{to_local(a.start_at):%H:%M} às {to_local(a.end_at):%H:%M}"
                        if same_prof else
                        f"Sala {a.room.name if a.room else ''} ocupada das {to_local(a.start_at):%H:%M} às {to_local(a.end_at):%H:%M}")
                       + (f" (com intervalo de {buffer} min)" if buffer else ""),
        })
    scope = [ScheduleBlock.professional_id == professional_id,
             and_(ScheduleBlock.professional_id.is_(None), ScheduleBlock.room_id.is_(None))]
    if room_id:
        scope.append(ScheduleBlock.room_id == room_id)
    blocks = db.scalars(select(ScheduleBlock).where(
        ScheduleBlock.start_at < end, ScheduleBlock.end_at > start, or_(*scope))).all()
    for b in blocks:
        out.append({"type": "bloqueio", "block_id": str(b.id), "start_at": b.start_at.isoformat(),
                    "end_at": b.end_at.isoformat(),
                    "message": f"Horário bloqueado ({to_local(b.start_at):%d/%m %H:%M}–{to_local(b.end_at):%H:%M})"
                               + (f": {b.reason}" if b.reason else "")})
    return out


def _load(db: Session, req: SlotRequest) -> tuple[Customer, Service, Professional, Room | None]:
    customer = db.get(Customer, req.customer_id)
    if customer is None or customer.status == "anonimizado":
        raise NotFound("Cliente")
    service = db.get(Service, req.service_id)
    if service is None or not service.is_active:
        raise AppError("Serviço inexistente ou inativo.")
    prof = db.get(Professional, req.professional_id)
    if prof is None or not prof.is_active:
        raise AppError("Profissional inexistente ou inativo.")
    room = None
    if req.room_id:
        room = db.get(Room, req.room_id)
        if room is None or not room.is_active:
            raise AppError("Sala inexistente ou inativa.")
    if service.professionals and prof.id not in {p.id for p in service.professionals}:
        raise AppError(f"{prof.name} não está habilitado(a) para o serviço {service.name}.")
    return customer, service, prof, room


def validate_slot(db: Session, req: SlotRequest, service: Service, *, override_hours: bool,
                  exclude_id: uuid.UUID | None = None) -> tuple[datetime, datetime]:
    if req.start_at.tzinfo is None:
        req.start_at = req.start_at.replace(tzinfo=clinic_tz())
    duration = req.duration_minutes or service.duration_minutes
    if duration < 5 or duration > 600:
        raise AppError("Duração inválida.")
    start = req.start_at
    end = start + timedelta(minutes=duration)
    if not override_hours:
        problems = hours_problems(db, req.professional_id, start, end)
        if problems:
            raise AppError(" ".join(problems), code="fora_do_horario")
    advisory_lock(db, f"prof:{req.professional_id}", f"room:{req.room_id}" if req.room_id else None)
    conflicts = find_conflicts(db, professional_id=req.professional_id, room_id=req.room_id, start=start, end=end,
                               buffer=buffer_for(db, service), exclude_id=exclude_id)
    if conflicts:
        raise Conflict("Conflito de horário: " + conflicts[0]["message"], details=conflicts)
    return start, end


def _history(db: Session, a: Appointment, action: str, from_status: str | None, user_id: uuid.UUID | None,
             reason: str | None = None, old_start: datetime | None = None) -> None:
    db.add(AppointmentStatusHistory(appointment_id=a.id, action=action, from_status=from_status, to_status=a.status,
                                    reason=reason, old_start_at=old_start, new_start_at=a.start_at if old_start else None,
                                    changed_by=user_id))


def create_appointments(db: Session, req: SlotRequest, *, user_id: uuid.UUID | None, override_hours: bool,
                        allow_past: bool, recurrence: str | None = None, occurrences: int = 1,
                        skip_conflicts: bool = False) -> tuple[list[Appointment], list[dict]]:
    from app.services import crm as crm_service
    from app.services import packages as pkg_service
    from app.services import whatsapp as wa

    customer, service, prof, room = _load(db, req)
    if occurrences < 1 or occurrences > 52:
        raise AppError("Recorrência deve ter entre 1 e 52 ocorrências.")
    if recurrence and recurrence not in ("semanal", "quinzenal", "mensal"):
        raise AppError("Recorrência inválida.")
    if req.start_at.tzinfo is None:
        req.start_at = req.start_at.replace(tzinfo=clinic_tz())
    if not allow_past and req.start_at < utcnow() - timedelta(minutes=5):
        raise AppError("Não é possível agendar no passado.")
    starts = [req.start_at]
    local_first = to_local(req.start_at)
    for i in range(1, occurrences if recurrence else 1):
        if recurrence == "semanal":
            starts.append(req.start_at + timedelta(weeks=i))
        elif recurrence == "quinzenal":
            starts.append(req.start_at + timedelta(weeks=2 * i))
        else:
            d = add_months(local_first.date(), i)
            starts.append(datetime.combine(d, local_first.time(), tzinfo=clinic_tz()))
    created, skipped = [], []
    group = uuid.uuid4() if len(starts) > 1 else None
    price = money(req.price if req.price is not None else service.price)
    discount = money(req.discount or 0)
    if req.package_id:
        price, discount = Decimal("0.00"), Decimal("0.00")
    if discount > price:
        raise AppError("Desconto maior que o valor do serviço.")
    for st in starts:
        r = SlotRequest(**{**req.__dict__, "start_at": st})
        try:
            start, end = validate_slot(db, r, service, override_hours=override_hours)
            if req.package_id:
                pkg_service.validate_for_appointment(db, req.package_id, customer_id=customer.id,
                                                     service_id=service.id, start_at=start)
        except AppError as exc:
            if skip_conflicts and len(starts) > 1:
                skipped.append({"start_at": st.isoformat(), "reason": exc.message})
                continue
            if len(starts) > 1:
                exc.message = f"{to_local(st):%d/%m/%Y %H:%M}: {exc.message}"
            raise
        a = Appointment(
            customer_id=customer.id, service_id=service.id, professional_id=prof.id, room_id=room.id if room else None,
            start_at=start, end_at=end, duration_minutes=int((end - start).total_seconds() // 60), price=price,
            discount=discount, payment_method_id=req.payment_method_id, status="agendado", notes=req.notes,
            is_evaluation=req.is_evaluation, package_id=req.package_id, recurrence_id=group, created_by=user_id,
        )
        db.add(a)
        db.flush()
        _history(db, a, "criado", None, user_id)
        created.append(a)
    if not created:
        raise AppError("Nenhum agendamento pôde ser criado: todos os horários estão indisponíveis.", details=skipped)
    crm_service.refresh_stage(db, customer, user_id=user_id)
    for a in created:
        db.refresh(a)
        wa.enqueue(db, customer=customer, purpose="confirmacao", appointment=a,
                   dedupe_key=f"confirmacao:{a.id}", user_id=user_id)
    return created, skipped


def reschedule(db: Session, a: Appointment, *, start_at: datetime, professional_id: uuid.UUID | None,
               room_id: uuid.UUID | None, duration_minutes: int | None, reason: str | None,
               user_id: uuid.UUID | None, override_hours: bool) -> Appointment:
    from app.services import whatsapp as wa

    if a.status not in ("agendado", "confirmado"):
        raise AppError("Só é possível remarcar atendimentos agendados ou confirmados.")
    req = SlotRequest(customer_id=a.customer_id, service_id=a.service_id,
                      professional_id=professional_id or a.professional_id, room_id=room_id,
                      start_at=start_at, duration_minutes=duration_minutes or a.duration_minutes)
    _, service, prof, room = _load(db, req)
    if req.start_at.tzinfo is None:
        req.start_at = req.start_at.replace(tzinfo=clinic_tz())
    if req.start_at < utcnow() - timedelta(minutes=5):
        raise AppError("Não é possível remarcar para o passado.")
    start, end = validate_slot(db, req, service, override_hours=override_hours, exclude_id=a.id)
    if a.package_id:
        from app.services import packages as pkg_service

        pkg_service.validate_for_appointment(db, a.package_id, customer_id=a.customer_id, service_id=a.service_id,
                                             start_at=start, exclude_appointment=a.id)
    old_start, old_status = a.start_at, a.status
    time_changed = start != a.start_at
    a.start_at, a.end_at = start, end
    a.duration_minutes = int((end - start).total_seconds() // 60)
    a.professional_id, a.room_id = prof.id, room.id if room else None
    if time_changed:
        a.status, a.confirmed_at, a.reminder_sent_at = "agendado", None, None
    db.flush()
    _history(db, a, "remarcado" if time_changed else "editado", old_status, user_id, reason,
             old_start if time_changed else None)
    if time_changed:
        db.refresh(a)
        wa.enqueue(db, customer=a.customer, purpose="remarcacao", appointment=a,
                   dedupe_key=f"remarcacao:{a.id}:{int(start.timestamp())}", user_id=user_id)
    return a


def change_status(db: Session, a: Appointment, action: str, *, user_id: uuid.UUID | None,
                  reason: str | None = None) -> Appointment:
    from app.services import crm as crm_service
    from app.services import finance as fin
    from app.services import packages as pkg_service
    from app.services import whatsapp as wa

    if action not in TRANSITIONS:
        raise AppError("Ação inválida.")
    allowed, target = TRANSITIONS[action]
    if a.status not in allowed:
        raise AppError(f"Não é possível '{action}' um atendimento com situação '{a.status}'.")
    now = utcnow()
    if action in ("concluir", "iniciar") and a.start_at > now + timedelta(minutes=30):
        raise AppError("O atendimento ainda não começou; não é possível iniciá-lo/concluí-lo antecipadamente.")
    if action == "falta" and a.start_at > now:
        raise AppError("Só é possível registrar falta após o horário marcado.")
    if action == "cancelar" and not reason:
        raise AppError("Informe o motivo do cancelamento.")
    old = a.status
    a.status = target
    if action == "confirmar":
        a.confirmed_at = now
    elif action == "iniciar":
        if not db.scalar(select(Treatment).where(Treatment.appointment_id == a.id)):
            db.add(Treatment(appointment_id=a.id, customer_id=a.customer_id, professional_id=a.professional_id,
                             service_id=a.service_id, started_at=now, status="em_andamento", created_by=user_id))
    elif action == "concluir":
        a.completed_at = now
        t = db.scalar(select(Treatment).where(Treatment.appointment_id == a.id))
        if t is None:
            db.add(Treatment(appointment_id=a.id, customer_id=a.customer_id, professional_id=a.professional_id,
                             service_id=a.service_id, started_at=min(a.start_at, now), ended_at=now,
                             status="concluido", created_by=user_id))
        else:
            t.ended_at, t.status = now, "concluido"
        db.flush()
        pkg_service.consume(db, a, "atendimento", user_id)
        fin.receivable_for_appointment(db, a, user_id)
    elif action == "falta":
        pkg_service.apply_no_show_rule(db, a, user_id)
    elif action == "cancelar":
        a.cancelled_at, a.cancel_reason = now, reason
        pkg_service.apply_cancellation_rule(db, a, user_id)
    db.flush()
    _history(db, a, action, old, user_id, reason)
    crm_service.refresh_stage(db, a.customer, user_id=user_id)
    if action == "cancelar":
        wa.enqueue(db, customer=a.customer, purpose="cancelamento", appointment=a,
                   dedupe_key=f"cancelamento:{a.id}", user_id=user_id)
    if action == "concluir":
        wa.enqueue(db, customer=a.customer, purpose="agradecimento", appointment=a,
                   dedupe_key=f"agradecimento:{a.id}", user_id=user_id)
    return a


def free_slots(db: Session, *, day: date, service: Service, professional_id: uuid.UUID,
               room_id: uuid.UUID | None, duration_minutes: int | None = None) -> list[str]:
    """Horários livres para agendamento rápido.

    Usa a duração escolhida no agendamento (ou a do serviço) e, além da grade fixa (ex.: de 30 em 30 min),
    oferece o horário exato em que termina cada atendimento/bloqueio do dia, para encaixar o próximo
    logo em seguida (ex.: sessão de 50 min que acaba às 15h50 libera um início às 15h50).
    """
    duration = timedelta(minutes=duration_minutes or service.duration_minutes)
    step = int(get_setting(db, "agenda.slot_minutes") or 30)
    bh = db.scalar(select(BusinessHour).where(BusinessHour.weekday == day.weekday()))
    if bh is None or not bh.is_open or is_holiday(db, day):
        return []
    tz = clinic_tz()
    open_at = datetime.combine(day, bh.open_time, tzinfo=tz)
    close = datetime.combine(day, bh.close_time, tzinfo=tz)
    candidates: set[datetime] = set()
    cursor = open_at
    while cursor + duration <= close:
        candidates.add(cursor)
        cursor += timedelta(minutes=step)
    buffer = buffer_for(db, service)
    who = [Appointment.professional_id == professional_id]
    if room_id:
        who.append(Appointment.room_id == room_id)
    ends = db.scalars(select(Appointment.end_at).where(
        Appointment.status.in_(BLOCKING_STATUSES), Appointment.end_at > open_at, Appointment.end_at < close, or_(*who))).all()
    ends += db.scalars(select(ScheduleBlock.end_at).where(ScheduleBlock.end_at > open_at, ScheduleBlock.end_at < close)).all()
    for e in ends:
        candidates.add(e.astimezone(tz) + timedelta(minutes=buffer))
    out = []
    now = utcnow()
    for start in sorted(candidates):
        end = start + duration
        if end > close or start < now:
            continue
        if not hours_problems(db, professional_id, start, end) and not find_conflicts(
            db, professional_id=professional_id, room_id=room_id, start=start, end=end, buffer=buffer
        ):
            out.append(start.isoformat())
    return out
