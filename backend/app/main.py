"""Aplicação FastAPI do Corpo Sano."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.deps import client_ip
from app.core.errors import AppError
from app.core.ratelimit import limiter

logger = logging.getLogger("corposano")
settings = get_settings()

CONSTRAINT_MESSAGES = {
    "uq_customers_cpf": "Já existe um cliente com este CPF.",
    "uq_users_email": "Já existe um usuário com este e-mail.",
    "ex_appointments_professional": "Conflito de horário: o profissional já possui atendimento neste período.",
    "ex_appointments_room": "Conflito de horário: a sala já está ocupada neste período.",
    "uq_fiscal_invoices_source_active": "Já existe uma nota fiscal ativa para esta operação.",
    "uq_accounts_receivable_appointment": "Este atendimento já possui conta a receber.",
    "uq_package_sessions_appointment_active": "A sessão deste atendimento já foi baixada do pacote.",
    "uq_cash_closings_account_date": "O fechamento deste dia já foi realizado para esta conta.",
}

FIELD_LABELS = {"value_error": "valor inválido", "missing": "campo obrigatório"}
FRONTEND_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                "font-src 'self' data:; connect-src 'self' https://viacep.com.br; frame-ancestors 'none'; "
                "base-uri 'self'; form-action 'self'; object-src 'none'")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.bootstrap import ensure_initial_admin, seed_reference_data

    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
        seed_reference_data(db)
        created = ensure_initial_admin(db)
        db.commit()
        if created:
            logger.warning("Administrador inicial criado: %s (troca de senha obrigatória)", created.email)
    yield


app = FastAPI(
    title="Corpo Sano API",
    version=settings.version,
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/api/openapi.json",
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/v1/whatsapp/webhook"):
        if not limiter.hit(f"api:{client_ip(request)}", settings.rate_limit_per_minute):
            return JSONResponse({"detail": "Muitas requisições. Aguarde alguns instantes.", "code": "limite"}, status_code=429)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if path.startswith("/api/v1"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif settings.serve_frontend_dir:
        response.headers.setdefault("Content-Security-Policy", FRONTEND_CSP)
    if settings.cookie_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse({"detail": exc.message, "code": exc.code, "details": exc.details}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
        msg = err.get("msg", "valor inválido")
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        errors.append({"field": ".".join(loc), "message": msg})
    first = errors[0] if errors else {"field": "", "message": "Dados inválidos."}
    detail = f"{first['field']}: {first['message']}" if first["field"] else first["message"]
    return JSONResponse({"detail": detail, "code": "validacao", "details": errors}, status_code=422)


@app.exception_handler(IntegrityError)
async def integrity_handler(request: Request, exc: IntegrityError):
    raw = str(exc.orig) if exc.orig else str(exc)
    for name, msg in CONSTRAINT_MESSAGES.items():
        if name in raw:
            return JSONResponse({"detail": msg, "code": "conflito"}, status_code=409)
    logger.warning("IntegrityError: %s", raw.splitlines()[0] if raw else "")
    return JSONResponse({"detail": "Operação viola a integridade dos dados (registro duplicado ou em uso).", "code": "conflito"}, status_code=409)


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception("Erro não tratado em %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Erro interno. A equipe técnica pode consultar os logs.", "code": "erro_interno"}, status_code=500)


@app.get("/api/health", tags=["Sistema"])
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "environment": settings.environment, "version": settings.version}


def _include_routers() -> None:
    from app.api import (
        agenda,
        auth,
        backups,
        clinical,
        crm,
        customers,
        dashboard,
        finance,
        fiscal,
        packages,
        reports,
        search,
        services_catalog,
        settings as settings_api,
        users,
        whatsapp,
    )

    for module in (auth, users, settings_api, customers, services_catalog, agenda, clinical, packages, crm,
                   whatsapp, finance, fiscal, reports, dashboard, search, backups):
        app.include_router(module.router, prefix="/api/v1")


def _mount_frontend() -> None:
    """Instalação local (Windows): a própria aplicação entrega a interface, sem Nginx."""
    folder = settings.serve_frontend_dir
    if not folder:
        return
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    root = Path(folder).resolve()
    index = root / "index.html"
    if not index.is_file():
        logger.warning("SERVE_FRONTEND_DIR sem index.html: %s", root)
        return
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Recurso não encontrado.", "code": "nao_encontrado"}, status_code=404)
        if full_path:
            candidate = (root / full_path).resolve()
            if candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-store"})


_include_routers()
_mount_frontend()
