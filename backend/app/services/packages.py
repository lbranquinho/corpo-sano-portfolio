"""Regras de pacotes: baixa de sessão somente após conclusão (ou regra de falta/cancelamento)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.core.settings_store import get_setting
from app.core.utils import local_today, to_local, utcnow
from app.models.package import Package, PackageSession
from app.models.schedule import Appointment


def lock_package(db: Session, package_id: uuid.UUID) -> Package:
    pkg = db.scalar(select(Package).where(Package.id == package_id).with_for_update(of=Package))
    if pkg is None:
        raise NotFound("Pacote")
    return pkg


def reserved_sessions(db: Session, package_id: uuid.UUID, exclude_appointment: uuid.UUID | None = None) -> int:
    """Agendamentos futuros já vinculados ao pacote (ainda não baixados)."""
    stmt = select(func.count()).select_from(Appointment).where(
        Appointment.package_id == package_id, Appointment.status.in_(("agendado", "confirmado", "em_atendimento"))
    )
    if exclude_appointment:
        stmt = stmt.where(Appointment.id != exclude_appointment)
    return db.scalar(stmt) or 0


def validate_for_appointment(db: Session, package_id: uuid.UUID, *, customer_id: uuid.UUID, service_id: uuid.UUID,
                             start_at: datetime, exclude_appointment: uuid.UUID | None = None) -> Package:
    pkg = lock_package(db, package_id)
    if pkg.customer_id != customer_id:
        raise AppError("O pacote selecionado pertence a outro cliente.")
    if pkg.service_id != service_id:
        raise AppError("O pacote selecionado é de outro serviço.")
    if pkg.status != "ativo":
        raise AppError(f"Pacote não está ativo (situação: {pkg.status}).")
    if pkg.expires_at and to_local(start_at).date() > pkg.expires_at:
        raise AppError(f"O pacote vence em {pkg.expires_at:%d/%m/%Y}, antes da data do agendamento.")
    if pkg.sessions_remaining - reserved_sessions(db, pkg.id, exclude_appointment) <= 0:
        raise AppError("O pacote não possui sessões disponíveis (considerando os agendamentos já reservados).")
    return pkg


def consume(db: Session, appointment: Appointment, reason: str, user_id: uuid.UUID | None) -> PackageSession | None:
    if not appointment.package_id:
        return None
    pkg = lock_package(db, appointment.package_id)
    already = db.scalar(select(PackageSession).where(
        PackageSession.appointment_id == appointment.id, PackageSession.reverted_at.is_(None)))
    if already:
        return already
    if pkg.sessions_remaining <= 0:
        raise AppError("O pacote não possui sessões disponíveis para baixa.")
    if pkg.status not in ("ativo",):
        raise AppError(f"Pacote não está ativo (situação: {pkg.status}).")
    session = PackageSession(package_id=pkg.id, appointment_id=appointment.id, reason=reason, created_by=user_id)
    db.add(session)
    pkg.sessions_used += 1
    if pkg.sessions_used >= pkg.sessions_total:
        pkg.status = "concluido"
    db.flush()
    return session


def revert(db: Session, session_id: uuid.UUID, user_id: uuid.UUID | None) -> PackageSession:
    s = db.get(PackageSession, session_id)
    if s is None or s.reverted_at is not None:
        raise NotFound("Baixa de sessão")
    pkg = lock_package(db, s.package_id)
    s.reverted_at = utcnow()
    s.reverted_by = user_id
    pkg.sessions_used -= 1
    if pkg.status == "concluido":
        pkg.status = "ativo" if not pkg.expires_at or pkg.expires_at >= local_today() else "expirado"
    db.flush()
    return s


def apply_cancellation_rule(db: Session, appointment: Appointment, user_id: uuid.UUID | None) -> PackageSession | None:
    if not appointment.package_id:
        return None
    pkg = db.get(Package, appointment.package_id)
    if pkg and pkg.late_cancel_consumes and appointment.start_at - utcnow() < timedelta(hours=pkg.late_cancel_hours):
        return consume(db, appointment, "cancelamento_tardio", user_id)
    return None


def apply_no_show_rule(db: Session, appointment: Appointment, user_id: uuid.UUID | None) -> PackageSession | None:
    if not appointment.package_id:
        return None
    pkg = db.get(Package, appointment.package_id)
    if pkg and pkg.no_show_consumes:
        return consume(db, appointment, "falta", user_id)
    return None


def expire_packages(db: Session) -> int:
    today = local_today()
    rows = db.scalars(select(Package).where(Package.status == "ativo", Package.expires_at.is_not(None),
                                            Package.expires_at < today)).all()
    for p in rows:
        p.status = "expirado"
    return len(rows)


def package_alerts(db: Session) -> dict[str, list[Package]]:
    low = int(get_setting(db, "packages.low_balance_threshold") or 1)
    days = int(get_setting(db, "packages.expiry_alert_days") or 15)
    today = local_today()
    active = db.scalars(select(Package).where(Package.status == "ativo")).all()
    return {
        "low_balance": [p for p in active if p.sessions_remaining <= low],
        "expiring": [p for p in active if p.expires_at and today <= p.expires_at <= today + timedelta(days=days)],
    }


def default_expiry(purchased: date, validity_days: int | None) -> date | None:
    return purchased + timedelta(days=validity_days) if validity_days else None
