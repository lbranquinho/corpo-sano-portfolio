from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.sqlalchemy_url,
    pool_pre_ping=True,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def advisory_lock(db: Session, *keys: object) -> None:
    """Bloqueio transacional do PostgreSQL para serializar operações concorrentes
    (ex.: dois agendamentos simultâneos para o mesmo profissional)."""
    for key in sorted(str(k) for k in keys if k is not None):
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))
