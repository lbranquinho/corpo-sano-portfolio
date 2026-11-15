from datetime import datetime, timedelta

from app.core.utils import clinic_tz, local_today
from tests.conftest import book, next_weekday_at


def _past(hours_ago: int = 3) -> datetime:
    now = datetime.now(clinic_tz()).replace(minute=0, second=0, microsecond=0)
    return now - timedelta(hours=hours_ago)


def _status(client, b, appt_id, action, **extra):
    return client.post(f"/api/v1/agenda/appointments/{appt_id}/status", headers=b["h"], json={"action": action, **extra})


def _summary(client, h):
    t = local_today()
    return client.get(f"/api/v1/finance/summary?start={t.replace(day=1)}&end={t}", headers=h).json()


def _method(client, h, code="pix"):
    return next(m for m in client.get("/api/v1/settings/payment-methods", headers=h).json() if m["code"] == code)


def test_scheduling_is_not_revenue(client, setup_basics):
    b = setup_basics
    assert book(client, b, next_weekday_at(10)).status_code == 201
    s = _summary(client, b["h"])
    assert s["contracted"] == 0 and s["received"] == 0
    assert client.get("/api/v1/finance/receivables", headers=b["h"]).json()["total"] == 0


def test_completion_creates_receivable_and_payment_flow(client, setup_basics):
    b = setup_basics
    a = book(client, b, _past(), override_hours=True).json()["created"][0]
    r = _status(client, b, a["id"], "concluir")
    assert r.status_code == 200 and r.json()["receivable_status"] == "aberto"
    rec_id = r.json()["receivable_id"]
    pix = _method(client, b["h"])
    s = _summary(client, b["h"])
    if _past().date() >= local_today().replace(day=1):
        assert s["contracted"] == 150.0 and s["pending"] == 150.0 and s["received"] == 0
    # pagamento acima do saldo é recusado
    r = client.post(f"/api/v1/finance/receivables/{rec_id}/payments", headers=b["h"],
                    json={"amount": "200.00", "payment_date": str(local_today()), "payment_method_id": pix["id"]})
    assert r.status_code == 400
    # pagamento parcial
    r = client.post(f"/api/v1/finance/receivables/{rec_id}/payments", headers=b["h"],
                    json={"amount": "50.00", "payment_date": str(local_today()), "payment_method_id": pix["id"]})
    assert r.status_code == 201 and r.json()["status"] == "parcial"
    tx_id = r.json()["transaction_id"]
    r = client.post(f"/api/v1/finance/receivables/{rec_id}/payments", headers=b["h"],
                    json={"amount": "100.00", "payment_date": str(local_today()), "payment_method_id": pix["id"]})
    assert r.json()["status"] == "pago"
    assert _summary(client, b["h"])["received"] == 150.0
    # estorno reabre o saldo e reduz a receita recebida
    r = client.post(f"/api/v1/finance/transactions/{tx_id}/reverse", headers=b["h"], json={"reason": "Pagamento duplicado"})
    assert r.status_code == 200
    rec = client.get(f"/api/v1/finance/receivables?q=Massagem", headers=b["h"]).json()["items"][0]
    assert rec["status"] == "parcial" and rec["balance"] == 50.0
    assert _summary(client, b["h"])["received"] == 100.0
    # estorno duplicado é recusado
    assert client.post(f"/api/v1/finance/transactions/{tx_id}/reverse", headers=b["h"], json={"reason": "De novo xx"}).status_code == 400


def test_payment_at_completion(client, setup_basics):
    b = setup_basics
    a = book(client, b, _past(), override_hours=True).json()["created"][0]
    pix = _method(client, b["h"])
    r = _status(client, b, a["id"], "concluir", payment={"amount": "150.00", "payment_method_id": pix["id"]})
    assert r.status_code == 200 and r.json()["receivable_status"] == "pago"


def test_cannot_complete_future_appointment(client, setup_basics):
    b = setup_basics
    a = book(client, b, next_weekday_at(10)).json()["created"][0]
    assert _status(client, b, a["id"], "concluir").status_code == 400
    assert _status(client, b, a["id"], "falta").status_code == 400


def test_cash_closing_blocks_retroactive_entries(client, setup_basics):
    b = setup_basics
    acc = client.get("/api/v1/settings/financial-accounts", headers=b["h"]).json()[0]
    today = local_today()
    r = client.post("/api/v1/finance/closings", headers=b["h"], json={"account_id": acc["id"], "closing_date": str(today)})
    assert r.status_code == 201
    a = book(client, b, _past(), override_hours=True).json()["created"][0]
    rec_id = _status(client, b, a["id"], "concluir").json()["receivable_id"]
    pix = _method(client, b["h"])
    r = client.post(f"/api/v1/finance/receivables/{rec_id}/payments", headers=b["h"],
                    json={"amount": "150.00", "payment_date": str(today), "payment_method_id": pix["id"], "account_id": acc["id"]})
    assert r.status_code == 400 and "fechado" in r.json()["detail"]


def test_expense_with_installments(client, setup_basics):
    b = setup_basics
    cats = client.get("/api/v1/settings/financial-categories", headers=b["h"]).json()
    rent = next(c for c in cats if c["name"] == "Aluguel")
    r = client.post("/api/v1/finance/expenses", headers=b["h"], json={
        "description": "Equipamento maca", "category_id": rent["id"], "competence_date": str(local_today()),
        "amount": "1000.00", "first_due_date": str(local_today()), "installments": 3})
    assert r.status_code == 201
    payables = client.get("/api/v1/finance/payables?q=maca", headers=b["h"]).json()["items"]
    assert sorted(p["amount"] for p in payables) == [333.33, 333.33, 333.34]


def _sell(client, b, sessions=3, **extra):
    body = {"customer_id": b["customer"]["id"], "service_id": b["service"]["id"], "sessions_total": sessions,
            "price": "400.00", **extra}
    return client.post("/api/v1/packages", headers=b["h"], json=body)


def test_package_session_consumed_only_on_completion(client, setup_basics):
    b = setup_basics
    r = _sell(client, b)
    assert r.status_code == 201
    pkg = r.json()["package"]
    assert len(r.json()["receivables"]) == 1
    a = book(client, b, _past(), override_hours=True, package_id=pkg["id"]).json()["created"][0]
    assert a["price"] == 0.0  # coberto pelo pacote
    p = client.get(f"/api/v1/packages/{pkg['id']}", headers=b["h"]).json()["package"]
    assert p["sessions_used"] == 0 and p["reserved"] == 1
    r = _status(client, b, a["id"], "concluir")
    assert r.status_code == 200 and r.json()["receivable_id"] is None  # sem cobrança duplicada
    p = client.get(f"/api/v1/packages/{pkg['id']}", headers=b["h"]).json()["package"]
    assert p["sessions_used"] == 1 and p["sessions_remaining"] == 2
    lead = client.get("/api/v1/crm/leads", headers=b["h"]).json()[0]
    assert lead["stage"] == "pacote_contratado"


def test_package_no_show_rule_and_balance_limit(client, setup_basics):
    b = setup_basics
    pkg = _sell(client, b, sessions=1, no_show_consumes=True).json()["package"]
    a = book(client, b, _past(), override_hours=True, package_id=pkg["id"]).json()["created"][0]
    # saldo totalmente reservado: novo agendamento no pacote é recusado
    r = book(client, b, next_weekday_at(10), package_id=pkg["id"])
    assert r.status_code == 400 and "sessões disponíveis" in r.json()["detail"]
    assert _status(client, b, a["id"], "falta").status_code == 200
    p = client.get(f"/api/v1/packages/{pkg['id']}", headers=b["h"]).json()
    assert p["package"]["sessions_used"] == 1 and p["package"]["status"] == "concluido"
    assert p["sessions"][0]["reason"] == "falta"


def test_package_no_show_without_rule(client, setup_basics):
    b = setup_basics
    pkg = _sell(client, b, sessions=2, no_show_consumes=False).json()["package"]
    a = book(client, b, _past(), override_hours=True, package_id=pkg["id"]).json()["created"][0]
    _status(client, b, a["id"], "falta")
    assert client.get(f"/api/v1/packages/{pkg['id']}", headers=b["h"]).json()["package"]["sessions_used"] == 0


def test_package_late_cancellation_rule(client, setup_basics):
    b = setup_basics
    pkg = _sell(client, b, sessions=2, late_cancel_consumes=True, late_cancel_hours=24).json()["package"]
    soon = datetime.now(clinic_tz()) + timedelta(hours=2)
    a = book(client, b, soon, override_hours=True, package_id=pkg["id"]).json()["created"][0]
    _status(client, b, a["id"], "cancelar", reason="Imprevisto do cliente")
    p = client.get(f"/api/v1/packages/{pkg['id']}", headers=b["h"]).json()
    assert p["package"]["sessions_used"] == 1 and p["sessions"][0]["reason"] == "cancelamento_tardio"


def test_package_other_customer_rejected(client, setup_basics):
    b = setup_basics
    pkg = _sell(client, b).json()["package"]
    other = client.post("/api/v1/customers", headers=b["h"], json={"full_name": "Outra Pessoa"}).json()
    r = client.post("/api/v1/agenda/appointments", headers=b["h"], json={
        "customer_id": other["id"], "service_id": b["service"]["id"], "professional_id": b["prof"]["id"],
        "start_at": next_weekday_at(10).isoformat(), "package_id": pkg["id"]})
    assert r.status_code == 400 and "outro cliente" in r.json()["detail"]


def test_package_installments(client, setup_basics):
    b = setup_basics
    r = _sell(client, b, installments=4)
    assert len(r.json()["receivables"]) == 4


def test_reports_run_and_export(client, setup_basics):
    b = setup_basics
    a = book(client, b, _past(), override_hours=True).json()["created"][0]
    _status(client, b, a["id"], "concluir")
    t = local_today()
    start = (t - timedelta(days=35)).isoformat()
    catalog = client.get("/api/v1/reports", headers=b["h"]).json()
    assert len(catalog) >= 25
    for rep in catalog:
        r = client.get(f"/api/v1/reports/{rep['key']}?start={start}&end={t}", headers=b["h"])
        assert r.status_code == 200, (rep["key"], r.text)
    for fmt, magic in (("csv", b"\xef\xbb\xbf"), ("xlsx", b"PK"), ("pdf", b"%PDF")):
        r = client.get(f"/api/v1/reports/atendimentos/export?start={start}&end={t}&format={fmt}", headers=b["h"])
        assert r.status_code == 200 and r.content.startswith(magic)


def test_dashboard(client, setup_basics):
    b = setup_basics
    r = client.get("/api/v1/dashboard", headers=b["h"])
    assert r.status_code == 200
    data = r.json()
    assert data["operational"]["total_customers"] == 1
    assert "financial" in data and "fiscal" in data
