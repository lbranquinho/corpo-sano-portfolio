"""Servidor único da instalação local (Windows).

Um só processo: aplica as migrations, inicia as rotinas do worker em segundo plano
(fila do WhatsApp, lembretes, backups diários...) e serve API + interface com o Uvicorn.

    python -m app.local_server        (configuração lida de CORPOSANO_ENV_FILE)
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("corposano.local")
BACKEND = Path(__file__).resolve().parents[1]


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")
    log.info("Banco de dados atualizado (migrations aplicadas).")


def worker_loop(stop: threading.Event, interval: int) -> None:
    from app.worker import run_cycle

    last_daily: dict = {}
    stop.wait(15)  # deixa a API subir primeiro
    while not stop.is_set():
        try:
            run_cycle(last_daily)
        except Exception:  # noqa: BLE001 — o worker nunca derruba o servidor
            log.exception("Falha no ciclo de rotinas")
        stop.wait(interval)


def setup() -> None:
    """Usado pelo instalador: migrations, dados de referência e administrador inicial."""
    from app.core.database import SessionLocal
    from app.services.bootstrap import ensure_initial_admin, seed_reference_data

    migrate()
    with SessionLocal() as db:
        seed_reference_data(db)
        user = ensure_initial_admin(db)
        db.commit()
    log.info("Dados de referência aplicados%s.", f"; administrador {user.email} criado" if user else "")


def main() -> None:
    import sys

    import uvicorn

    from app.core.config import get_settings

    if "--setup" in sys.argv:
        setup()
        return
    settings = get_settings()
    migrate()
    stop = threading.Event()
    threading.Thread(target=worker_loop, args=(stop, settings.worker_interval_seconds), daemon=True,
                     name="corposano-worker").start()
    log.info("Corpo Sano disponível em http://%s:%s", "localhost" if settings.local_host in ("0.0.0.0", "::") else
             settings.local_host, settings.local_port)
    try:
        uvicorn.run("app.main:app", host=settings.local_host, port=settings.local_port, log_level="info",
                    proxy_headers=False, access_log=False)
    finally:
        stop.set()


if __name__ == "__main__":
    main()
