"""Armazenamento de arquivos criptografados em disco (volume dedicado)."""
from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_bytes, encrypt_bytes, sha256_hex
from app.core.errors import AppError
from app.models.system import StoredFile

ALLOWED_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "application/xml",
    "text/xml",
    "text/csv",
    "text/plain",
    "application/zip",
    "application/x-zip-compressed",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
}

# assinaturas mínimas para conferir o conteúdo declarado
MAGIC = {
    "application/pdf": [b"%PDF"],
    "image/png": [b"\x89PNG"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "application/zip": [b"PK"],
}


def _root() -> Path:
    root = Path(get_settings().storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_name(name: str) -> str:
    name = Path(name or "arquivo").name
    return re.sub(r"[^\w.\- ]", "_", name)[:200] or "arquivo"


def save_file(
    db: Session,
    data: bytes,
    *,
    filename: str,
    content_type: str | None,
    category: str,
    user_id: uuid.UUID | None = None,
    sensitive: bool = False,
    description: str | None = None,
    internal: bool = False,
    **links: uuid.UUID | None,
) -> StoredFile:
    """``internal=True`` para arquivos gerados pelo sistema (exportações), sem o limite de upload."""
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if not internal and len(data) > max_bytes:
        raise AppError(f"Arquivo excede o limite de {get_settings().max_upload_mb} MB.")
    if not data:
        raise AppError("Arquivo vazio.")
    ctype = (content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream").split(";")[0]
    if ctype not in ALLOWED_TYPES:
        raise AppError("Tipo de arquivo não permitido.")
    for expected, sigs in MAGIC.items():
        if ctype == expected and not any(data.startswith(s) for s in sigs):
            raise AppError("O conteúdo do arquivo não corresponde ao tipo informado.")
    file_id = uuid.uuid4()
    key = f"{category}/{file_id.hex[:2]}/{file_id.hex}.bin"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encrypt_bytes(data))
    record = StoredFile(
        id=file_id,
        category=category,
        original_name=safe_name(filename),
        content_type=ctype,
        size_bytes=len(data),
        sha256=sha256_hex(data),
        storage_key=key,
        sensitive=sensitive,
        description=description,
        uploaded_by=user_id,
        **links,
    )
    db.add(record)
    db.flush()
    return record


def read_file(record: StoredFile) -> bytes:
    path = _root() / record.storage_key
    if not path.exists():
        raise AppError("Arquivo não encontrado no armazenamento.", status_code=404)
    data = decrypt_bytes(path.read_bytes())
    if sha256_hex(data) != record.sha256:
        raise AppError("Falha de integridade do arquivo.", status_code=500)
    return data


def delete_file(db: Session, record: StoredFile) -> None:
    path = _root() / record.storage_key
    if path.exists():
        path.unlink()
    db.delete(record)
