"""Regras fiscais: duplicidade, prontidão, DPS assinada, autorização somente com confirmação oficial."""
import base64
import gzip
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from app.core.utils import clinic_tz, local_today
from app.integrations.nfse import xml_builder as xb
from app.integrations.nfse.certificate import inspect_pfx, load_pfx
from app.integrations.nfse.nacional import NationalProvider
from app.integrations.nfse.signer import sign_xml, verify_xml
from app.services import fiscal as fiscal_svc
from tests.conftest import VALID_CNPJ, book

CERT_PASSWORD = "senha-do-certificado"
ACCESS_KEY = "3550308" + "2" * 43  # 50 dígitos (formato)


def make_pfx(cnpj: str = VALID_CNPJ) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"CLINICA TESTE LTDA:{cnpj}"),
                      x509.NameAttribute(NameOID.COUNTRY_NAME, "BR")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365)).sign(key, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(b"teste", key, cert, None,
                                                 serialization.BestAvailableEncryption(CERT_PASSWORD.encode()))


def configure_company(client, h, regime="simples_nacional", op=3):
    r = client.put("/api/v1/fiscal/company", headers=h, json={
        "legal_name": "Clínica Teste Ltda", "cnpj": VALID_CNPJ, "municipal_registration": "123456",
        "ibge_code": "3550308", "uf": "SP", "municipality_name": "São Paulo", "tax_regime": regime,
        "op_simples_nacional": op, "reg_ap_trib_sn": 1 if op == 3 else None, "reg_esp_trib": 0,
        "dps_series": "1", "next_dps_number": 1, "layout_version": "1.01"})
    assert r.status_code == 200, r.text
    code = client.post("/api/v1/tax-service-codes", headers=h, json={
        "national_code": "060201", "description": "Código informado pelo contador (teste)", "iss_rate": "2.00",
        "validated": True, "validated_by": "Contador Teste"}).json()
    return code


def upload_cert(client, h):
    r = client.post("/api/v1/fiscal/certificates", headers=h, files={"file": ("cert.pfx", make_pfx(), "application/x-pkcs12")},
                    data={"password": CERT_PASSWORD, "alias": "A1 teste"})
    assert r.status_code == 201, r.text


def completed_receivable(client, b):
    start = datetime.now(clinic_tz()).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    a = book(client, b, start, override_hours=True).json()["created"][0]
    r = client.post(f"/api/v1/agenda/appointments/{a['id']}/status", headers=b["h"], json={"action": "concluir"})
    return a, r.json()["receivable_id"]


def invoice_body(code_id, rec_id=None, **extra):
    return {"tax_service_code_id": code_id, "description": "Sessão de massagem relaxante", "competence_date": str(local_today()),
            "gross_amount": "150.00", "taker_document": "52998224725", "taker_name": "Maria José da Silva",
            "receivable_id": rec_id, **extra}


# ------------------------------------------------------------------ XML/assinatura
def test_dps_id_format():
    ident = xb.dps_id("3550308", VALID_CNPJ, "1", 7)
    assert ident == "DPS" + "3550308" + "2" + VALID_CNPJ + "00001" + "7".zfill(15)
    assert len(ident) == 45


def test_build_and_sign_dps_verifies():
    pfx = make_pfx()
    info = inspect_pfx(pfx, CERT_PASSWORD)
    assert info.document == VALID_CNPJ
    cert = load_pfx(pfx, CERT_PASSWORD)
    data = xb.DpsData(environment=2, issued_at=datetime.now(clinic_tz()), series="1", number=1,
                      competence=local_today(), emitter_ibge="3550308", provider=xb.Party(document=VALID_CNPJ),
                      op_simples_nacional=3, reg_ap_trib_sn=1, reg_esp_trib=0, taker=xb.Party(document="52998224725", name="Maria"),
                      service_location_ibge="3550308", national_code="060201", municipal_code=None,
                      description="Sessão de massagem", nbs_code=None, service_amount=__import__("decimal").Decimal("150"))
    ident, xml = xb.build_dps(data)
    signed = sign_xml(xml, ident, cert)
    assert verify_xml(signed, cert.cert_pem)
    root = etree.fromstring(signed)
    assert root.tag == "{http://www.sped.fazenda.gov.br/nfse}DPS"
    assert root.find("{http://www.w3.org/2000/09/xmldsig#}Signature") is not None
    # adulteração invalida a assinatura
    tampered = signed.replace(b"150.00", b"15.00")
    assert not verify_xml(tampered, cert.cert_pem)


def test_signature_matches_libxmlsec1_reference():
    """Validação cruzada com a libxmlsec1 (implementação de referência XMLDSig), quando instalada."""
    xmlsec = pytest.importorskip("xmlsec")
    cert = load_pfx(make_pfx(), CERT_PASSWORD)
    ident, ev = xb.build_cancel_event(environment=2, author_document=VALID_CNPJ, access_key=ACCESS_KEY, reason_code="1",
                                      reason="Erro na emissão do valor do serviço", issued_at=datetime.now(clinic_tz()))
    signed = sign_xml(ev, ident, cert)
    root = etree.fromstring(signed)
    xmlsec.tree.add_ids(root, ["Id"])
    ctx = xmlsec.SignatureContext()
    ctx.key = xmlsec.Key.from_memory(cert.cert_pem, xmlsec.constants.KeyDataFormatCertPem, None)
    ctx.verify(root.find("{http://www.w3.org/2000/09/xmldsig#}Signature"))  # lança exceção se inválida


def test_cancel_event_requires_reason_length():
    with pytest.raises(xb.DpsError):
        xb.build_cancel_event(environment=2, author_document=VALID_CNPJ, access_key=ACCESS_KEY, reason_code="1",
                              reason="curto", issued_at=datetime.now(clinic_tz()))


# ------------------------------------------------------------------ Regras de emissão
def test_transmission_blocked_without_configuration(client, setup_basics):
    b = setup_basics
    code = configure_company(client, b["h"])
    _, rec = completed_receivable(client, b)
    inv = client.post("/api/v1/fiscal/invoices", headers=b["h"], json=invoice_body(code["id"], rec)).json()["invoice"]
    r = client.post(f"/api/v1/fiscal/invoices/{inv['id']}/transmit", headers=b["h"])
    assert r.status_code == 400 and "Certificado" in r.json()["detail"]
    assert client.get(f"/api/v1/fiscal/invoices/{inv['id']}", headers=b["h"]).json()["status"] == "rascunho"


def test_duplicate_invoice_for_same_operation(client, setup_basics):
    b = setup_basics
    code = configure_company(client, b["h"])
    _, rec = completed_receivable(client, b)
    assert client.post("/api/v1/fiscal/invoices", headers=b["h"], json=invoice_body(code["id"], rec)).status_code == 201
    r = client.post("/api/v1/fiscal/invoices", headers=b["h"], json=invoice_body(code["id"], rec))
    assert r.status_code == 400 and "ativa" in r.json()["detail"]


def test_package_appointment_cannot_be_invoiced_individually(client, setup_basics):
    b = setup_basics
    code = configure_company(client, b["h"])
    pkg = client.post("/api/v1/packages", headers=b["h"], json={
        "customer_id": b["customer"]["id"], "service_id": b["service"]["id"], "sessions_total": 2, "price": "250.00"}).json()
    start = datetime.now(clinic_tz()).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    a = book(client, b, start, override_hours=True, package_id=pkg["package"]["id"]).json()["created"][0]
    r = client.post("/api/v1/fiscal/invoices", headers=b["h"], json=invoice_body(code["id"], appointment_id=a["id"]))
    assert r.status_code == 400 and "pacote" in r.json()["detail"]
    # nota do pacote inteiro OK; depois, nota por parcela é bloqueada
    assert client.post("/api/v1/fiscal/invoices", headers=b["h"],
                       json=invoice_body(code["id"], package_id=pkg["package"]["id"], gross_amount="250.00")).status_code == 201
    r = client.post("/api/v1/fiscal/invoices", headers=b["h"], json=invoice_body(code["id"], pkg["receivables"][0]))
    assert r.status_code == 400


def _mock_provider(handler):
    def factory(db, environment):
        return NationalProvider(sefin_url="https://sefin.test/SefinNacional", adn_url="https://adn.test",
                                certificate=fiscal_svc.load_active_certificate(db), transport=httpx.MockTransport(handler))
    return factory


def _nfse_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    dps = gzip.decompress(base64.b64decode(body["dpsXmlGZipB64"]))
    root = etree.fromstring(dps)
    ident = root.find("{http://www.sped.fazenda.gov.br/nfse}infDPS").get("Id")
    nfse = (f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01"><infNFSe Id="NFS{ACCESS_KEY}">'
            f"<nNFSe>15</nNFSe><dhProc>2026-11-12T10:00:00-03:00</dhProc><nDFSe>998877</nDFSe><cStat>100</cStat>"
            f"</infNFSe></NFSe>").encode()
    return httpx.Response(201, json={"tipoAmbiente": 2, "versaoAplicativo": "x", "dataHoraProcessamento": "2026-11-12T10:00:00",
                                     "idDps": ident, "chaveAcesso": ACCESS_KEY,
                                     "nfseXmlGZipB64": base64.b64encode(gzip.compress(nfse)).decode()})


def _ready_invoice(client, b):
    code = configure_company(client, b["h"])
    upload_cert(client, b["h"])
    _, rec = completed_receivable(client, b)
    return client.post("/api/v1/fiscal/invoices", headers=b["h"], json=invoice_body(code["id"], rec)).json()["invoice"]


def test_authorized_only_with_official_confirmation(client, setup_basics, monkeypatch):
    b = setup_basics
    inv = _ready_invoice(client, b)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/nfse") and request.method == "POST":
            return _nfse_response(request)
        return httpx.Response(404, json={})

    monkeypatch.setattr(fiscal_svc, "make_provider", _mock_provider(handler))
    r = client.post(f"/api/v1/fiscal/invoices/{inv['id']}/transmit", headers=b["h"])
    assert r.status_code == 200, r.text
    data = r.json()["invoice"]
    assert data["status"] == "autorizada" and data["nfse_number"] == "15" and data["access_key"] == ACCESS_KEY
    assert data["has_nfse_xml"] and data["dps_number"] == 1
    # a numeração avançou e a DPS foi assinada
    assert client.get("/api/v1/fiscal/company", headers=b["h"]).json()["next_dps_number"] == 2


def test_rejection_keeps_invoice_not_issued(client, setup_basics, monkeypatch):
    b = setup_basics
    inv = _ready_invoice(client, b)

    def handler(request):
        return httpx.Response(400, json={"tipoAmbiente": 2, "versaoAplicativo": "x", "dataHoraProcessamento": "x",
                                         "erros": [{"codigo": "E0001", "descricao": "Erro de teste"}]})

    monkeypatch.setattr(fiscal_svc, "make_provider", _mock_provider(handler))
    data = client.post(f"/api/v1/fiscal/invoices/{inv['id']}/transmit", headers=b["h"]).json()["invoice"]
    assert data["status"] == "rejeitada" and "E0001" in data["last_error"] and data["nfse_number"] is None


def test_communication_failure_never_simulates_issue(client, setup_basics, monkeypatch):
    b = setup_basics
    inv = _ready_invoice(client, b)

    def down(request):
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(fiscal_svc, "make_provider", _mock_provider(down))
    data = client.post(f"/api/v1/fiscal/invoices/{inv['id']}/transmit", headers=b["h"]).json()["invoice"]
    assert data["status"] == "aguardando_transmissao" and data["access_key"] is None

    # reprocessamento: consulta a DPS primeiro; como foi gerada, recupera a NFS-e sem reenviar
    sent = []

    def recovered(request):
        sent.append((request.method, request.url.path))
        if request.url.path.startswith("/SefinNacional/dps/"):
            return httpx.Response(200, json={"tipoAmbiente": 2, "versaoAplicativo": "x", "dataHoraProcessamento": "x",
                                             "idDps": "x", "chaveAcesso": ACCESS_KEY})
        if request.url.path == f"/SefinNacional/nfse/{ACCESS_KEY}":
            nfse = f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe Id="NFS{ACCESS_KEY}"><nNFSe>16</nNFSe></infNFSe></NFSe>'
            return httpx.Response(200, json={"tipoAmbiente": 2, "versaoAplicativo": "x", "dataHoraProcessamento": "x",
                                             "chaveAcesso": ACCESS_KEY,
                                             "nfseXmlGZipB64": base64.b64encode(gzip.compress(nfse.encode())).decode()})
        return httpx.Response(404, json={})

    monkeypatch.setattr(fiscal_svc, "make_provider", _mock_provider(recovered))
    data = client.post(f"/api/v1/fiscal/invoices/{inv['id']}/reprocess", headers=b["h"]).json()["invoice"]
    assert data["status"] == "autorizada" and data["nfse_number"] == "16"
    assert not any(m == "POST" and p.endswith("/nfse") for m, p in sent)  # não reenviou


def test_production_requires_validation(client, setup_basics):
    b = setup_basics
    configure_company(client, b["h"])
    upload_cert(client, b["h"])
    r = client.post("/api/v1/fiscal/company/production?enabled=true", headers=b["h"])
    assert r.status_code == 400 and "validado" in r.json()["detail"]
    r = client.put("/api/v1/fiscal/company/environment", headers=b["h"], json={"environment": "producao"})
    assert r.status_code == 400


def test_certificate_must_match_cnpj(client, setup_basics):
    b = setup_basics
    configure_company(client, b["h"])
    other = make_pfx("33000167000101")
    r = client.post("/api/v1/fiscal/certificates", headers=b["h"], files={"file": ("c.pfx", other, "application/x-pkcs12")},
                    data={"password": CERT_PASSWORD})
    assert r.status_code == 400 and "CNPJ" in r.json()["detail"]


def test_tax_estimate_requires_rules(client, setup_basics):
    b = setup_basics
    configure_company(client, b["h"])
    period = f"{local_today():%Y-%m}"
    r = client.post(f"/api/v1/fiscal/assessments/estimate?period={period}", headers=b["h"])
    assert r.status_code == 400  # nada é presumido
    client.post("/api/v1/fiscal/tax-rates", headers=b["h"], json={
        "tax": "SIMPLES", "regime": "simples_nacional", "rate": "6.0000", "valid_from": "2026-01-01",
        "description": "Alíquota efetiva informada pelo contador"})
    r = client.post(f"/api/v1/fiscal/assessments/estimate?period={period}&source=contratada", headers=b["h"])
    assert r.status_code == 200 and "ESTIMATIVA" in r.json()["items"][0]["calculation_notes"]


def test_obligations_only_from_active_templates(client, setup_basics):
    b = setup_basics
    configure_company(client, b["h"])
    period = f"{local_today():%Y-%m}"
    r = client.post(f"/api/v1/fiscal/obligations/generate?period={period}", headers=b["h"])
    assert "0 obrigação" in r.json()["message"]  # nenhum modelo ativo por padrão
    tpl = next(t for t in client.get("/api/v1/fiscal/obligation-templates", headers=b["h"]).json() if t["code"] == "PGDAS-D")
    client.put(f"/api/v1/fiscal/obligation-templates/{tpl['id']}", headers=b["h"], json={**tpl, "is_active": True})
    r = client.post(f"/api/v1/fiscal/obligations/generate?period={period}", headers=b["h"])
    assert "1 obrigação" in r.json()["message"]


def test_accounting_export_zip(client, setup_basics):
    b = setup_basics
    _, rec = completed_receivable(client, b)
    t = local_today()
    r = client.post("/api/v1/fiscal/exports", headers=b["h"], json={"start": str(t.replace(day=1) - timedelta(days=31)), "end": str(t)})
    assert r.status_code == 201, r.text
    exp = r.json()["export"]
    z = client.get(f"/api/v1/fiscal/exports/{exp['id']}/download", headers=b["h"])
    assert z.status_code == 200 and z.content.startswith(b"PK")
    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert "LEIAME.txt" in names and "relatorios/relatorios.xlsx" in names and "relatorios/relatorios.pdf" in names
