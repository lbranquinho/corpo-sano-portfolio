"""Comandos administrativos.

  python -m app.cli seed                          # dados de referência (idempotente)
  python -m app.cli create-admin --email X --name Y   # senha lida de forma interativa ou de ADMIN_PASSWORD
  python -m app.cli backup                        # backup imediato
  python -m app.cli backup-restore ARQUIVO --confirmo
  python -m app.cli generate-keys                 # gera chaves para o .env
"""
from __future__ import annotations

import argparse
import base64
import getpass
import os
import secrets
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="corposano")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    ca = sub.add_parser("create-admin")
    ca.add_argument("--email", required=True)
    ca.add_argument("--name", required=True)
    sub.add_parser("backup")
    rs = sub.add_parser("backup-restore")
    rs.add_argument("file")
    rs.add_argument("--confirmo", action="store_true")
    sub.add_parser("generate-keys")
    args = p.parse_args(argv)

    if args.cmd == "generate-keys":
        from cryptography.fernet import Fernet

        print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
        print(f"ENCRYPTION_KEYS={Fernet.generate_key().decode()}")
        print(f"HEALTH_ENCRYPTION_KEYS={Fernet.generate_key().decode()}")
        print(f"BACKUP_ENCRYPTION_KEY={base64.b64encode(os.urandom(32)).decode()}")
        print("# Guarde BACKUP_ENCRYPTION_KEY fora do servidor: sem ela os backups não podem ser restaurados.")
        return 0

    from sqlalchemy import select

    from app.core.database import SessionLocal

    if args.cmd == "seed":
        from app.services.bootstrap import seed_reference_data

        with SessionLocal() as db:
            seed_reference_data(db)
            db.commit()
        print("Dados de referência aplicados.")
        return 0

    if args.cmd == "create-admin":
        from app.core.security import hash_password, validate_password_strength
        from app.models.auth import Role, User
        from app.services.bootstrap import seed_reference_data

        password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Senha provisória: ")
        validate_password_strength(password)
        with SessionLocal() as db:
            seed_reference_data(db)
            if db.scalar(select(User).where(User.email == args.email.lower())):
                print("Já existe usuário com este e-mail.", file=sys.stderr)
                return 1
            role = db.scalar(select(Role).where(Role.code == "admin"))
            db.add(User(name=args.name, email=args.email.lower(), password_hash=hash_password(password),
                        role_id=role.id, must_change_password=True))
            db.commit()
        print("Administrador criado. A troca de senha será exigida no primeiro acesso.")
        return 0

    if args.cmd == "backup":
        from app.services.backup import run_backup

        with SessionLocal() as db:
            rec = run_backup(db, "manual")
            print(f"Backup {rec.status}: {rec.file_name or ''} {rec.error or ''}")
            return 0 if rec.status == "sucesso" else 1

    if args.cmd == "backup-restore":
        from app.services.backup import restore_backup

        if not args.confirmo:
            print("ATENÇÃO: a restauração substitui TODO o banco configurado em DATABASE_URL. "
                  "Repita o comando com --confirmo para prosseguir.", file=sys.stderr)
            return 2
        restore_backup(args.file, confirm=True)
        print("Restauração concluída. Reinicie a API e o worker.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
