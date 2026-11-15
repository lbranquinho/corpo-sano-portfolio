import hashlib
import hmac
import io
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.crypto import CryptoError, decrypt_stream, encrypt_stream
from app.core.settings_store import set_setting
from app.integrations.whatsapp.client import WhatsAppClient
from app.models.clinical import CustomerHealthRecord
from app.models.whatsapp import WhatsappMessage, WhatsappTemplate
from app.services import whatsapp as wa
from tests.conftest import book, next_weekday_at

APP_SECRET = "segredo-do-app-teste"


def _enable_whatsapp(db):
    for k, v in {"whatsapp.enabled": True, "whatsapp.phone_number_id": "123456", "whatsapp.waba_id": "999",
                 "whatsapp.access_token": "token-teste", "whatsapp.app_secret": APP_SECRET,
                 "whatsapp.verify_token": "verifica-123"}.items():
        set_setting(db, k, v)
    db.add(WhatsappTemplate(name="confirmacao_agendamento", language="pt_BR", category="UTILITY", purpose="confirmacao",
                            body_text="Olá {{1}}, seu horário em {{2}} às {{3}} está confirmado.",
                            parameters=["cliente_nome", "data", "hora"], meta_status="APPROVED", is_active=True))
    db.commit()


def test_confirmation_enqueued_with_consent(client, setup_basics, db):
    _enable_whatsapp(db)
    a = book(client, setup_basics, next_weekday_at(10)).json()["created"][0]
    msg = db.scalar(select(WhatsappMessage).where(WhatsappMessage.appointment_id == uuid.UUID(a["id"])))
    assert msg.status == "pendente" and msg.content.startswith("Olá Maria")
    # nenhuma informação clínica nas variáveis
    assert set(msg.variables["params"]) and all("anamnese" not in p.lower() for p in msg.variables["params"])


def test_no_consent_blocks_message(client, setup_basics, db):
    _enable_whatsapp(db)
    b = setup_basics
    c = client.post("/api/v1/customers", headers=b["h"], json={"full_name": "Sem Consentimento", "phone": "11912345678"}).json()
    r = client.post("/api/v1/agenda/appointments", headers=b["h"], json={
        "customer_id": c["id"], "service_id": b["service"]["id"], "professional_id": b["prof"]["id"],
        "start_at": next_weekday_at(15).isoformat()})
    msg = db.scalar(select(WhatsappMessage).where(WhatsappMessage.appointment_id == uuid.UUID(r.json()["created"][0]["id"])))
    assert msg.status == "bloqueada" and "consentimento" in msg.last_error


def test_disabled_integration_does_not_block_operation(client, setup_basics, db):
    assert book(client, setup_basics, next_weekday_at(10)).status_code == 201
    assert db.scalar(select(WhatsappMessage.id)) is None


def test_queue_send_and_retry(client, setup_basics, db, monkeypatch):
    _enable_whatsapp(db)
    book(client, setup_basics, next_weekday_at(10))
    attempts = {"n": 0}

    def handler(request: httpx.Request):
        attempts["n"] += 1
        assert request.headers["authorization"] == "Bearer token-teste"
        payload = json.loads(request.content)
        assert payload["type"] == "template" and payload["messaging_product"] == "whatsapp"
        if attempts["n"] == 1:
            return httpx.Response(500, json={"error": {"code": 131000, "message": "Erro temporário"}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.TESTE1"}]})

    def factory(db_):
        return WhatsAppClient(access_token="token-teste", phone_number_id="123456", waba_id="999", api_version="v24.0",
                              transport=httpx.MockTransport(handler))

    monkeypatch.setattr(wa, "make_client", factory)
    wa.process_queue(db)
    msg = db.scalar(select(WhatsappMessage))
    assert msg.status == "pendente" and msg.attempts == 1  # erro temporário: nova tentativa agendada
    msg.next_attempt_at = datetime.now().astimezone() - timedelta(seconds=1)
    db.commit()
    wa.process_queue(db)
    db.refresh(msg)
    assert msg.status == "enviada" and msg.wa_message_id == "wamid.TESTE1"


def _signed_post(client, payload: dict, secret: str = APP_SECRET):
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/api/v1/whatsapp/webhook", content=raw, headers={"X-Hub-Signature-256": sig,
                                                                        "Content-Type": "application/json"})


def test_webhook_verification_and_signature(client, db):
    _enable_whatsapp(db)
    ok = client.get("/api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=verifica-123&hub.challenge=777")
    assert ok.status_code == 200 and ok.text == "777"
    assert client.get("/api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=errado&hub.challenge=1").status_code == 403
    assert _signed_post(client, {"entry": []}, secret="outro").status_code == 401


def test_webhook_status_inbound_and_optout(client, setup_basics, db):
    _enable_whatsapp(db)
    book(client, setup_basics, next_weekday_at(10))
    msg = db.scalar(select(WhatsappMessage))
    msg.status, msg.wa_message_id = "enviada", "wamid.ABC"
    db.commit()
    payload = {"entry": [{"changes": [{"value": {
        "statuses": [{"id": "wamid.ABC", "status": "read", "timestamp": "1762950000"}],
        "messages": [{"from": "5511987654321", "id": "wamid.IN1", "timestamp": "1762950100", "type": "text",
                      "text": {"body": "SAIR"}}]}}]}]}
    r = _signed_post(client, payload)
    assert r.status_code == 200 and r.json()["messages"] == 1
    db.expire_all()
    assert db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "wamid.ABC")).status == "lida"
    inbound = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "wamid.IN1"))
    assert str(inbound.customer_id) == setup_basics["customer"]["id"]
    consents = client.get(f"/api/v1/customers/{setup_basics['customer']['id']}/consents", headers=setup_basics["h"]).json()
    assert next(c for c in consents if c["type"] == "whatsapp_marketing")["granted"] is False
    # reentrega do mesmo webhook não duplica
    _signed_post(client, payload)
    assert len(db.scalars(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "wamid.IN1")).all()) == 1


def test_health_data_encrypted_at_rest(client, setup_basics, db):
    b = setup_basics
    r = client.post(f"/api/v1/clinical/customers/{b['customer']['id']}/health-records", headers=b["h"], json={
        "objective": "Relaxamento", "allergies": "Alergia a amendoim", "consent_given": True,
        "consent_name": "Maria José da Silva"})
    assert r.status_code == 201
    raw = db.execute(text("SELECT data_enc FROM customer_health_records")).scalar()
    assert "amendoim" not in raw
    records = client.get(f"/api/v1/clinical/customers/{b['customer']['id']}/health-records", headers=b["h"]).json()
    assert records[0]["allergies"] == "Alergia a amendoim" and len(records[0]["consent_hash"]) == 64
    # recepcionista não acessa dados clínicos
    from tests.conftest import login, make_user

    make_user("recep@clinica.com.br", "recepcionista")
    h = login(client, "recep@clinica.com.br")
    assert client.get(f"/api/v1/clinical/customers/{b['customer']['id']}/health-records", headers=h).status_code == 403


def test_health_record_requires_consent(client, setup_basics):
    b = setup_basics
    r = client.post(f"/api/v1/clinical/customers/{b['customer']['id']}/health-records", headers=b["h"], json={
        "objective": "x", "consent_given": False, "consent_name": "Maria José"})
    assert r.status_code == 400


def test_backup_stream_encryption_detects_tampering():
    data = os.urandom(3 * 1024 * 1024 + 123)
    enc = io.BytesIO()
    encrypt_stream(io.BytesIO(data), enc)
    out = io.BytesIO()
    decrypt_stream(io.BytesIO(enc.getvalue()), out)
    assert out.getvalue() == data
    tampered = bytearray(enc.getvalue())
    tampered[100] ^= 0xFF
    with pytest.raises(CryptoError):
        decrypt_stream(io.BytesIO(bytes(tampered)), None)


@pytest.mark.skipif(not shutil.which(get_settings().pg_dump_path) and not os.path.exists(get_settings().pg_dump_path),
                    reason="pg_dump indisponível")
def test_backup_and_restore_roundtrip(client, setup_basics, db):
    """Backup real (pg_dump) + restauração em um banco separado e conferência dos dados."""
    import tempfile
    from pathlib import Path

    from app.services.backup import backup_dir, restore_backup, run_backup

    mirror = tempfile.mkdtemp(prefix="cs-mirror-")
    get_settings().backup_mirror_dir = mirror
    try:
        rec = run_backup(db, "manual")
    finally:
        get_settings().backup_mirror_dir = ""
    assert rec.status == "sucesso", rec.error
    assert rec.verify_status == "ok"
    assert (Path(mirror) / rec.file_name).stat().st_size == rec.size_bytes  # cópia adicional
    path = backup_dir() / rec.file_name
    s = get_settings()
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    base_url = make_url(s.sqlalchemy_url)
    target_db = "corposano_restore_check"
    admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {target_db}"))
        conn.execute(text(f"CREATE DATABASE {target_db}"))
    admin_engine.dispose()
    target_url = base_url.set(database=target_db)
    os.environ["DATABASE_URL"] = target_url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    try:
        restore_backup(str(path), confirm=True)
        e = create_engine(target_url)
        with e.connect() as conn:
            names = conn.execute(text("SELECT full_name FROM customers")).scalars().all()
        e.dispose()
        assert names == ["Maria José da Silva"]
    finally:
        os.environ["DATABASE_URL"] = base_url.render_as_string(hide_password=False)
        get_settings.cache_clear()
        admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {target_db}"))
        admin_engine.dispose()
