"""Worker de tarefas em segundo plano (processo separado da API).

- Fila de envio do WhatsApp (tentativas controladas)
- Lembretes de agendamento e mensagens de aniversário
- Expiração de pacotes, clientes inativos (CRM), obrigações atrasadas
- Geração mensal do calendário de obrigações
- Backup diário criptografado com retenção
A falha de uma tarefa não interrompe as demais.
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.utils import local_now

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("corposano.worker")
_running = True


def _stop(*_):  # noqa: ANN002
    global _running
    _running = False


def _task(name: str, fn) -> None:  # noqa: ANN001
    with SessionLocal() as db:
        try:
            result = fn(db)
            db.commit()
            if result:
                log.info("%s: %s", name, result)
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("Tarefa %s falhou", name)


def run_cycle(last_daily: dict) -> None:
    from app.services import backup, crm, packages, taxes, whatsapp

    _task("whatsapp_lembretes", whatsapp.schedule_reminders)
    _task("whatsapp_aniversarios", whatsapp.schedule_birthdays)
    _task("whatsapp_fila", whatsapp.process_queue)
    today = local_now().date()
    if last_daily.get("date") != today:
        _task("pacotes_expirados", packages.expire_packages)
        _task("crm_inativos", crm.mark_inactive_customers)
        _task("obrigacoes_atrasadas", taxes.mark_late_obligations)

        def _gen(db):  # noqa: ANN001
            from sqlalchemy import select

            from app.models.fiscal import TaxCompanySettings

            s = db.scalar(select(TaxCompanySettings).limit(1))
            if s and s.tax_regime:
                return taxes.generate_obligations(db, f"{today.year}-{today.month:02d}")
            return 0

        _task("obrigacoes_mes", _gen)
        last_daily["date"] = today

    def _backup(db):  # noqa: ANN001
        if backup.due_for_daily(db):
            rec = backup.run_backup(db, "automatico")
            return f"backup {rec.status}"
        return None

    _task("backup_diario", _backup)


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    interval = get_settings().worker_interval_seconds
    log.info("Worker iniciado (intervalo %ss)", interval)
    last_daily: dict = {}
    while _running:
        started = datetime.now()
        run_cycle(last_daily)
        elapsed = (datetime.now() - started).total_seconds()
        for _ in range(max(1, int(interval - elapsed))):
            if not _running:
                break
            time.sleep(1)
    log.info("Worker finalizado")


if __name__ == "__main__":
    main()
