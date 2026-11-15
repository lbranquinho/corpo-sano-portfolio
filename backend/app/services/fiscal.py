"""Corpo Sano Contábil — emissão de NFS-e com regras de segurança fiscal.

Princípios:
- A nota só é considerada emitida após confirmação de autorização do serviço oficial (HTTP 201 + chave + XML).
- Falha de comunicação NUNCA vira autorização: a nota fica "aguardando_transmissao" e é reprocessada
  consultando primeiro a DPS (GET /dps/{id}) para evitar duplicidade.
- Produção exige cadastro validado pelo contador, certificado válido e liberação explícita.
- Uma operação (conta a receber / pacote / atendimento) não pode ter duas notas ativas.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_bytes, decrypt_str
from app.core.errors import AppError, NotFound
from app.core.settings_store import get_setting
from app.core.storage import save_file
from app.core.utils import is_valid_cnpj, local_now, money, utcnow
from app.integrations.nfse import xml_builder as xb
from app.integrations.nfse.base import FiscalProvider, ProviderResult
from app.integrations.nfse.certificate import LoadedCertificate, load_pfx
from app.integrations.nfse.nacional import NationalProvider
from app.integrations.nfse.signer import sign_xml
from app.models.catalog import TaxServiceCode
from app.models.finance import AccountsReceivable
from app.models.fiscal import (
    ACTIVE_INVOICE_STATUSES,
    DigitalCertificate,
    FiscalInvoice,
    FiscalInvoiceEvent,
    TaxCompanySettings,
)
from app.models.package import Package
from app.models.schedule import Appointment

ENV_CODE = {"producao": 1, "homologacao": 2}
CANCEL_REASONS = {"1": "Erro na emissão", "2": "Serviço não prestado", "9": "Outros"}


def company(db: Session) -> TaxCompanySettings:
    s = db.scalar(select(TaxCompanySettings).limit(1))
    if s is None:
        s = TaxCompanySettings()
        db.add(s)
        db.flush()
    return s


def active_certificate(db: Session) -> DigitalCertificate | None:
    return db.scalar(select(DigitalCertificate).where(DigitalCertificate.is_active.is_(True)).limit(1))


def load_active_certificate(db: Session) -> LoadedCertificate:
    cert = active_certificate(db)
    if cert is None:
        raise AppError("Nenhum certificado digital ativo. Envie o certificado A1 em Contábil > Configurações fiscais.")
    if cert.valid_to <= utcnow():
        raise AppError("O certificado digital ativo está vencido.")
    pfx = decrypt_bytes(cert.pfx_enc.encode("ascii"))
    return load_pfx(pfx, decrypt_str(cert.password_enc) or "")


@dataclass
class Check:
    key: str
    ok: bool
    message: str
    required_for: str  # ambos | producao


def readiness(db: Session) -> list[Check]:
    s = company(db)
    cert = active_certificate(db)
    checks = [
        Check("cnpj", bool(s.cnpj and is_valid_cnpj(s.cnpj)), "CNPJ do prestador válido", "ambos"),
        Check("razao_social", bool(s.legal_name), "Razão social informada", "ambos"),
        Check("municipio", bool(s.ibge_code and len(s.ibge_code) == 7), "Código IBGE do município (7 dígitos)", "ambos"),
        Check("regime", bool(s.tax_regime), "Regime tributário definido", "ambos"),
        Check("opsimpnac", s.op_simples_nacional in (1, 2, 3), "Situação perante o Simples Nacional (opSimpNac) definida", "ambos"),
        Check("regaptribsn", s.op_simples_nacional != 3 or s.reg_ap_trib_sn in (1, 2, 3),
              "Regime de apuração do Simples Nacional (regApTribSN) definido para ME/EPP", "ambos"),
        Check("certificado", bool(cert and cert.valid_to > utcnow()), "Certificado digital A1 ativo e válido", "ambos"),
        Check("certificado_cnpj", bool(cert and s.cnpj and cert.document and cert.document[:8] == s.cnpj[:8]),
              "Certificado pertence ao CNPJ (raiz) do prestador", "ambos"),
        Check("codigos", bool(db.scalar(select(TaxServiceCode.id).where(TaxServiceCode.is_active.is_(True)).limit(1))),
              "Ao menos um código de serviço fiscal cadastrado", "ambos"),
        Check("validado", s.validated, "Cadastro fiscal validado pelo contador", "producao"),
        Check("producao_liberada", s.production_enabled, "Emissão em produção liberada explicitamente", "producao"),
        Check("xsd", xb.schema_path("DPS", s.layout_version) is not None,
              f"Esquema XSD oficial da DPS v{s.layout_version} instalado (validação local)", "producao"),
    ]
    return checks


def ensure_ready(db: Session, environment: str) -> None:
    failed = [c for c in readiness(db) if not c.ok and (c.required_for == "ambos" or environment == "producao")]
    if failed:
        raise AppError("Emissão bloqueada. Pendências: " + "; ".join(c.message for c in failed), code="fiscal_nao_pronto",
                       details=[c.__dict__ for c in failed])


def make_provider(db: Session, environment: str) -> FiscalProvider:
    s = company(db)
    if s.nfse_provider != "nacional":
        raise AppError(f"Provedor fiscal '{s.nfse_provider}' ainda não possui adaptador instalado.")
    suffix = "producao" if environment == "producao" else "homologacao"
    return NationalProvider(
        sefin_url=get_setting(db, f"nfse.sefin_url_{suffix}"),
        adn_url=get_setting(db, f"nfse.adn_url_{suffix}"),
        certificate=load_active_certificate(db),
        timeout=float(get_setting(db, "nfse.timeout_seconds") or 60),
    )


def _event(db: Session, inv: FiscalInvoice, event_type: str, *, success: bool, message: str | None = None,
           http_status: int | None = None, details: dict | None = None, xml: str | None = None,
           code: str | None = None, user_id: uuid.UUID | None = None) -> None:
    db.add(FiscalInvoiceEvent(invoice_id=inv.id, event_type=event_type, success=success, message=message,
                              http_status=http_status, details=details, xml=xml, event_code=code, user_id=user_id))


# ---------------------------------------------------------------- duplicidade
def source_for(db: Session, *, receivable_id: uuid.UUID | None, package_id: uuid.UUID | None,
               appointment_id: uuid.UUID | None) -> tuple[str | None, dict]:
    """Determina a chave da operação e impede emissão duplicada sobre a mesma operação."""
    links: dict = {"receivable_id": receivable_id, "package_id": package_id, "appointment_id": appointment_id}
    if appointment_id:
        appt = db.get(Appointment, appointment_id)
        if appt is None:
            raise NotFound("Atendimento")
        if appt.package_id:
            raise AppError("Atendimento coberto por pacote: a nota deve ser emitida sobre a venda do pacote.")
        rec = db.scalar(select(AccountsReceivable).where(AccountsReceivable.appointment_id == appt.id,
                                                         AccountsReceivable.status != "cancelado"))
        if rec:
            receivable_id = rec.id
            links["receivable_id"] = rec.id
    if receivable_id:
        rec = db.get(AccountsReceivable, receivable_id)
        if rec is None:
            raise NotFound("Conta a receber")
        if rec.status == "cancelado":
            raise AppError("Conta a receber cancelada.")
        if rec.package_id:
            links["package_id"] = rec.package_id
            pkg_inv = db.scalar(select(FiscalInvoice.id).where(FiscalInvoice.source_key == f"package:{rec.package_id}",
                                                               FiscalInvoice.status.in_(ACTIVE_INVOICE_STATUSES)))
            if pkg_inv:
                raise AppError("Já existe nota ativa para o pacote inteiro; não emita nota por parcela.")
        key = f"receivable:{receivable_id}"
    elif package_id:
        if db.get(Package, package_id) is None:
            raise NotFound("Pacote")
        rec_ids = db.scalars(select(AccountsReceivable.id).where(AccountsReceivable.package_id == package_id)).all()
        if rec_ids and db.scalar(select(FiscalInvoice.id).where(
                FiscalInvoice.source_key.in_([f"receivable:{r}" for r in rec_ids]),
                FiscalInvoice.status.in_(ACTIVE_INVOICE_STATUSES))):
            raise AppError("Já existem notas ativas por parcela deste pacote; não emita nota do pacote inteiro.")
        key = f"package:{package_id}"
    elif appointment_id:
        key = f"appointment:{appointment_id}"
    else:
        key = None
    if key and db.scalar(select(FiscalInvoice.id).where(FiscalInvoice.source_key == key,
                                                        FiscalInvoice.status.in_(ACTIVE_INVOICE_STATUSES))):
        raise AppError("Já existe uma nota fiscal ativa (rascunho, em transmissão ou autorizada) para esta operação.")
    return key, links


# ---------------------------------------------------------------- montagem
def compute_amounts(gross: Decimal, unconditional: Decimal, conditional: Decimal, deductions: Decimal,
                    iss_rate: Decimal | None) -> dict[str, Decimal]:
    gross, unconditional, conditional, deductions = (money(v) for v in (gross, unconditional, conditional, deductions))
    if unconditional + conditional >= gross:
        raise AppError("Descontos não podem igualar ou superar o valor do serviço.")
    base = money(gross - unconditional - deductions)
    if base <= 0:
        raise AppError("Base de cálculo inválida.")
    iss = money(base * iss_rate / 100) if iss_rate is not None else None
    return {"net": money(gross - unconditional), "base": base, "iss": iss}


def build_dps_for(db: Session, inv: FiscalInvoice) -> tuple[str, bytes]:
    s = company(db)
    env = ENV_CODE[inv.environment]
    provider = xb.Party(document=s.cnpj, municipal_registration=s.municipal_registration,
                        phone=(s.phone or "")[-11:] or None, email=s.email)
    taker = None
    if inv.taker_document:
        a = inv.taker_address or {}
        taker = xb.Party(document=inv.taker_document, name=inv.taker_name, email=inv.taker_email,
                         phone=(inv.taker_phone or "")[-11:] or None, ibge_code=a.get("ibge_code"),
                         zip_code=a.get("zip_code"), street=a.get("street"), number=a.get("number"),
                         complement=a.get("complement"), district=a.get("district"))
    replaced = db.get(FiscalInvoice, inv.replaces_id) if inv.replaces_id else None
    data = xb.DpsData(
        environment=env, issued_at=inv.issued_at or local_now(), series=inv.dps_series, number=inv.dps_number,
        competence=inv.competence_date, emitter_ibge=s.ibge_code, provider=provider,
        op_simples_nacional=s.op_simples_nacional, reg_ap_trib_sn=s.reg_ap_trib_sn, reg_esp_trib=s.reg_esp_trib or 0,
        taker=taker, service_location_ibge=inv.incidence_ibge or s.ibge_code, national_code=inv.national_code,
        municipal_code=inv.municipal_code, description=inv.description, nbs_code=inv.nbs_code,
        service_amount=inv.gross_amount, unconditional_discount=inv.unconditional_discount,
        conditional_discount=inv.conditional_discount, deductions=inv.deductions, iss_withheld=inv.iss_withheld,
        iss_rate=inv.iss_rate, include_iss_rate=s.op_simples_nacional == 3 and inv.iss_rate is not None,
        federal_retentions={k: v for k, v in (inv.retentions or {}).items() if k in ("irrf", "csll", "cp")},
        total_tax_sn_percent=Decimal(str(inv.tax_info["pTotTribSN"])) if (inv.tax_info or {}).get("pTotTribSN") else None,
        substitution_key=replaced.access_key if replaced else None,
        substitution_code=inv.substitution_reason_code, substitution_reason=inv.substitution_reason,
        layout_version=s.layout_version,
    )
    return xb.build_dps(data)


def reserve_number(db: Session, inv: FiscalInvoice) -> None:
    if inv.dps_number:
        return
    s = db.scalar(select(TaxCompanySettings).with_for_update().limit(1))
    inv.dps_series = s.dps_series
    inv.dps_number = s.next_dps_number
    s.next_dps_number += 1
    db.flush()


def _apply_authorization(db: Session, inv: FiscalInvoice, result: ProviderResult, user_id: uuid.UUID | None) -> None:
    info = xb.parse_nfse(result.nfse_xml)
    inv.status = "autorizada"
    inv.access_key = result.access_key or info.get("access_key")
    inv.nfse_number = info.get("number")
    inv.protocol = info.get("dfe_number")
    inv.nfse_xml = result.nfse_xml.decode("utf-8")
    inv.authorized_at = utcnow()
    inv.last_error = None
    inv.query_url = get_setting(db, "nfse.public_query_url", "https://www.nfse.gov.br/consultapublica")
    _event(db, inv, "autorizacao", success=True, http_status=result.http_status,
           message=f"NFS-e {inv.nfse_number or ''} autorizada", details={**result.raw_summary,
                                                                        "alertas": [a.__dict__ for a in result.alerts]},
           user_id=user_id)
    if inv.replaces_id:
        old = db.get(FiscalInvoice, inv.replaces_id)
        if old:
            old.status, old.replaced_by_id = "substituida", inv.id
            _event(db, old, "substituicao", success=True, message=f"Substituída pela NFS-e {inv.nfse_number}", user_id=user_id)
    db.flush()
    try:  # DANFSe é opcional; falha aqui não afeta a autorização
        fetch_danfse(db, inv, user_id)
    except Exception:  # noqa: BLE001
        _event(db, inv, "danfse", success=False, message="DANFSe não obtido automaticamente; tente novamente depois.")


def transmit(db: Session, inv: FiscalInvoice, user_id: uuid.UUID | None) -> FiscalInvoice:
    if inv.status not in ("rascunho", "rejeitada"):
        raise AppError(f"Nota com situação '{inv.status}' não pode ser transmitida. Use 'Reprocessar'.")
    ensure_ready(db, inv.environment)
    s = company(db)
    if inv.environment != s.nfse_environment:
        raise AppError("O ambiente da nota difere do ambiente fiscal configurado. Recrie o rascunho.")
    reserve_number(db, inv)
    inv.issued_at = local_now()
    ident, xml = build_dps_for(db, inv)
    errors = xb.validate_xsd(xml, "DPS", s.layout_version)
    if errors:
        inv.status, inv.last_error = "rejeitada", "Validação local (XSD): " + "; ".join(errors)
        _event(db, inv, "validacao_local", success=False, message=inv.last_error, user_id=user_id)
        db.flush()
        return inv
    cert = load_active_certificate(db)
    signed = sign_xml(xml, ident, cert, get_setting(db, "nfse.signature_algorithm") or "rsa-sha256")
    inv.dps_id, inv.dps_xml = ident, signed.decode("utf-8")
    inv.status, inv.attempts = "transmitindo", inv.attempts + 1
    _event(db, inv, "transmissao", success=True, message=f"DPS {ident} enviada ({inv.environment})", user_id=user_id)
    db.commit()  # registra o envio antes de chamar o serviço externo
    provider = make_provider(db, inv.environment)
    result = provider.emit(signed)
    if result.ok:
        _apply_authorization(db, inv, result, user_id)
    elif result.communication_failure:
        inv.status = "aguardando_transmissao"
        inv.last_error = "Falha de comunicação: situação desconhecida. Use 'Reprocessar' (consulta a DPS antes de reenviar). " + result.error_text()
        _event(db, inv, "erro_comunicacao", success=False, http_status=result.http_status, message=inv.last_error,
               user_id=user_id)
    else:
        inv.status, inv.last_error = "rejeitada", result.error_text()
        _event(db, inv, "rejeicao", success=False, http_status=result.http_status, message=inv.last_error,
               details={"erros": [e.__dict__ for e in result.errors]}, user_id=user_id)
    db.flush()
    return inv


def reprocess(db: Session, inv: FiscalInvoice, user_id: uuid.UUID | None) -> FiscalInvoice:
    """Para notas com situação desconhecida: consulta a DPS e só reenvia se nenhuma NFS-e foi gerada."""
    if inv.status not in ("aguardando_transmissao", "transmitindo"):
        raise AppError("Reprocessamento disponível apenas para notas aguardando confirmação.")
    if not inv.dps_id or not inv.dps_xml:
        inv.status = "rascunho"
        db.flush()
        return transmit(db, inv, user_id)
    provider = make_provider(db, inv.environment)
    found = provider.get_by_dps(inv.dps_id)
    _event(db, inv, "consulta", success=found.ok, http_status=found.http_status,
           message="Consulta da DPS: " + ("NFS-e localizada" if found.ok else found.error_text()), user_id=user_id)
    if found.ok:
        nfse = provider.get_nfse(found.access_key)
        if nfse.ok:
            _apply_authorization(db, inv, nfse, user_id)
            return inv
        inv.last_error = "DPS processada, mas não foi possível obter o XML da NFS-e: " + nfse.error_text()
        db.flush()
        return inv
    if found.communication_failure:
        inv.last_error = "Serviço fiscal indisponível. Tente reprocessar mais tarde."
        db.flush()
        return inv
    if found.http_status == 404:
        result = provider.emit(inv.dps_xml.encode("utf-8"))
        inv.attempts += 1
        if result.ok:
            _apply_authorization(db, inv, result, user_id)
        elif result.communication_failure:
            inv.last_error = "Nova falha de comunicação. " + result.error_text()
            _event(db, inv, "erro_comunicacao", success=False, message=inv.last_error, user_id=user_id)
        else:
            inv.status, inv.last_error = "rejeitada", result.error_text()
            _event(db, inv, "rejeicao", success=False, http_status=result.http_status, message=inv.last_error,
                   user_id=user_id)
    db.flush()
    return inv


def cancel(db: Session, inv: FiscalInvoice, *, reason_code: str, reason: str, user_id: uuid.UUID | None) -> FiscalInvoice:
    if inv.status != "autorizada" or not inv.access_key:
        raise AppError("Somente NFS-e autorizadas podem ser canceladas.")
    if reason_code not in CANCEL_REASONS:
        raise AppError("Motivo de cancelamento inválido.")
    s = company(db)
    ident, xml = xb.build_cancel_event(environment=ENV_CODE[inv.environment], author_document=s.cnpj,
                                       access_key=inv.access_key, reason_code=reason_code, reason=reason,
                                       issued_at=local_now())
    errors = xb.validate_xsd(xml, "pedRegEvento", "1.00")
    if errors:
        raise AppError("Validação local do evento (XSD) falhou: " + "; ".join(errors))
    signed = sign_xml(xml, ident, load_active_certificate(db), get_setting(db, "nfse.signature_algorithm") or "rsa-sha256")
    provider = make_provider(db, inv.environment)
    result = provider.register_event(inv.access_key, signed)
    if result.ok:
        inv.status, inv.cancelled_at = "cancelada", utcnow()
        inv.cancel_reason_code, inv.cancel_reason = reason_code, reason
        _event(db, inv, "cancelamento", success=True, http_status=result.http_status, code="101101",
               message=f"Cancelada: {CANCEL_REASONS[reason_code]} — {reason}",
               xml=result.event_xml.decode("utf-8") if result.event_xml else None, user_id=user_id)
    else:
        _event(db, inv, "cancelamento", success=False, http_status=result.http_status, code="101101",
               message=result.error_text(), user_id=user_id)
        db.flush()
        raise AppError("Cancelamento não confirmado pelo serviço fiscal: " + result.error_text(),
                       code="cancelamento_rejeitado")
    db.flush()
    return inv


def refresh(db: Session, inv: FiscalInvoice, user_id: uuid.UUID | None) -> dict:
    if not inv.access_key:
        raise AppError("Nota sem chave de acesso.")
    provider = make_provider(db, inv.environment)
    nfse = provider.get_nfse(inv.access_key)
    events = provider.list_events(inv.access_key)
    _event(db, inv, "consulta", success=nfse.ok, http_status=nfse.http_status,
           message="Consulta de situação" + ("" if nfse.ok else ": " + nfse.error_text()),
           details={"eventos": events.raw_summary.get("eventos")} if events.ok else None, user_id=user_id)
    if nfse.ok and nfse.nfse_xml:
        inv.nfse_xml = nfse.nfse_xml.decode("utf-8")
    db.flush()
    return {"nfse_found": nfse.ok, "events": events.raw_summary.get("eventos") if events.ok else None}


def fetch_danfse(db: Session, inv: FiscalInvoice, user_id: uuid.UUID | None) -> bool:
    if not inv.access_key:
        return False
    provider = make_provider(db, inv.environment)
    res = provider.download_danfse(inv.access_key)
    if res.ok and res.pdf:
        f = save_file(db, res.pdf, filename=f"DANFSe_{inv.nfse_number or inv.access_key}.pdf",
                      content_type="application/pdf", category="fiscal", user_id=user_id, fiscal_invoice_id=inv.id)
        inv.danfse_file_id = f.id
        _event(db, inv, "danfse", success=True, message="DANFSe armazenado", user_id=user_id)
        db.flush()
        return True
    return False


def preview(db: Session, inv: FiscalInvoice) -> dict:
    s = company(db)
    draft_number = inv.dps_number or s.next_dps_number
    tmp_number, tmp_series = inv.dps_number, inv.dps_series
    inv.dps_number, inv.dps_series = draft_number, inv.dps_series or s.dps_series
    try:
        ident, xml = build_dps_for(db, inv)
        errors = xb.validate_xsd(xml, "DPS", s.layout_version)
    finally:
        inv.dps_number, inv.dps_series = tmp_number, tmp_series
    return {"dps_id": ident, "xml": xml.decode("utf-8"), "xsd_errors": errors,
            "xsd_available": errors is not None,
            "note": "Prévia sem assinatura. O número da DPS é reservado somente na transmissão."}


def date_ok(d: date) -> None:
    from app.core.utils import local_today

    if d > local_today():
        raise AppError("A data de competência não pode ser futura.")
