"""Configuração pós-instalação do Corpo Sano no Windows (executado pelo instalador, como administrador).

- Gera as chaves de segurança (apenas na primeira instalação; atualizações preservam o arquivo)
- Cria o banco PostgreSQL embutido e o registra como serviço "CorpoSanoDB"
- Aplica as migrations, cria os dados de referência e o administrador inicial
- Registra o serviço "CorpoSano" (API + interface + rotinas) e aguarda o sistema responder

Uso: python instalar.py --app-dir "C:\\Program Files\\Corpo Sano" --data-dir "C:\\ProgramData\\CorpoSano" --params arquivo.txt
O arquivo de parâmetros (gerado pelo instalador e apagado em seguida) contém linhas chave=valor:
admin_name, admin_email, admin_password, port, mirror_dir, firewall (0/1).
Senhas nunca são gravadas no log.
"""
from __future__ import annotations

import argparse
import base64
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SERVICE_APP = "CorpoSano"
SERVICE_DB = "CorpoSanoDB"
NETWORK_SERVICE_SID = "*S-1-5-20"
ADMINS_SID = "*S-1-5-32-544"
SYSTEM_SID = "*S-1-5-18"
LOG: Path | None = None


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _decode(data: bytes | None, fallback: str) -> str:
    if not data:
        return ""
    try:
        text = data.decode("utf-8")  # Python (PYTHONUTF8=1) e saídas somente ASCII
    except UnicodeDecodeError:
        text = data.decode(fallback, errors="replace")
    return text.replace("\r\n", "\n")


def run(cmd: list[str], *, check: bool = True, env: dict | None = None, cwd: str | None = None, quiet: bool = False,
        enc: str = "oem") -> subprocess.CompletedProcess:
    """enc: codificação da saída quando não for UTF-8 — 'oem' (sc, netsh, icacls) ou 'mbcs' (PostgreSQL)."""
    if not quiet:
        log("> " + " ".join(c if " " not in c else f'"{c}"' for c in cmd))
    p = subprocess.run(cmd, capture_output=True, env=env, cwd=cwd,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    p.stdout, p.stderr = _decode(p.stdout, enc), _decode(p.stderr, enc)
    out = p.stdout + p.stderr
    if out.strip() and not quiet:
        log(out.strip()[-3000:])
    if check and p.returncode != 0:
        raise RuntimeError(f"Comando falhou ({p.returncode}): {cmd[0]}")
    return p


def read_params(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v
    return out


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def write_env(path: Path, env: dict[str, str]) -> None:
    lines = ["# Corpo Sano — configuração da instalação local (gerado pelo instalador).",
             "# CONFIDENCIAL: contém chaves de criptografia. Guarde uma cópia em local seguro, fora deste computador.",
             "# Sem BACKUP_ENCRYPTION_KEY os backups não podem ser restaurados."]
    lines += [f"{k}={v}" for k, v in env.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # somente Administradores e SYSTEM podem ler
    run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{ADMINS_SID}:F", f"{SYSTEM_SID}:F"], quiet=True)


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def current_user_sid() -> str | None:
    p = run(["whoami", "/user", "/fo", "csv", "/nh"], check=False, quiet=True)
    sid = (p.stdout or "").strip().split(",")[-1].strip().strip('"')
    return sid if sid.startswith("S-1-") else None


def service_exists(name: str) -> bool:
    return run(["sc.exe", "query", name], check=False, quiet=True).returncode == 0


def wait_service_stopped(name: str, timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = run(["sc.exe", "query", name], check=False, quiet=True)
        if p.returncode != 0 or ("STOPPED" in p.stdout and "STOP_PENDING" not in p.stdout):
            return
        time.sleep(2)
    log(f"AVISO: o serviço {name} não parou em {timeout}s.")


def wait_service_deleted(name: str, timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline and service_exists(name):
        time.sleep(1)


def wait_postgres(bin_dir: Path, port: int, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if run([str(bin_dir / "pg_isready.exe"), "-h", "localhost", "-p", str(port)], check=False, quiet=True).returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError("O banco de dados não respondeu a tempo.")


def setup_postgres(app_dir: Path, data_dir: Path, env: dict[str, str]) -> None:
    bin_dir = app_dir / "pgsql" / "bin"
    pgdata = data_dir / "pgdata"
    port = int(env["PG_PORT"])
    if not (pgdata / "PG_VERSION").exists():
        log("Criando o banco de dados (initdb)...")
        pgdata.mkdir(parents=True, exist_ok=True)
        # o initdb executa com token restrito (sem o grupo Administradores): o usuário precisa de acesso explícito
        sid = current_user_sid()
        if sid:
            run(["icacls", str(pgdata), "/grant", f"*{sid}:(OI)(CI)F", "/Q"], quiet=True)
        # arquivo temporário na pasta do usuário: o initdb (token restrito) não lê a pasta protegida de dados
        fd, tmp = tempfile.mkstemp(prefix="cs-pg-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(env["PG_SUPERUSER_PASSWORD"])
        pwfile = Path(tmp)
        try:
            run([str(bin_dir / "initdb.exe"), "-D", str(pgdata), "-U", "postgres", f"--pwfile={pwfile}", "-E", "UTF8",
                 "--no-locale", "--auth-host=scram-sha-256", "--auth-local=scram-sha-256"], enc="mbcs")
        finally:
            pwfile.unlink(missing_ok=True)
        with open(pgdata / "postgresql.conf", "a", encoding="utf-8") as f:
            f.write(f"\n# Corpo Sano\nport = {port}\nlisten_addresses = 'localhost'\n"
                    "logging_collector = on\nlog_directory = 'log'\nlog_rotation_age = 7d\n")
    run(["icacls", str(pgdata), "/grant", f"{NETWORK_SERVICE_SID}:(OI)(CI)F", "/T", "/Q"], quiet=True)
    if not service_exists(SERVICE_DB):
        log("Registrando o serviço do banco de dados...")
        run([str(bin_dir / "pg_ctl.exe"), "register", "-N", SERVICE_DB, "-D", str(pgdata), "-S", "auto",
             "-U", "NT AUTHORITY\\NetworkService"], enc="mbcs")
        run(["sc.exe", "description", SERVICE_DB, "Corpo Sano — banco de dados PostgreSQL"], check=False, quiet=True)
        run(["sc.exe", "failure", SERVICE_DB, "reset=", "86400", "actions=", "restart/10000/restart/30000/restart/60000"],
            check=False, quiet=True)
    run(["sc.exe", "start", SERVICE_DB], check=False)
    wait_postgres(bin_dir, port)
    log("Banco de dados em execução.")

    import psycopg
    from psycopg import sql

    su = dict(host="localhost", port=port, user="postgres", password=env["PG_SUPERUSER_PASSWORD"], autocommit=True)
    with psycopg.connect(dbname="postgres", **su) as conn:
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'corposano'").fetchone():
            conn.execute(sql.SQL("CREATE ROLE corposano LOGIN PASSWORD {}").format(sql.Literal(env["DB_PASSWORD"])))
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = 'corposano'").fetchone():
            conn.execute("CREATE DATABASE corposano OWNER corposano ENCODING 'UTF8' TEMPLATE template0")
    with psycopg.connect(dbname="corposano", **su) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")


def winsw(app_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run([str(app_dir / "service" / f"{SERVICE_APP}.exe"), *args], check=check)


def write_service_xml(app_dir: Path, data_dir: Path, env_file: Path) -> None:
    xml = f"""<service>
  <id>{SERVICE_APP}</id>
  <name>Corpo Sano</name>
  <description>Corpo Sano — sistema de gestão (interface, API e rotinas automáticas)</description>
  <executable>{app_dir / 'python' / 'python.exe'}</executable>
  <arguments>-m app.local_server</arguments>
  <workingdirectory>{app_dir / 'app'}</workingdirectory>
  <env name="CORPOSANO_ENV_FILE" value="{env_file}"/>
  <env name="PYTHONUTF8" value="1"/>
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>
  <depend>{SERVICE_DB}</depend>
  <onfailure action="restart" delay="10 sec"/>
  <onfailure action="restart" delay="30 sec"/>
  <onfailure action="restart" delay="60 sec"/>
  <resetfailure>1 hour</resetfailure>
  <stoptimeout>20 sec</stoptimeout>
  <logpath>{data_dir / 'logs'}</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>5</keepFiles>
  </log>
</service>
"""
    (app_dir / "service" / f"{SERVICE_APP}.xml").write_text(xml, encoding="utf-8")


def wait_http(port: int, timeout: int = 180) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
    raise RuntimeError(f"O sistema não respondeu em {url}. Consulte os logs em ProgramData\\CorpoSano\\logs.")


def main() -> int:
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-dir", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--params", required=True)
    a = ap.parse_args()
    app_dir, data_dir = Path(a.app_dir), Path(a.data_dir)
    for sub in ("logs", "files", "backups"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    # dados acessíveis somente a Administradores e SYSTEM (ProgramData permite leitura a usuários comuns)
    run(["icacls", str(data_dir), "/inheritance:r", "/grant:r", f"{ADMINS_SID}:(OI)(CI)F", f"{SYSTEM_SID}:(OI)(CI)F",
         "/Q"], quiet=True)
    LOG = data_dir / "logs" / "instalacao.log"
    params = read_params(Path(a.params))
    env_file = data_dir / "corposano.env"
    sys.path.insert(0, str(app_dir / "app"))
    existing_db = (data_dir / "pgdata" / "PG_VERSION").exists()
    log(f"=== Corpo Sano — configuração ({'atualização' if existing_db else 'nova instalação'}) ===")

    env = read_env(env_file)
    if not env.get("SECRET_KEY"):  # chaves geradas uma única vez e preservadas nas atualizações
        from cryptography.fernet import Fernet

        pg_port = next(p for p in range(5544, 5600) if port_free(p))
        env = {
            "ENVIRONMENT": "local",
            "PG_PORT": str(pg_port),
            "PG_SUPERUSER_PASSWORD": secrets.token_urlsafe(24),
            "DB_PASSWORD": secrets.token_urlsafe(24),
            "SECRET_KEY": secrets.token_urlsafe(48),
            "ENCRYPTION_KEYS": Fernet.generate_key().decode(),
            "HEALTH_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
            "BACKUP_ENCRYPTION_KEY": base64.b64encode(os.urandom(32)).decode(),
        }
    port = int(params.get("port") or env.get("LOCAL_PORT") or 8080)
    env.update({
        "DATABASE_URL": f"postgresql+psycopg://corposano:{env['DB_PASSWORD']}@localhost:{env['PG_PORT']}/corposano",
        "COOKIE_SECURE": "false",
        # sem proxy reverso na instalação local: nunca confiar em X-Forwarded-For/X-Real-IP
        # (senão um computador da rede poderia informar IP falso e driblar o limite de tentativas)
        "TRUSTED_PROXIES": "",
        "LOCAL_HOST": "0.0.0.0",
        "LOCAL_PORT": str(port),
        "PUBLIC_BASE_URL": f"http://localhost:{port}",
        "SERVE_FRONTEND_DIR": str(app_dir / "web"),
        "STORAGE_DIR": str(data_dir / "files"),
        "BACKUP_DIR": str(data_dir / "backups"),
        "PG_DUMP_PATH": str(app_dir / "pgsql" / "bin" / "pg_dump.exe"),
        "PG_RESTORE_PATH": str(app_dir / "pgsql" / "bin" / "pg_restore.exe"),
        "TIMEZONE": env.get("TIMEZONE", "America/Sao_Paulo"),
        "BACKUP_RETENTION_DAYS": env.get("BACKUP_RETENTION_DAYS", "30"),
        "BACKUP_DAILY_HOUR": env.get("BACKUP_DAILY_HOUR", "12"),
        "API_WORKERS": "1",
    })
    mirror = params.get("mirror_dir", "").strip()
    if mirror:
        try:
            Path(mirror).mkdir(parents=True, exist_ok=True)
            env["BACKUP_MIRROR_DIR"] = mirror
        except OSError as exc:  # não impede a instalação: o aviso aparece em Configurações › Backups
            log(f"AVISO: pasta de cópia dos backups indisponível ({mirror}): {exc}")
    elif "mirror_dir" in params:  # campo esvaziado no instalador: deixa de copiar
        env.pop("BACKUP_MIRROR_DIR", None)
    admin_email = params.get("admin_email", "").strip().lower()
    if admin_email:  # usado somente se ainda não existir nenhum usuário (ensure_initial_admin)
        env["INITIAL_ADMIN_NAME"] = params.get("admin_name") or "Administrador"
        env["INITIAL_ADMIN_EMAIL"] = admin_email
        env["INITIAL_ADMIN_PASSWORD"] = params.get("admin_password", "")
    write_env(env_file, env)
    log(f"Configuração gravada em {env_file} (porta {port}).")

    if service_exists(SERVICE_APP):
        winsw(app_dir, "stopwait", check=False)
        wait_service_stopped(SERVICE_APP)
    setup_postgres(app_dir, data_dir, env)

    child_env = dict(os.environ, CORPOSANO_ENV_FILE=str(env_file), PYTHONUTF8="1")
    log("Aplicando migrations e dados de referência...")
    try:
        run([str(app_dir / "python" / "python.exe"), "-m", "app.local_server", "--setup"], env=child_env,
            cwd=str(app_dir / "app"))
    finally:  # a senha provisória nunca permanece gravada no arquivo de configuração
        if any(k in env for k in ("INITIAL_ADMIN_PASSWORD", "INITIAL_ADMIN_EMAIL", "INITIAL_ADMIN_NAME")):
            for k in ("INITIAL_ADMIN_PASSWORD", "INITIAL_ADMIN_EMAIL", "INITIAL_ADMIN_NAME"):
                env.pop(k, None)
            write_env(env_file, env)

    import psycopg

    with psycopg.connect(host="localhost", port=int(env["PG_PORT"]), user="corposano", password=env["DB_PASSWORD"],
                         dbname="corposano") as conn:
        has_users = conn.execute("SELECT EXISTS (SELECT 1 FROM users)").fetchone()[0]
    if not has_users:
        raise RuntimeError("Nenhum administrador foi criado. Execute o instalador novamente e informe nome, "
                           "e-mail e senha provisória do administrador.")
    # marca a instalação concluída: nas próximas execuções do instalador o administrador não é pedido de novo
    (data_dir / "instalacao.ok").write_text(time.strftime("%Y-%m-%d %H:%M:%S") + "\n", encoding="utf-8")

    write_service_xml(app_dir, data_dir, env_file)
    if service_exists(SERVICE_APP):  # recria o serviço com a configuração atual
        winsw(app_dir, "uninstall", check=False)
        wait_service_deleted(SERVICE_APP)
    winsw(app_dir, "install")
    run(["sc.exe", "failure", SERVICE_APP, "reset=", "3600", "actions=", "restart/10000/restart/30000/restart/60000"],
        check=False, quiet=True)
    winsw(app_dir, "start")

    run(["netsh", "advfirewall", "firewall", "delete", "rule", "name=Corpo Sano"], check=False, quiet=True)
    if params.get("firewall") == "1":
        log("Liberando a porta no Firewall do Windows (redes privadas/domínio)...")
        run(["netsh", "advfirewall", "firewall", "add", "rule", "name=Corpo Sano", "dir=in", "action=allow",
             "protocol=TCP", f"localport={port}", "profile=private,domain"])

    wait_http(port)
    log(f"Instalação concluída. Acesse http://localhost:{port}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log(f"ERRO: {exc}")
        sys.exit(1)
