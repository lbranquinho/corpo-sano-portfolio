"""Remoção dos serviços do Corpo Sano (executado pelo desinstalador, como administrador).

Por padrão os DADOS são preservados em ProgramData\\CorpoSano (banco, anexos, backups, configuração),
permitindo reinstalar sem perdas. Com --remove-data 1 tudo é apagado.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path

SERVICE_APP = "CorpoSano"
SERVICE_DB = "CorpoSanoDB"


def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 1, "", "timeout")


def service_state(name: str) -> str | None:
    """Estado do serviço (RUNNING, STOPPED, STOP_PENDING...) ou None se não existir."""
    p = run(["sc.exe", "query", name])
    if p.returncode != 0:
        return None
    for state in ("STOP_PENDING", "START_PENDING", "STOPPED", "RUNNING", "PAUSED"):
        if state in (p.stdout or ""):
            return state
    return "UNKNOWN"


def wait_state(name: str, done: tuple[str | None, ...], timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if service_state(name) in done:
            return True
        time.sleep(2)
    return service_state(name) in done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-dir", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--remove-data", default="0")
    a = ap.parse_args()
    app_dir, data_dir = Path(a.app_dir), Path(a.data_dir)
    winsw = app_dir / "service" / f"{SERVICE_APP}.exe"
    pg_ctl = app_dir / "pgsql" / "bin" / "pg_ctl.exe"
    pgdata = data_dir / "pgdata"

    # 1) sistema: parar e aguardar a parada real (o banco só pode parar depois dele, pois é dependência)
    if service_state(SERVICE_APP) is not None:
        if winsw.exists():
            run([str(winsw), "stopwait"])
        else:
            run(["sc.exe", "stop", SERVICE_APP])
        wait_state(SERVICE_APP, ("STOPPED", None), 60)
        if winsw.exists():
            run([str(winsw), "uninstall"])
        else:
            run(["sc.exe", "delete", SERVICE_APP])
        wait_state(SERVICE_APP, (None,), 30)

    # 2) banco de dados: parar, aguardar e remover o serviço
    if service_state(SERVICE_DB) is not None:
        run(["sc.exe", "stop", SERVICE_DB])
        if not wait_state(SERVICE_DB, ("STOPPED",), 90) and pg_ctl.exists() and pgdata.exists():
            run([str(pg_ctl), "stop", "-D", str(pgdata), "-m", "fast", "-w", "-t", "60"], timeout=90)
            wait_state(SERVICE_DB, ("STOPPED",), 30)
        if pg_ctl.exists():
            run([str(pg_ctl), "unregister", "-N", SERVICE_DB])
        if service_state(SERVICE_DB) is not None:
            run(["sc.exe", "delete", SERVICE_DB])
        wait_state(SERVICE_DB, (None,), 30)

    run(["netsh", "advfirewall", "firewall", "delete", "rule", "name=Corpo Sano"])

    if a.remove_data == "1" and data_dir.exists():
        for _ in range(5):
            shutil.rmtree(data_dir, ignore_errors=True)
            if not data_dir.exists():
                break
            time.sleep(3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
