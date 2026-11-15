"""Criptografia de credenciais, arquivos e dados de saúde.

- Fernet (AES-128-CBC + HMAC-SHA256) com MultiFernet para rotação de chaves.
- Dados de saúde usam um conjunto de chaves separado (HEALTH_ENCRYPTION_KEYS).
- Backups usam AES-256-GCM em blocos (streaming), ver ``encrypt_stream``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from typing import Any, BinaryIO

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


class CryptoError(Exception):
    pass


def _multi(keys: str) -> MultiFernet:
    parts = [k.strip() for k in keys.split(",") if k.strip()]
    if not parts:
        raise CryptoError("Nenhuma chave de criptografia configurada.")
    try:
        return MultiFernet([Fernet(k.encode()) for k in parts])
    except Exception as exc:  # chave mal formatada
        raise CryptoError("Chave de criptografia inválida (use Fernet.generate_key()).") from exc


_general: MultiFernet | None = None
_health: MultiFernet | None = None


def general_cipher() -> MultiFernet:
    global _general
    if _general is None:
        _general = _multi(get_settings().encryption_keys)
    return _general


def health_cipher() -> MultiFernet:
    global _health
    if _health is None:
        _health = _multi(get_settings().health_encryption_keys)
    return _health


def encrypt_str(value: str | None) -> str | None:
    if value is None:
        return None
    return general_cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_str(token: str | None) -> str | None:
    if token is None:
        return None
    try:
        return general_cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CryptoError("Não foi possível descriptografar a credencial.") from exc


def encrypt_bytes(data: bytes) -> bytes:
    return general_cipher().encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    try:
        return general_cipher().decrypt(data)
    except InvalidToken as exc:
        raise CryptoError("Arquivo corrompido ou chave incorreta.") from exc


def encrypt_health(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    return health_cipher().encrypt(raw).decode("ascii")


def decrypt_health(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    try:
        return json.loads(health_cipher().decrypt(token.encode("ascii")).decode("utf-8"))
    except InvalidToken as exc:
        raise CryptoError("Não foi possível descriptografar o registro clínico.") from exc


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Backups: AES-256-GCM em blocos de 1 MiB
# Formato: b"CSBK1" + [nonce(12) | tamanho(4, big-endian) | ciphertext+tag] ...
# ---------------------------------------------------------------------------
BACKUP_MAGIC = b"CSBK1"
CHUNK = 1024 * 1024


def _backup_key() -> bytes:
    try:
        key = base64.b64decode(get_settings().backup_encryption_key)
    except Exception as exc:
        raise CryptoError("BACKUP_ENCRYPTION_KEY inválida (base64).") from exc
    if len(key) != 32:
        raise CryptoError("BACKUP_ENCRYPTION_KEY deve ter 32 bytes (base64).")
    return key


def encrypt_stream(src: BinaryIO, dst: BinaryIO) -> str:
    """Criptografa ``src`` em ``dst``; retorna o SHA-256 do arquivo cifrado."""
    aes = AESGCM(_backup_key())
    digest = hashlib.sha256()
    dst.write(BACKUP_MAGIC)
    digest.update(BACKUP_MAGIC)
    index = 0
    while True:
        block = src.read(CHUNK)
        if not block:
            break
        nonce = os.urandom(12)
        # o índice do bloco entra como dado associado: impede reordenação de blocos
        ct = aes.encrypt(nonce, block, struct.pack(">Q", index))
        frame = nonce + struct.pack(">I", len(ct)) + ct
        dst.write(frame)
        digest.update(frame)
        index += 1
    return digest.hexdigest()


def decrypt_stream(src: BinaryIO, dst: BinaryIO | None) -> int:
    """Descriptografa e valida a integridade; ``dst=None`` apenas verifica."""
    aes = AESGCM(_backup_key())
    if src.read(len(BACKUP_MAGIC)) != BACKUP_MAGIC:
        raise CryptoError("Arquivo não é um backup do Corpo Sano.")
    total = 0
    index = 0
    while True:
        head = src.read(16)
        if not head:
            break
        if len(head) != 16:
            raise CryptoError("Backup truncado.")
        nonce, size = head[:12], struct.unpack(">I", head[12:])[0]
        ct = src.read(size)
        if len(ct) != size:
            raise CryptoError("Backup truncado.")
        try:
            block = aes.decrypt(nonce, ct, struct.pack(">Q", index))
        except Exception as exc:
            raise CryptoError("Falha de integridade no backup (chave incorreta ou arquivo alterado).") from exc
        if dst is not None:
            dst.write(block)
        total += len(block)
        index += 1
    return total
