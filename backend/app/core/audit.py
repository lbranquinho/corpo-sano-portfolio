"""Trilhas de auditoria para operações sensíveis."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.system import AuditLog

# chaves que nunca devem aparecer em logs
_REDACT = {"password", "senha", "token", "access_token", "app_secret", "verify_token", "pfx", "certificate", "secret"}


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if any(r in k.lower() for r in _REDACT) else _clean(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def audit(
    db: Session,
    action: str,
    *,
    user: Any = None,
    entity: str | None = None,
    entity_id: Any = None,
    details: dict | None = None,
    ip: str | None = None,
    sensitive: bool = False,
) -> None:
    db.add(
        AuditLog(
            action=action,
            user_id=getattr(user, "id", None),
            user_name=getattr(user, "name", None),
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=_clean(details) if details else None,
            ip=ip or getattr(user, "_request_ip", None),
            sensitive=sensitive,
        )
    )
