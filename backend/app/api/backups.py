from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require
from app.core.errors import AppError, NotFound
from app.core.settings_store import get_setting
from app.models.auth import User
from app.models.system import BackupHistory
from app.services import backup as svc

router = APIRouter(prefix="/backups", tags=["Backups"])
ADMIN = require("backups.manage")


def _out(b: BackupHistory) -> dict:
    return {"id": str(b.id), "kind": b.kind, "status": b.status, "started_at": b.started_at, "finished_at": b.finished_at,
            "file_name": b.file_name, "size_bytes": b.size_bytes, "sha256": b.sha256, "offsite_status": b.offsite_status,
            "verified_at": b.verified_at, "verify_status": b.verify_status, "error": b.error, "deleted_at": b.deleted_at}


@router.get("")
def list_backups(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    s = get_settings()
    rows = db.scalars(select(BackupHistory).order_by(BackupHistory.started_at.desc()).limit(200)).all()
    return {
        "items": [_out(b) for b in rows],
        "config": {
            "retention_days": get_setting(db, "backup.retention_days") or s.backup_retention_days,
            "daily_hour": s.backup_daily_hour,
            "offsite_configured": bool(s.backup_s3_bucket or s.backup_mirror_dir),
            "offsite_bucket": s.backup_s3_bucket or s.backup_mirror_dir or None,
            "encryption": "AES-256-GCM",
        },
    }


@router.post("/run")
def run_now(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    running = db.scalar(select(BackupHistory.id).where(BackupHistory.status == "executando").limit(1))
    if running:
        raise AppError("Já existe um backup em execução.")
    rec = svc.run_backup(db, "manual", user.id)
    audit(db, "backup_manual", user=user, entity="backup", entity_id=rec.id, details={"status": rec.status})
    db.commit()
    if rec.status != "sucesso":
        raise AppError(f"Backup falhou: {rec.error}", details=_out(rec))
    return {"message": "Backup concluído, criptografado e verificado.", "backup": _out(rec)}


@router.post("/{backup_id}/verify")
def verify(backup_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    rec = db.get(BackupHistory, backup_id)
    if rec is None or not rec.file_name or rec.deleted_at:
        raise NotFound("Backup")
    ok = svc.verify_backup(rec)
    audit(db, "backup_verificado", user=user, entity="backup", entity_id=rec.id, details={"ok": ok})
    db.commit()
    return {"message": "Integridade confirmada." if ok else f"Falha na verificação: {rec.error}", "backup": _out(rec)}


@router.get("/{backup_id}/download")
def download(backup_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    rec = db.get(BackupHistory, backup_id)
    if rec is None or not rec.file_name or rec.deleted_at:
        raise NotFound("Backup")
    path = svc.backup_dir() / rec.file_name
    if not path.exists():
        raise NotFound("Arquivo de backup")
    audit(db, "backup_baixado", user=user, entity="backup", entity_id=rec.id, sensitive=True)
    db.commit()
    return FileResponse(path, media_type="application/octet-stream", filename=rec.file_name)
