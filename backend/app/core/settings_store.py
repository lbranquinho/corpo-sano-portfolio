"""Configurações editáveis pela interface (sem alteração de código).

Valores secretos (tokens, senhas) são criptografados e nunca retornam ao frontend.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.crypto import decrypt_str, encrypt_str
from app.models.system import SystemSetting

DEFAULTS: dict[str, Any] = {
    # Agenda
    "agenda.buffer_minutes": 10,
    "agenda.slot_minutes": 30,
    "agenda.allow_overbooking_rooms": False,
    # CRM
    "crm.return_alert_days": [30, 60, 90],
    "crm.inactive_after_days": 120,
    "crm.recurring_min_visits": 2,
    # Pacotes
    "packages.low_balance_threshold": 1,
    "packages.expiry_alert_days": 15,
    # Financeiro
    "finance.default_account_id": None,
    "finance.default_receivable_due_days": 0,
    # Segurança / LGPD
    "security.session_idle_minutes": 30,
    "lgpd.retention_years_inactive": 5,
    "lgpd.consent_text": (
        "Autorizo o tratamento dos meus dados pessoais e das informações de saúde por mim relatadas "
        "exclusivamente para a prestação dos serviços de massoterapia, conforme a LGPD (Lei 13.709/2018). "
        "Declaro que as informações prestadas são verdadeiras e que fui informado(a) de que a massoterapia "
        "não substitui avaliação ou tratamento médico."
    ),
    # WhatsApp
    "whatsapp.enabled": False,
    "whatsapp.api_version": "v24.0",
    "whatsapp.business_id": "",
    "whatsapp.waba_id": "",
    "whatsapp.phone_number_id": "",
    "whatsapp.reminder_hours_before": 24,
    "whatsapp.auto_confirmation": True,
    "whatsapp.auto_reminder": True,
    "whatsapp.auto_reschedule": True,
    "whatsapp.auto_cancellation": True,
    "whatsapp.auto_thanks": False,
    "whatsapp.auto_birthday": False,
    "whatsapp.birthday_hour": 9,
    "whatsapp.optout_keywords": ["SAIR", "PARAR", "CANCELAR MENSAGENS", "STOP"],
    # NFS-e (URLs oficiais — conferir com a documentação vigente em gov.br/nfse)
    "nfse.sefin_url_homologacao": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
    "nfse.sefin_url_producao": "https://sefin.nfse.gov.br/SefinNacional",
    "nfse.adn_url_homologacao": "https://adn.producaorestrita.nfse.gov.br",
    "nfse.adn_url_producao": "https://adn.nfse.gov.br",
    "nfse.timeout_seconds": 60,
    "nfse.signature_algorithm": "rsa-sha256",
    "nfse.danfse_path": "/danfse/{chave}",
    "nfse.public_query_url": "https://www.nfse.gov.br/consultapublica",
    # Backups
    "backup.retention_days": None,  # None = usa BACKUP_RETENTION_DAYS do ambiente
}

SECRET_KEYS = {"whatsapp.access_token", "whatsapp.app_secret", "whatsapp.verify_token"}


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(SystemSetting, key)
    if row is None:
        return DEFAULTS.get(key, default)
    if row.is_secret:
        return decrypt_str(row.value_enc) if row.value_enc else None
    return row.value


def set_setting(db: Session, key: str, value: Any, user_id: uuid.UUID | None = None) -> None:
    row = db.get(SystemSetting, key)
    secret = key in SECRET_KEYS
    if row is None:
        row = SystemSetting(key=key, is_secret=secret)
        db.add(row)
    row.is_secret = secret
    row.updated_by = user_id
    if secret:
        row.value = None
        row.value_enc = encrypt_str(value) if value else None
    else:
        row.value = value


def has_secret(db: Session, key: str) -> bool:
    row = db.get(SystemSetting, key)
    return bool(row and row.value_enc)


def get_group(db: Session, prefix: str) -> dict[str, Any]:
    """Configurações não secretas de um grupo, com padrões preenchidos."""
    out = {k: v for k, v in DEFAULTS.items() if k.startswith(prefix)}
    rows = db.query(SystemSetting).filter(SystemSetting.key.like(prefix + "%")).all()
    for row in rows:
        if not row.is_secret:
            out[row.key] = row.value
    return out
