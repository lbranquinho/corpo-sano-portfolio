from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.utils import is_valid_cnpj, is_valid_cpf
from app.models.customer import Customer
from tests.conftest import VALID_CPF, VALID_CPF_2, book, next_weekday_at


def test_cpf_cnpj_validators():
    assert is_valid_cpf(VALID_CPF) and is_valid_cpf("529.982.247-25")
    assert not is_valid_cpf("52998224724") and not is_valid_cpf("11111111111")
    assert is_valid_cnpj("11.222.333/0001-81") and not is_valid_cnpj("11222333000182")


def test_customer_cpf_optional_and_validated(client, admin):
    assert client.post("/api/v1/customers", headers=admin, json={"full_name": "Sem CPF Cliente"}).status_code == 201
    r = client.post("/api/v1/customers", headers=admin, json={"full_name": "CPF Errado", "cpf": "123.456.789-00"})
    assert r.status_code == 422 and "CPF" in r.json()["detail"]


def test_duplicate_cpf_conflict(client, admin):
    assert client.post("/api/v1/customers", headers=admin, json={"full_name": "Primeira Pessoa", "cpf": VALID_CPF}).status_code == 201
    r = client.post("/api/v1/customers", headers=admin, json={"full_name": "Segunda Pessoa", "cpf": VALID_CPF})
    assert r.status_code == 409


def test_search_by_name_phone_cpf(client, admin):
    client.post("/api/v1/customers", headers=admin, json={"full_name": "João Conceição", "cpf": VALID_CPF_2,
                                                           "phone": "(21) 99876-5432"})
    for q in ("joao", "conceição", "998765", VALID_CPF_2[:6]):
        items = client.get(f"/api/v1/customers?q={q}", headers=admin).json()["items"]
        assert [c["full_name"] for c in items] == ["João Conceição"], q


def test_customer_creates_crm_lead(client, setup_basics):
    leads = client.get("/api/v1/crm/leads", headers=setup_basics["h"]).json()
    assert leads[0]["customer_id"] == setup_basics["customer"]["id"]
    assert leads[0]["stage"] == "novo_contato"


def test_schedule_and_conflict_same_professional(client, setup_basics):
    b = setup_basics
    start = next_weekday_at(10)
    r = book(client, b, start)
    assert r.status_code == 201, r.text
    # mesmo profissional, horário sobreposto, outra sala
    other_room = client.post("/api/v1/settings/rooms", headers=b["h"], json={"name": "Sala 2"}).json()
    r2 = book(client, b, start + timedelta(minutes=30), room_id=other_room["id"])
    assert r2.status_code == 409
    assert r2.json()["details"][0]["type"] == "profissional"


def test_conflict_same_room(client, setup_basics):
    b = setup_basics
    start = next_weekday_at(10)
    assert book(client, b, start).status_code == 201
    r = book(client, b, start + timedelta(minutes=15), professional_id=b["prof2"]["id"])
    assert r.status_code == 409
    assert r.json()["details"][0]["type"] == "sala"


def test_buffer_between_sessions(client, setup_basics):
    b = setup_basics
    client.put("/api/v1/settings/params/agenda", headers=b["h"], json={"agenda.buffer_minutes": 15})
    start = next_weekday_at(10)
    assert book(client, b, start).status_code == 201
    assert book(client, b, start + timedelta(minutes=65)).status_code == 409  # dentro do intervalo de 15 min
    assert book(client, b, start + timedelta(minutes=75)).status_code == 201


def test_back_to_back_without_interval(client, setup_basics):
    """Padrão: sem intervalo entre sessões (ex.: 15h e 16h com serviço de 60 min)."""
    b = setup_basics
    assert client.get("/api/v1/settings/params/agenda", headers=b["h"]).json()["agenda.buffer_minutes"] == 0
    assert book(client, b, next_weekday_at(15)).status_code == 201
    r = book(client, b, next_weekday_at(16))
    assert r.status_code == 201, r.text


def test_custom_duration_moves_next_start(client, setup_basics):
    """Duração alterada no agendamento (60 → 50 min) define o término e libera o próximo início às 15h50."""
    b = setup_basics
    start = next_weekday_at(15)
    r = book(client, b, start, duration_minutes=50)
    assert r.status_code == 201, r.text
    day = start.date().isoformat()
    slots = client.get(f"/api/v1/agenda/availability?day={day}&service_id={b['service']['id']}"
                       f"&professional_id={b['prof']['id']}&room_id={b['room']['id']}&duration_minutes=30", headers=b["h"]).json()["slots"]
    hhmm = [s[11:16] for s in slots]
    assert "15:50" in hhmm and "15:30" not in hhmm and "14:30" in hhmm  # 14h30 + 30 min termina às 15h
    assert book(client, b, start + timedelta(minutes=45)).status_code == 409
    assert book(client, b, start + timedelta(minutes=50)).status_code == 201
    # para mais: 90 min a partir das 17h ocupa até 18h30
    assert book(client, b, next_weekday_at(17), duration_minutes=90).status_code == 201
    assert book(client, b, next_weekday_at(18)).status_code == 409


def test_default_hours_6_to_22_every_day(client, setup_basics):
    b = setup_basics
    hours = client.get("/api/v1/settings/business-hours", headers=b["h"]).json()
    assert [(h["is_open"], h["open_time"], h["close_time"]) for h in hours] == [(True, "06:00:00", "22:00:00")] * 7
    assert book(client, b, next_weekday_at(6)).status_code == 201
    assert book(client, b, next_weekday_at(21)).status_code == 201  # termina às 22h
    assert book(client, b, next_weekday_at(10, weekday=6)).status_code == 201  # domingo aberto


def test_outside_hours_and_holiday_rejected(client, setup_basics):
    b = setup_basics
    r = book(client, b, next_weekday_at(22))
    assert r.status_code == 400 and "horário de funcionamento" in r.json()["detail"]
    hours = client.get("/api/v1/settings/business-hours", headers=b["h"]).json()
    hours[6] = {"weekday": 6, "is_open": False}
    assert client.put("/api/v1/settings/business-hours", headers=b["h"], json=hours).status_code == 200
    r = book(client, b, next_weekday_at(10, weekday=6))  # domingo fechado
    assert r.status_code == 400
    holiday = next_weekday_at(10, weekday=2)
    client.post("/api/v1/settings/holidays", headers=b["h"], json={"date": holiday.date().isoformat(), "name": "Feriado municipal"})
    r = book(client, b, holiday)
    assert r.status_code == 400 and "feriado" in r.json()["detail"]
    # administrador pode sobrepor horário de funcionamento explicitamente
    assert book(client, b, next_weekday_at(22), override_hours=True).status_code == 201


def test_schedule_block(client, setup_basics):
    b = setup_basics
    start = next_weekday_at(14)
    r = client.post("/api/v1/agenda/blocks", headers=b["h"], json={
        "professional_id": b["prof"]["id"], "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=2)).isoformat(), "reason": "Curso"})
    assert r.status_code == 201
    r = book(client, b, start + timedelta(minutes=30))
    assert r.status_code == 409 and r.json()["details"][0]["type"] == "bloqueio"


def test_cancel_frees_slot_and_reschedule(client, setup_basics):
    b = setup_basics
    start = next_weekday_at(10)
    a = book(client, b, start).json()["created"][0]
    r = client.post(f"/api/v1/agenda/appointments/{a['id']}/status", headers=b["h"], json={"action": "cancelar"})
    assert r.status_code == 400  # motivo obrigatório
    r = client.post(f"/api/v1/agenda/appointments/{a['id']}/status", headers=b["h"],
                    json={"action": "cancelar", "reason": "Cliente pediu"})
    assert r.status_code == 200 and r.json()["status"] == "cancelado"
    b2 = book(client, b, start).json()["created"][0]
    new_start = start + timedelta(hours=2)
    r = client.put(f"/api/v1/agenda/appointments/{b2['id']}", headers=b["h"], json={
        "start_at": new_start.isoformat(), "professional_id": b["prof"]["id"], "room_id": b["room"]["id"],
        "duration_minutes": 60, "price": "150.00", "discount": "0", "reason": "Remarcação"})
    assert r.status_code == 200
    detail = client.get(f"/api/v1/agenda/appointments/{b2['id']}", headers=b["h"]).json()
    assert [h["action"] for h in detail["history"]] == ["criado", "remarcado"]


def test_recurrence_skip_conflicts(client, setup_basics):
    b = setup_basics
    start = next_weekday_at(10)
    assert book(client, b, start + timedelta(weeks=1)).status_code == 201  # ocupa a 2ª ocorrência
    r = book(client, b, start, recurrence="semanal", occurrences=4)
    assert r.status_code == 409
    r = book(client, b, start, recurrence="semanal", occurrences=4, skip_conflicts=True)
    assert r.status_code == 201
    assert len(r.json()["created"]) == 3 and len(r.json()["skipped"]) == 1


def test_database_exclusion_constraint(db, setup_basics):
    """Mesmo sem passar pela API, o banco impede sobreposição do mesmo profissional."""
    b = setup_basics
    start = next_weekday_at(10)
    params = {"c": b["customer"]["id"], "s": b["service"]["id"], "p": b["prof"]["id"], "st": start,
              "en": start + timedelta(hours=1)}
    sql = text("INSERT INTO appointments (id, customer_id, service_id, professional_id, start_at, end_at, duration_minutes,"
               " price, discount, status, is_evaluation, created_at, updated_at) VALUES (gen_random_uuid(), :c, :s, :p, :st,"
               " :en, 60, 100, 0, 'agendado', false, now(), now())")
    db.execute(sql, params)
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(sql, {**params, "st": start + timedelta(minutes=30), "en": start + timedelta(minutes=90)})
        db.commit()
    db.rollback()


def test_availability_slots(client, setup_basics):
    b = setup_basics
    day = next_weekday_at(10).date()
    book(client, b, next_weekday_at(10))
    r = client.get(f"/api/v1/agenda/availability?day={day}&service_id={b['service']['id']}&professional_id={b['prof']['id']}",
                   headers=b["h"])
    slots = r.json()["slots"]
    assert slots and not any("T10:00" in s or "T10:30" in s for s in slots)


def test_anonymize_keeps_fiscal_records(client, setup_basics, db):
    b = setup_basics
    cid = b["customer"]["id"]
    r = client.post(f"/api/v1/customers/{cid}/anonymize", headers=b["h"], json={"confirmation": "ANONIMIZAR", "reason": "Pedido do titular"})
    assert r.status_code == 200
    c = db.get(Customer, __import__("uuid").UUID(cid))
    assert c.cpf is None and c.status == "anonimizado" and "anonimizado" in c.full_name.lower()
