"""Certificado digital ICP-Brasil (A1 / PKCS#12): leitura, metadados e material para mTLS/assinatura."""
from __future__ import annotations

import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12

# OIDs ICP-Brasil (DOC-ICP-04): CNPJ da pessoa jurídica e dados do responsável
OID_CNPJ = "2.16.76.1.3.3"
OID_PF_DATA = "2.16.76.1.3.1"


class CertificateError(Exception):
    pass


@dataclass
class CertificateInfo:
    subject: str
    issuer: str
    serial_number: str
    valid_from: datetime
    valid_to: datetime
    document: str | None
    thumbprint_sha256: str


@dataclass
class LoadedCertificate:
    key_pem: bytes
    cert_pem: bytes
    chain_pem: bytes
    certificate: x509.Certificate
    private_key: object


def _extract_document(cert: x509.Certificate) -> str | None:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        for name in san:
            if isinstance(name, x509.OtherName) and name.type_id.dotted_string == OID_CNPJ:
                digits = re.sub(r"\D", "", name.value.decode("latin-1", "ignore"))
                if len(digits) >= 14:
                    return digits[-14:]
            if isinstance(name, x509.OtherName) and name.type_id.dotted_string == OID_PF_DATA:
                digits = re.sub(r"\D", "", name.value.decode("latin-1", "ignore"))
                if len(digits) >= 19:
                    return digits[8:19]  # data de nascimento (8) + CPF (11)
    except x509.ExtensionNotFound:
        pass
    cn = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    if cn:
        m = re.search(r":(\d{14}|\d{11})\b", cn[0].value)
        if m:
            return m.group(1)
    return None


def load_pfx(data: bytes, password: str) -> LoadedCertificate:
    try:
        key, cert, extra = pkcs12.load_key_and_certificates(data, password.encode() if password else None)
    except ValueError as exc:
        raise CertificateError("Não foi possível abrir o certificado: senha incorreta ou arquivo inválido.") from exc
    if key is None or cert is None:
        raise CertificateError("O arquivo não contém chave privada e certificado.")
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    chain = b"".join(c.public_bytes(serialization.Encoding.PEM) for c in (extra or []))
    return LoadedCertificate(key_pem=key_pem, cert_pem=cert_pem, chain_pem=chain, certificate=cert, private_key=key)


def inspect_pfx(data: bytes, password: str) -> CertificateInfo:
    loaded = load_pfx(data, password)
    cert = loaded.certificate
    return CertificateInfo(
        subject=cert.subject.rfc4514_string()[:500],
        issuer=cert.issuer.rfc4514_string()[:500],
        serial_number=format(cert.serial_number, "X"),
        valid_from=cert.not_valid_before_utc,
        valid_to=cert.not_valid_after_utc,
        document=_extract_document(cert),
        thumbprint_sha256=cert.fingerprint(hashes.SHA256()).hex(),
    )


def is_valid_now(info_valid_from: datetime, info_valid_to: datetime) -> bool:
    now = datetime.now(timezone.utc)
    return info_valid_from <= now <= info_valid_to


@contextmanager
def mtls_files(loaded: LoadedCertificate) -> Iterator[tuple[str, str]]:
    """Grava chave/certificado em arquivos temporários privados apenas durante a conexão."""
    tmpdir = tempfile.mkdtemp(prefix="cs-mtls-")
    cert_path = os.path.join(tmpdir, "cert.pem")
    key_path = os.path.join(tmpdir, "key.pem")
    try:
        fd = os.open(cert_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(loaded.cert_pem + loaded.chain_pem)
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(loaded.key_pem)
        yield cert_path, key_path
    finally:
        for p in (cert_path, key_path):
            try:
                if os.path.exists(p):
                    with open(p, "r+b") as f:
                        f.write(b"\0" * os.path.getsize(p))
                    os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
