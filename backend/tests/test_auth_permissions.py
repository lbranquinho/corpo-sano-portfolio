from datetime import timedelta

from sqlalchemy import select

from app.models.system import AuditLog
from tests.conftest import PASSWORD, VALID_CPF_2, book, login, make_user, next_weekday_at


def test_login_and_me(client, admin):
    r = client.get("/api/v1/auth/me", headers=admin)
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "admin"
    assert "fiscal.issue" in data["permissions"]


def test_wrong_password_is_generic_and_locks(client):
    make_user("x@clinica.com.br", "recepcionista")
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"email": "x@clinica.com.br", "password": "errada123"})
        assert r.status_code == 401
        assert r.json()["detail"] == "E-mail ou senha inválidos."
    r = client.post("/api/v1/auth/login", json={"email": "x@clinica.com.br", "password": PASSWORD})
    assert r.status_code == 423  # bloqueado após 5 tentativas


def test_unknown_user_same_message(client):
    r = client.post("/api/v1/auth/login", json={"email": "ninguem@clinica.com.br", "password": "qualquer123"})
    assert r.status_code == 401
    assert r.json()["detail"] == "E-mail ou senha inválidos."


def test_must_change_password_blocks_modules(client):
    make_user("novo@clinica.com.br", "recepcionista", must_change=True)
    h = login(client, "novo@clinica.com.br")
    assert client.get("/api/v1/customers", headers=h).status_code == 403
    r = client.post("/api/v1/auth/change-password", headers=h,
                    json={"current_password": PASSWORD, "new_password": "OutraSenha456"})
    assert r.status_code == 200
    assert client.get("/api/v1/customers", headers=h).status_code == 200


def test_weak_password_rejected(client, admin):
    r = client.post("/api/v1/auth/change-password", headers=admin,
                    json={"current_password": PASSWORD, "new_password": "curta"})
    assert r.status_code == 400


def test_refresh_rotation_and_logout(client, admin):
    old_cookie = client.cookies.get("cs_refresh")
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200
    assert client.cookies.get("cs_refresh") != old_cookie
    client.post("/api/v1/auth/logout")
    assert client.post("/api/v1/auth/refresh").status_code == 204  # cookie apagado: sem sessão
    # o access token da sessão encerrada também deixa de valer
    assert client.get("/api/v1/auth/me", headers=admin).status_code == 401


def test_receptionist_cannot_access_finance_or_fiscal(client):
    make_user("rec@clinica.com.br", "recepcionista")
    h = login(client, "rec@clinica.com.br")
    assert client.get("/api/v1/finance/summary?start=2026-01-01&end=2026-01-31", headers=h).status_code == 403
    assert client.get("/api/v1/fiscal/invoices", headers=h).status_code == 403
    assert client.get("/api/v1/users", headers=h).status_code == 403
    assert client.get("/api/v1/customers", headers=h).status_code == 200


def test_accountant_restricted_to_fiscal(client):
    make_user("contador@clinica.com.br", "contador")
    h = login(client, "contador@clinica.com.br")
    assert client.get("/api/v1/fiscal/invoices", headers=h).status_code == 200
    assert client.get("/api/v1/fiscal/exports", headers=h).status_code == 200
    assert client.get("/api/v1/customers", headers=h).status_code == 403
    assert client.get("/api/v1/agenda/appointments?start=2026-01-01&end=2026-01-02", headers=h).status_code == 403


def test_therapist_sees_only_own_customers_and_agenda(client, setup_basics):
    b = setup_basics
    start = next_weekday_at(10)
    assert book(client, b, start).status_code == 201
    other = client.post("/api/v1/customers", headers=b["h"], json={"full_name": "Outro Cliente", "cpf": VALID_CPF_2}).json()
    book_body = {"customer_id": other["id"], "service_id": b["service"]["id"], "professional_id": b["prof2"]["id"],
                 "start_at": (start + timedelta(hours=3)).isoformat()}
    assert client.post("/api/v1/agenda/appointments", headers=b["h"], json=book_body).status_code == 201
    make_user("ana@clinica.com.br", "massoterapeuta", professional_id=b["prof"]["id"])
    h = login(client, "ana@clinica.com.br")
    names = [c["full_name"] for c in client.get("/api/v1/customers", headers=h).json()["items"]]
    assert names == ["Maria José da Silva"]
    assert client.get(f"/api/v1/customers/{other['id']}", headers=h).status_code == 403
    day = start.date().isoformat()
    appts = client.get(f"/api/v1/agenda/appointments?start={day}&end={day}", headers=h).json()
    assert len(appts) == 1 and appts[0]["professional_id"] == b["prof"]["id"]


def test_user_permission_override(client, admin):
    rec = make_user("rec2@clinica.com.br", "recepcionista")
    r = client.put(f"/api/v1/users/{rec.id}/permissions", headers=admin, json=[{"code": "customers.write", "allow": False}])
    assert r.status_code == 200
    h = login(client, "rec2@clinica.com.br")
    assert client.post("/api/v1/customers", headers=h, json={"full_name": "Fulano de Tal"}).status_code == 403


def test_cannot_remove_last_admin(client, admin, db):
    me = client.get("/api/v1/auth/me", headers=admin).json()
    roles = client.get("/api/v1/roles", headers=admin).json()
    rec_role = next(r for r in roles if r["code"] == "recepcionista")
    r = client.put(f"/api/v1/users/{me['id']}", headers=admin,
                   json={"name": "Admin", "email": me["email"], "role_id": rec_role["id"], "is_active": True})
    assert r.status_code == 400


def test_audit_log_records_login(client, admin, db):
    actions = db.scalars(select(AuditLog.action)).all()
    assert "login" in actions


def test_login_sql_injection_is_rejected(client, admin, db):
    from app.models.auth import User

    before = len(db.scalars(select(User.id)).all())
    for payload in ["' OR '1'='1' --", "x@x.com'; DROP TABLE users; --", "admin@clinica.com.br' --"]:
        r = client.post("/api/v1/auth/login", json={"email": payload, "password": "' OR 1=1 --"})
        assert r.status_code == 401
        assert r.json()["detail"] == "E-mail ou senha inválidos."
    assert len(db.scalars(select(User.id)).all()) == before  # tabela intacta


def test_like_wildcards_are_literal(client, admin):
    from app.core.utils import escape_like, like_contains

    assert escape_like("50%_a\\b") == "50\\%\\_a\\\\b"
    assert like_contains("%") == "%\\%%"
    # sem escape, "%" casaria com todas as ações da auditoria; agora procura o caractere literal
    r = client.get("/api/v1/audit-logs", headers=admin, params={"action": "%"})
    assert r.status_code == 200
    assert r.json()["total"] == 0
    r = client.get("/api/v1/audit-logs", headers=admin, params={"action": "login"})
    assert r.json()["total"] >= 1


def test_forwarded_ip_only_from_trusted_proxy(monkeypatch):
    from types import SimpleNamespace

    from app.core import deps

    req = SimpleNamespace(client=SimpleNamespace(host="192.168.1.50"), headers={"x-forwarded-for": "1.2.3.4"})
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(trusted_proxies="172.16.0.0/12"))
    assert deps.client_ip(req) == "192.168.1.50"  # cabeçalho ignorado: origem não é proxy
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(trusted_proxies=""))
    assert deps.client_ip(req) == "192.168.1.50"  # instalação local: nunca confia
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(trusted_proxies="192.168.0.0/16"))
    assert deps.client_ip(req) == "1.2.3.4"  # proxy confiável: usa o IP encaminhado


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
