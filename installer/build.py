"""Monta o instalador Windows do Corpo Sano (CorpoSano-Setup-<versão>.exe).

Pré-requisitos na máquina de build (Windows x64):
  - Python 3.12 (o mesmo que será embutido) — execute este script com ele (ou com um venv dele)
  - PostgreSQL 16 instalado (os binários oficiais são copiados de PG_HOME)
  - Node.js (para gerar a interface) e as dependências do frontend instaladas (npm install)
  - Inno Setup 6 (ISCC.exe)

Uso:  python installer/build.py [--pg-home "C:\\Program Files\\PostgreSQL\\16"] [--iscc caminho\\ISCC.exe]
A montagem usa uma pasta de caminho curto (%USERPROFILE%\\.cs-build) para evitar o limite de 260 caracteres do Windows.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"
STAGE_ROOT = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".cs-build"
STAGE = STAGE_ROOT / "stage"
DOWNLOADS = STAGE_ROOT / "downloads"
WINSW_URL = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW.NET461.exe"

PY_EXCLUDE_DIRS = {"Doc", "include", "libs", "tcl", "Scripts", "__pycache__"}
PY_EXCLUDE_LIB = {"test", "idlelib", "tkinter", "turtledemo", "ensurepip", "site-packages", "lib2to3", "__pycache__"}
PY_EXCLUDE_FILES = {"NEWS.txt", "pythonw.exe"}
PG_EXCLUDE = {"pgAdmin 4", "stackbuilder"}


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def copy_python(dst: Path) -> None:
    base = Path(sys.base_prefix)
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Use Python 3.12 para montar o instalador.")
    for item in base.iterdir():
        if item.name in PY_EXCLUDE_DIRS or item.name in PY_EXCLUDE_FILES:
            continue
        if item.is_dir() and item.name == "Lib":
            for sub in item.iterdir():
                if sub.name in PY_EXCLUDE_LIB:
                    continue
                target = dst / "Lib" / sub.name
                if sub.is_dir():
                    shutil.copytree(sub, target, ignore=shutil.ignore_patterns("__pycache__", "test", "tests"))
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(sub, target)
        elif item.is_dir():
            shutil.copytree(item, dst / item.name, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst / item.name)
    (dst / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)


def download(url: str, dest: Path) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"  baixando {url}")
        with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    print(f"  {dest.name} SHA-256 {hashlib.sha256(dest.read_bytes()).hexdigest()}")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg-home", default=r"C:\Program Files\PostgreSQL\16")
    ap.add_argument("--iscc", default=str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"))
    ap.add_argument("--node", default=r"C:\Program Files\nodejs\node.exe")
    ap.add_argument("--skip-frontend", action="store_true")
    a = ap.parse_args()
    pg_home = Path(a.pg_home)
    if not (pg_home / "bin" / "initdb.exe").exists():
        raise SystemExit(f"PostgreSQL não encontrado em {pg_home}")
    iscc = Path(a.iscc)
    if not iscc.exists():
        iscc = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
    if not iscc.exists():
        raise SystemExit("ISCC.exe (Inno Setup 6) não encontrado.")

    step(f"Preparando pasta de montagem {STAGE}")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    step("Python 3.12 (runtime)")
    copy_python(STAGE / "python")

    step("Dependências do backend")
    run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-warn-script-location",
         "--only-binary=:all:", "--target", STAGE / "python" / "Lib" / "site-packages", "-r", ROOT / "backend" / "requirements.txt"])
    for junk in (STAGE / "python" / "Lib" / "site-packages" / "bin",):
        shutil.rmtree(junk, ignore_errors=True)

    step("Código do backend")
    for name in ("app", "alembic"):
        shutil.copytree(ROOT / "backend" / name, STAGE / "app" / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.xsd.bak"))
    shutil.copy2(ROOT / "backend" / "alembic.ini", STAGE / "app" / "alembic.ini")

    step("Interface (build de produção)")
    if not a.skip_frontend:
        run([a.node, ROOT / "frontend" / "node_modules" / "typescript" / "bin" / "tsc", "-b", "--noEmit"], cwd=ROOT / "frontend")
        run([a.node, ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js", "build"], cwd=ROOT / "frontend")
    shutil.copytree(ROOT / "frontend" / "dist", STAGE / "web")

    step("PostgreSQL 16 (binários oficiais)")
    for name in ("bin", "lib", "share"):
        shutil.copytree(pg_home / name, STAGE / "pgsql" / name, ignore=shutil.ignore_patterns(*PG_EXCLUDE))
    for lic in ("server_license.txt", "commandlinetools_3rd_party_licenses.txt"):
        if (pg_home / lic).exists():
            shutil.copy2(pg_home / lic, STAGE / "pgsql" / lic)

    step("Gerenciador de serviço (WinSW)")
    (STAGE / "service").mkdir()
    shutil.copy2(download(WINSW_URL, DOWNLOADS / "WinSW.NET461.exe"), STAGE / "service" / "CorpoSano.exe")

    step("Scripts de instalação, ícone e leia-me")
    shutil.copytree(ROOT / "installer" / "setup", STAGE / "setup", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "installer" / "corposano.ico", STAGE / "corposano.ico")
    shutil.copy2(ROOT / "installer" / "LEIA-ME.txt", STAGE / "LEIA-ME.txt")

    step("Pré-compilação (.pyc) e teste de importação com o runtime embutido")
    py = STAGE / "python" / "python.exe"
    run([py, "-m", "compileall", "-q", "-j", "0", STAGE / "python" / "Lib", STAGE / "app"])
    smoke_env = dict(os.environ, DATABASE_URL="postgresql+psycopg://x:y@localhost:1/z", SECRET_KEY="s" * 48,
                     ENCRYPTION_KEYS="", HEALTH_ENCRYPTION_KEYS="", BACKUP_ENCRYPTION_KEY="", CORPOSANO_ENV_FILE="nao-existe.env",
                     SERVE_FRONTEND_DIR=str(STAGE / "web"))
    from cryptography.fernet import Fernet  # noqa: PLC0415

    smoke_env["ENCRYPTION_KEYS"] = Fernet.generate_key().decode()
    smoke_env["HEALTH_ENCRYPTION_KEYS"] = Fernet.generate_key().decode()
    smoke_env["BACKUP_ENCRYPTION_KEY"] = "A" * 43 + "="
    run([py, "-c", "import psycopg, lxml.etree, cryptography, argon2, reportlab, openpyxl, app.main, app.local_server; "
                   "print('  runtime OK:', psycopg.pq.__impl__, len(app.main.app.routes), 'rotas')"],
        cwd=STAGE / "app", env=smoke_env)

    size = sum(f.stat().st_size for f in STAGE.rglob("*") if f.is_file())
    print(f"  conteúdo montado: {size / 1024 / 1024:.0f} MB")

    step("Compilando o instalador (Inno Setup)")
    out_dir = ROOT / "entrega"
    out_dir.mkdir(exist_ok=True)
    run([iscc, "/Q", f"/DStageDir={STAGE}", f"/DOutputDir={out_dir}", f"/DAppVersion={VERSION}",
         ROOT / "installer" / "corposano.iss"])
    exe = out_dir / f"CorpoSano-Setup-{VERSION}.exe"
    print(f"\nInstalador gerado: {exe} ({exe.stat().st_size / 1024 / 1024:.0f} MB)")
    print(f"SHA-256: {hashlib.sha256(exe.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
