"""Backups do PostgreSQL: pg_dump (formato custom) → AES-256-GCM → disco local + cópia externa (S3 compatível).

Restauração é feita pela linha de comando (scripts/restore.sh / `python -m app.cli backup-restore`),
nunca pela interface web, para evitar sobrescrita acidental do banco de produção.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import CryptoError, decrypt_stream, encrypt_stream
from app.core.errors import AppError
from app.core.settings_store import get_setting
from app.core.utils import local_now, utcnow
from app.models.system import BackupHistory

log = logging.getLogger("corposano.backup")


def _pg_env() -> tuple[list[str], dict]:
    url = urlparse(get_settings().sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://"))
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    args = ["-h", url.hostname or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres"]
    return args + ["-d", url.path.lstrip("/")], env


def backup_dir() -> Path:
    p = Path(get_settings().backup_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _s3_client():
    s = get_settings()
    if not s.backup_s3_bucket:
        return None
    import boto3
    from botocore.config import Config

    config = None
    if s.backup_s3_endpoint:
        # provedores compatíveis com S3 (Oracle Object Storage, MinIO, Wasabi...): endereçamento por caminho
        # e somas de verificação só quando exigidas (as automáticas do boto3 >= 1.36 não são aceitas por todos)
        config = Config(s3={"addressing_style": "path"}, signature_version="s3v4",
                        request_checksum_calculation="when_required",
                        response_checksum_validation="when_required")
    return boto3.client("s3", endpoint_url=s.backup_s3_endpoint or None, region_name=s.backup_s3_region or None,
                        aws_access_key_id=s.backup_s3_access_key or None, aws_secret_access_key=s.backup_s3_secret_key or None,
                        config=config)


def run_backup(db: Session, kind: str = "automatico", user_id: uuid.UUID | None = None) -> BackupHistory:
    s = get_settings()
    rec = BackupHistory(kind=kind, status="executando", created_by=user_id)
    db.add(rec)
    db.commit()
    name = f"corposano_{s.environment}_{local_now():%Y%m%d_%H%M%S}.dump.enc"
    target = backup_dir() / name
    tmp = tempfile.NamedTemporaryFile(prefix="cs-dump-", suffix=".dump", delete=False)
    tmp.close()
    try:
        args, env = _pg_env()
        proc = subprocess.run([s.pg_dump_path, "-Fc", "--no-owner", "--no-privileges", "-f", tmp.name, *args],
                              env=env, capture_output=True, text=True, timeout=3600)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump falhou: {proc.stderr.strip()[:500]}")
        with open(tmp.name, "rb") as src, open(target, "wb") as dst:
            digest = encrypt_stream(src, dst)
        rec.file_name, rec.size_bytes, rec.sha256 = name, target.stat().st_size, digest
        verify_backup(rec)
        client = _s3_client()
        if client:
            key = s.backup_s3_prefix + name
            try:
                client.upload_file(str(target), s.backup_s3_bucket, key)
                rec.offsite_status, rec.offsite_key = "enviado", key
            except Exception as exc:  # noqa: BLE001
                rec.offsite_status = "falha"
                rec.error = f"Cópia externa falhou: {type(exc).__name__}"
                log.error("Falha no envio do backup para armazenamento externo: %s", exc)
        else:
            rec.offsite_status = "nao_configurado"
        if s.backup_mirror_dir and rec.verify_status == "ok":
            # cópia adicional (HD externo, pasta sincronizada com a nuvem) — essencial na instalação local
            try:
                mirror = Path(s.backup_mirror_dir)
                mirror.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, mirror / name)
                if rec.offsite_status == "nao_configurado":
                    rec.offsite_status, rec.offsite_key = "pasta", str(mirror / name)
            except OSError as exc:
                rec.error = f"Cópia para {s.backup_mirror_dir} falhou: {exc}"[:2000]
                log.error("Falha na cópia do backup para %s: %s", s.backup_mirror_dir, exc)
        rec.status = "sucesso" if rec.verify_status == "ok" else "falha"
    except Exception as exc:  # noqa: BLE001
        rec.status, rec.error = "falha", str(exc)[:2000]
        log.error("Backup falhou: %s", exc)
        if target.exists():
            target.unlink()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        rec.finished_at = utcnow()
        db.commit()
    apply_retention(db)
    return rec


def verify_backup(rec: BackupHistory) -> bool:
    """Confere o hash, descriptografa (autenticação GCM por bloco) e valida o arquivo com pg_restore --list."""
    path = backup_dir() / (rec.file_name or "")
    try:
        if not path.exists():
            raise CryptoError("Arquivo não encontrado.")
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        if rec.sha256 and h.hexdigest() != rec.sha256:
            raise CryptoError("Hash SHA-256 divergente.")
        with tempfile.NamedTemporaryFile(prefix="cs-verify-", suffix=".dump", delete=False) as out:
            out_name = out.name
            with open(path, "rb") as src:
                decrypt_stream(src, out)
        try:
            proc = subprocess.run([get_settings().pg_restore_path, "--list", out_name], capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                raise CryptoError("pg_restore não reconheceu o arquivo: " + proc.stderr.strip()[:300])
        finally:
            os.unlink(out_name)
        rec.verify_status, rec.verified_at = "ok", utcnow()
        return True
    except (CryptoError, OSError, subprocess.SubprocessError) as exc:
        rec.verify_status, rec.verified_at = "falha", utcnow()
        rec.error = f"Verificação falhou: {exc}"[:2000]
        return False


def apply_retention(db: Session) -> int:
    days = get_setting(db, "backup.retention_days") or get_settings().backup_retention_days
    limit = utcnow() - timedelta(days=int(days))
    n = 0
    for rec in db.scalars(select(BackupHistory).where(BackupHistory.started_at < limit, BackupHistory.deleted_at.is_(None),
                                                      BackupHistory.file_name.is_not(None))).all():
        path = backup_dir() / rec.file_name
        if path.exists():
            path.unlink()
        mirror_dir = get_settings().backup_mirror_dir
        if mirror_dir and (Path(mirror_dir) / rec.file_name).exists():
            (Path(mirror_dir) / rec.file_name).unlink()
        rec.deleted_at = utcnow()
        n += 1
    db.commit()
    return n


def restore_backup(file_path: str, *, confirm: bool) -> None:
    """Restaura um backup criptografado sobre o banco configurado (uso exclusivo via CLI)."""
    if not confirm:
        raise AppError("Restauração exige confirmação explícita (--confirmo).")
    s = get_settings()
    with tempfile.NamedTemporaryFile(prefix="cs-restore-", suffix=".dump", delete=False) as out:
        out_name = out.name
        with open(file_path, "rb") as src:
            decrypt_stream(src, out)
    try:
        args, env = _pg_env()
        proc = subprocess.run([s.pg_restore_path, "--clean", "--if-exists", "--no-owner", "--no-privileges",
                               "--single-transaction", *args, out_name], env=env, capture_output=True, text=True, timeout=7200)
        if proc.returncode != 0:
            raise RuntimeError("pg_restore falhou: " + proc.stderr.strip()[:1000])
    finally:
        os.unlink(out_name)


def due_for_daily(db: Session) -> bool:
    if local_now().hour < get_settings().backup_daily_hour:
        return False
    last = db.scalar(select(BackupHistory).where(BackupHistory.kind == "automatico")
                     .order_by(BackupHistory.started_at.desc()).limit(1))
    if last is None:
        return True
    from app.core.utils import to_local

    return to_local(last.started_at).date() < local_now().date()
