"""Testes contra PostgreSQL real (banco dedicado definido em TEST_DATABASE_URL)."""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest


def _read_env_file() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    out: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


_file_env = _read_env_file()
TEST_DB = os.environ.get("TEST_DATABASE_URL") or _file_env.get("TEST_DATABASE_URL")
if not TEST_DB:
    raise RuntimeError("Defina TEST_DATABASE_URL (PostgreSQL dedicado a testes).")
_tmp = Path(tempfile.mkdtemp(prefix="cs-tests-"))
os.environ.update({
    "DATABASE_URL": TEST_DB,
    "ENVIRONMENT": "test",
    "COOKIE_SECURE": "false",
    "STORAGE_DIR": str(_tmp / "files"),
    "BACKUP_DIR": str(_tmp / "backups"),
    "INITIAL_ADMIN_EMAIL": "",
    "INITIAL_ADMIN_PASSWORD": "",
})
for key in ("SECRET_KEY", "ENCRYPTION_KEYS", "HEALTH_ENCRYPTION_KEYS", "BACKUP_ENCRYPTION_KEY", "PG_DUMP_PATH", "PG_RESTORE_PATH"):
    if key not in os.environ and key in _file_env:
        os.environ[key] = _file_env[key]
if "SECRET_KEY" not in os.environ:
    import base64

    from cryptography.fernet import Fernet

    os.environ["SECRET_KEY"] = "t" * 48
    os.environ["ENCRYPTION_KEYS"] = Fernet.generate_key().decode()
    os.environ["HEALTH_ENCRYPTION_KEYS"] = Fernet.generate_key().decode()
    os.environ["BACKUP_ENCRYPTION_KEY"] = base64.b64encode(os.urandom(32)).decode()

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.utils import clinic_tz, local_today  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.auth import Role, User  # noqa: E402
from app.services.bootstrap import seed_reference_data  # noqa: E402

PASSWORD = "SenhaForte123"
VALID_CPF = "52998224725"
VALID_CPF_2 = "11144477735"
VALID_CNPJ = "11222333000181"


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(cfg, "head")
    yield
    shutil.rmtree(_tmp, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_db():
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with SessionLocal() as db:
        seed_reference_data(db)
        db.commit()
    limiter.reset()
    yield


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def make_user(email: str, role_code: str, professional_id=None, must_change: bool = False) -> User:
    with SessionLocal() as s:
        role = s.query(Role).filter_by(code=role_code).one()
        u = User(name=email.split("@")[0].title(), email=email, password_hash=hash_password(PASSWORD), role_id=role.id,
                 professional_id=professional_id, must_change_password=must_change)
        s.add(u)
        s.commit()
        s.refresh(u)
        return u


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin(client) -> dict:
    make_user("admin@clinica.com.br", "admin")
    return login(client, "admin@clinica.com.br")


def next_weekday_at(hour: int, weekday: int = 0, weeks_ahead: int = 1) -> datetime:
    """Próxima data (no fuso da clínica) com o dia da semana informado (0 = segunda)."""
    d = local_today() + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    d += timedelta(weeks=weeks_ahead - 1)
    return datetime.combine(d, time(hour), tzinfo=clinic_tz())


@pytest.fixture
def setup_basics(client, admin) -> dict:
    """Profissional, sala, serviço e cliente criados pela própria API."""
    h = admin
    prof = client.post("/api/v1/settings/professionals", headers=h, json={"name": "Ana Terapeuta", "color": "#2563EB"}).json()
    prof2 = client.post("/api/v1/settings/professionals", headers=h, json={"name": "Bruno Terapeuta", "color": "#8B5CF6"}).json()
    room = client.post("/api/v1/settings/rooms", headers=h, json={"name": "Sala 1"}).json()
    service = client.post("/api/v1/services", headers=h, json={
        "name": "Massagem relaxante", "duration_minutes": 60, "buffer_minutes": 0, "price": "150.00"}).json()
    r = client.post("/api/v1/customers", headers=h, json={
        "full_name": "Maria José da Silva", "cpf": VALID_CPF, "phone": "(11) 98765-4321", "email": "maria@cliente.com.br",
        "consents": {"whatsapp_transacional": True, "tratamento_dados": True}})
    assert r.status_code == 201, r.text
    return {"h": h, "prof": prof, "prof2": prof2, "room": room, "service": service, "customer": r.json()}


def book(client, b: dict, start: datetime, **extra):
    body = {"customer_id": b["customer"]["id"], "service_id": b["service"]["id"], "professional_id": b["prof"]["id"],
            "room_id": b["room"]["id"], "start_at": start.isoformat(), **extra}
    return client.post("/api/v1/agenda/appointments", headers=b["h"], json=body)
