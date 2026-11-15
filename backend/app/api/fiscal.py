"""Corpo Sano Contábil — rotas do módulo contábil e fiscal."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.crud import make_crud
from app.core.audit import audit
from app.core.crypto import encrypt_bytes, encrypt_str
from app.core.database import get_db
from app.core.deps import has_perm, require, require_any
from app.core.errors import AppError, NotFound
from app.core.storage import read_file, save_file
from app.core.utils import local_today, money, only_digits, utcnow
from app.integrations.nfse.certificate import CertificateError, inspect_pfx
from app.models.auth import User
from app.models.catalog import Service, TaxServiceCode
from app.models.customer import Customer
from app.models.finance import AccountsPayable, AccountsReceivable
from app.models.fiscal import (
    ACTIVE_INVOICE_STATUSES,
    TAX_REGIMES,
    AccountingExport,
    DigitalCertificate,
    FiscalDocument,
    FiscalInvoice,
    TaxAssessment,
    TaxObligation,
    TaxObligationTemplate,
    TaxRate,
)
from app.models.package import Package
from app.models.system import StoredFile
from app.schemas.common import ORM, CepStr, CnpjStr, DocumentStr, IbgeStr, Money, Page, PhoneStr, StrippedModel, UfStr
from app.services import accounting
from app.services import fiscal as svc
from app.services import taxes as tax_svc

router = APIRouter(prefix="/fiscal", tags=["Contábil e Fiscal"])
SENSITIVE_COMPANY_FIELDS = {"cnpj", "ibge_code", "tax_regime", "op_simples_nacional", "reg_ap_trib_sn", "reg_esp_trib",
                            "municipal_registration", "layout_version", "nfse_provider"}


# ================================================================ Cadastro fiscal
class CompanyIn(StrippedModel):
    legal_name: str | None = Field(default=None, max_length=150)
    trade_name: str | None = Field(default=None, max_length=150)
    cnpj: CnpjStr = None
    municipal_registration: str | None = Field(default=None, max_length=20)
    state_registration: str | None = Field(default=None, max_length=20)
    zip_code: CepStr = None
    street: str | None = None
    number: str | None = None
    complement: str | None = None
    district: str | None = None
    municipality_name: str | None = None
    uf: UfStr = None
    ibge_code: IbgeStr = None
    phone: PhoneStr = None
    email: EmailStr | None = None
    cnae_main: str | None = Field(default=None, max_length=10)
    cnaes_secondary: list[str] = Field(default_factory=list)
    tax_regime: str | None = None
    regime_details: str | None = None
    op_simples_nacional: int | None = Field(default=None, ge=1, le=3)
    reg_ap_trib_sn: int | None = Field(default=None, ge=1, le=3)
    reg_esp_trib: int = Field(default=0, ge=0, le=9)
    opening_date: date | None = None
    legal_representative: str | None = None
    legal_representative_cpf: str | None = None
    accountant_name: str | None = None
    accountant_crc: str | None = None
    accountant_email: EmailStr | None = None
    accountant_phone: PhoneStr = None
    accountant_document: DocumentStr = None
    has_employees: bool = False
    dps_series: str = Field(default="1", pattern=r"^\d{1,5}$")
    next_dps_number: int = Field(default=1, ge=1)
    layout_version: str = Field(default="1.01", pattern=r"^\d\.\d{2}$")


class ValidateIn(BaseModel):
    accountant_name: str = Field(min_length=3, max_length=150)
    notes: str | None = Field(default=None, max_length=2000)


class EnvironmentIn(BaseModel):
    environment: str = Field(pattern=r"^(homologacao|producao)$")


def _company_out(db: Session) -> dict:
    s = svc.company(db)
    data = {c.name: getattr(s, c.name) for c in s.__table__.columns}
    data["id"] = str(s.id)
    data["readiness"] = [c.__dict__ for c in svc.readiness(db)]
    data["dps_number_used"] = bool(db.scalar(select(FiscalInvoice.id).where(FiscalInvoice.dps_number.is_not(None)).limit(1)))
    return data


@router.get("/company")
def get_company(db: Session = Depends(get_db), user: User = Depends(require("fiscal.read"))):
    return _company_out(db)


@router.put("/company")
def update_company(data: CompanyIn, db: Session = Depends(get_db), user: User = Depends(require("fiscal.settings"))):
    s = svc.company(db)
    if data.tax_regime and data.tax_regime not in TAX_REGIMES:
        raise AppError("Regime tributário inválido.")
    values = data.model_dump()
    if db.scalar(select(FiscalInvoice.id).where(FiscalInvoice.dps_number.is_not(None)).limit(1)):
        if values["next_dps_number"] < s.next_dps_number or values["dps_series"] != s.dps_series:
            raise AppError("Já existem DPS numeradas: a série não pode mudar e o próximo número não pode retroceder.")
    changed = [k for k, v in values.items() if getattr(s, k) != v]
    for k, v in values.items():
        setattr(s, k, v)
    s.updated_by = user.id
    if SENSITIVE_COMPANY_FIELDS & set(changed) and s.validated:
        s.validated, s.production_enabled, s.validated_at = False, False, None
        s.nfse_environment = "homologacao"
        msg = "Cadastro salvo. Campos fiscais relevantes mudaram: a validação do contador foi revogada e a emissão voltou para homologação."
    else:
        msg = "Cadastro fiscal salvo."
    audit(db, "cadastro_fiscal_alterado", user=user, entity="tax_company_settings", entity_id=s.id, details={"campos": changed})
    db.commit()
    return {"message": msg, "company": _company_out(db)}


@router.post("/company/validate")
def validate_company(data: ValidateIn, db: Session = Depends(get_db), user: User = Depends(require_any("fiscal.settings", "fiscal.taxes"))):
    s = svc.company(db)
    failed = [c.message for c in svc.readiness(db) if not c.ok and c.required_for == "ambos"]
    if failed:
        raise AppError("Complete o cadastro antes da validação: " + "; ".join(failed))
    s.validated, s.validated_at, s.validated_by_name, s.validation_notes = True, utcnow(), data.accountant_name, data.notes
    audit(db, "cadastro_fiscal_validado", user=user, entity="tax_company_settings", entity_id=s.id,
          details={"contador": data.accountant_name})
    db.commit()
    return {"message": "Cadastro fiscal marcado como validado pelo contador.", "company": _company_out(db)}


@router.post("/company/production")
def toggle_production(enabled: bool, db: Session = Depends(get_db), user: User = Depends(require("fiscal.settings"))):
    s = svc.company(db)
    if enabled:
        if not s.validated:
            raise AppError("A emissão em produção exige o cadastro validado pelo contador.")
        homolog_ok = db.scalar(select(FiscalInvoice.id).where(FiscalInvoice.environment == "homologacao",
                                                              FiscalInvoice.status == "autorizada").limit(1))
        if not homolog_ok:
            raise AppError("Emita e confira ao menos uma NFS-e autorizada em homologação antes de liberar produção.")
    s.production_enabled = enabled
    if not enabled:
        s.nfse_environment = "homologacao"
    audit(db, "producao_fiscal_" + ("liberada" if enabled else "bloqueada"), user=user, entity="tax_company_settings")
    db.commit()
    return {"message": "Produção " + ("liberada." if enabled else "bloqueada; ambiente retornou para homologação."),
            "company": _company_out(db)}


@router.put("/company/environment")
def set_environment(data: EnvironmentIn, db: Session = Depends(get_db), user: User = Depends(require("fiscal.settings"))):
    s = svc.company(db)
    if data.environment == "producao":
        svc.ensure_ready(db, "producao")
    s.nfse_environment = data.environment
    audit(db, "ambiente_fiscal_alterado", user=user, details={"ambiente": data.environment})
    db.commit()
    return {"message": f"Ambiente fiscal: {data.environment}.", "company": _company_out(db)}


# ================================================================ Certificados
@router.get("/certificates")
def list_certificates(db: Session = Depends(get_db), user: User = Depends(require("fiscal.read"))):
    return [{"id": str(c.id), "alias": c.alias, "subject": c.subject, "issuer": c.issuer, "document": c.document,
             "valid_from": c.valid_from, "valid_to": c.valid_to, "is_active": c.is_active, "uploaded_at": c.uploaded_at,
             "expired": c.valid_to <= utcnow(), "days_to_expire": (c.valid_to - utcnow()).days}
            for c in db.scalars(select(DigitalCertificate).order_by(DigitalCertificate.uploaded_at.desc())).all()]


@router.post("/certificates", status_code=201)
async def upload_certificate(file: UploadFile = File(...), password: str = Form(...), alias: str = Form("Certificado A1"),
                             activate: bool = Form(True), db: Session = Depends(get_db),
                             user: User = Depends(require("fiscal.settings"))):
    data = await file.read()
    if len(data) > 100 * 1024:
        raise AppError("Arquivo de certificado inválido (muito grande).")
    try:
        info = inspect_pfx(data, password)
    except CertificateError as exc:
        raise AppError(str(exc)) from exc
    if info.valid_to <= utcnow():
        raise AppError("Certificado vencido.")
    if db.scalar(select(DigitalCertificate.id).where(DigitalCertificate.thumbprint_sha256 == info.thumbprint_sha256)):
        raise AppError("Este certificado já foi enviado.")
    s = svc.company(db)
    if s.cnpj and info.document and info.document[:8] != s.cnpj[:8]:
        raise AppError("O certificado não pertence ao CNPJ cadastrado da clínica.")
    cert = DigitalCertificate(alias=alias[:120], subject=info.subject, issuer=info.issuer, serial_number=info.serial_number,
                              document=info.document, valid_from=info.valid_from, valid_to=info.valid_to,
                              thumbprint_sha256=info.thumbprint_sha256, pfx_enc=encrypt_bytes(data).decode("ascii"),
                              password_enc=encrypt_str(password), is_active=False, uploaded_by=user.id)
    db.add(cert)
    db.flush()
    if activate:
        for c in db.scalars(select(DigitalCertificate).where(DigitalCertificate.id != cert.id)).all():
            c.is_active = False
        cert.is_active = True
    audit(db, "certificado_enviado", user=user, entity="certificate", entity_id=cert.id,
          details={"titular": info.subject, "validade": info.valid_to.isoformat()})
    db.commit()
    return {"message": f"Certificado armazenado com criptografia. Válido até {info.valid_to:%d/%m/%Y}.", "id": str(cert.id)}


@router.post("/certificates/{cert_id}/activate")
def activate_certificate(cert_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.settings"))):
    cert = db.get(DigitalCertificate, cert_id)
    if cert is None:
        raise NotFound("Certificado")
    if cert.valid_to <= utcnow():
        raise AppError("Certificado vencido.")
    for c in db.scalars(select(DigitalCertificate)).all():
        c.is_active = c.id == cert_id
    audit(db, "certificado_ativado", user=user, entity="certificate", entity_id=cert_id)
    db.commit()
    return {"message": "Certificado ativado."}


@router.delete("/certificates/{cert_id}")
def delete_certificate(cert_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.settings"))):
    cert = db.get(DigitalCertificate, cert_id)
    if cert is None:
        raise NotFound("Certificado")
    db.delete(cert)
    audit(db, "certificado_removido", user=user, entity="certificate", entity_id=cert_id)
    db.commit()
    return {"message": "Certificado removido do sistema."}


@router.get("/readiness")
def readiness(db: Session = Depends(get_db), user: User = Depends(require("fiscal.read"))):
    s = svc.company(db)
    return {"environment": s.nfse_environment, "checks": [c.__dict__ for c in svc.readiness(db)]}


# ================================================================ NFS-e
class InvoiceIn(StrippedModel):
    customer_id: uuid.UUID | None = None
    taker_document: DocumentStr = None
    taker_name: str | None = Field(default=None, max_length=150)
    taker_email: EmailStr | None = None
    taker_phone: PhoneStr = None
    taker_zip_code: CepStr = None
    taker_street: str | None = Field(default=None, max_length=200)
    taker_number: str | None = Field(default=None, max_length=20)
    taker_complement: str | None = Field(default=None, max_length=100)
    taker_district: str | None = Field(default=None, max_length=100)
    taker_ibge_code: IbgeStr = None
    service_id: uuid.UUID | None = None
    tax_service_code_id: uuid.UUID
    description: str = Field(min_length=5, max_length=2000)
    competence_date: date
    gross_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    unconditional_discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    conditional_discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    deductions: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    incidence_ibge: IbgeStr = None
    iss_rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    iss_withheld: bool = False
    retentions: dict[str, Decimal] = Field(default_factory=dict)
    total_tax_sn_percent: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    additional_info: str | None = Field(default=None, max_length=2000)
    receivable_id: uuid.UUID | None = None
    package_id: uuid.UUID | None = None
    appointment_id: uuid.UUID | None = None


class CancelInvoiceIn(BaseModel):
    reason_code: str = Field(pattern=r"^(1|2|9)$")
    reason: str = Field(min_length=15, max_length=255)


class SubstituteIn(InvoiceIn):
    reason_code: str = Field(default="99", pattern=r"^\d{2}$")
    reason: str = Field(min_length=15, max_length=255)


class InvoiceListItem(ORM):
    id: uuid.UUID
    status: str
    environment: str
    nfse_number: str | None
    dps_number: int | None
    access_key: str | None
    taker_name: str | None
    taker_document: str | None
    competence_date: date
    gross_amount: Money
    net_amount: Money
    iss_amount: Money | None
    created_at: datetime
    authorized_at: datetime | None
    last_error: str | None


def _apply_invoice(db: Session, inv: FiscalInvoice, data: InvoiceIn) -> None:
    svc.date_ok(data.competence_date)
    code = db.get(TaxServiceCode, data.tax_service_code_id)
    if code is None or not code.is_active:
        raise AppError("Código de serviço fiscal inexistente ou inativo.")
    allowed_ret = {"irrf", "csll", "cp", "pis", "cofins"}
    bad = set(data.retentions) - allowed_ret
    if bad:
        raise AppError(f"Retenções não suportadas: {', '.join(bad)}")
    amounts = svc.compute_amounts(data.gross_amount, data.unconditional_discount, data.conditional_discount,
                                  data.deductions, data.iss_rate)
    if data.customer_id:
        c = db.get(Customer, data.customer_id)
        if c is None:
            raise NotFound("Cliente")
    inv.customer_id = data.customer_id
    inv.taker_document, inv.taker_name, inv.taker_email, inv.taker_phone = (
        data.taker_document, data.taker_name, data.taker_email, data.taker_phone)
    if data.taker_document and not data.taker_name:
        raise AppError("Informe o nome/razão social do tomador.")
    inv.taker_address = {"zip_code": data.taker_zip_code, "street": data.taker_street, "number": data.taker_number,
                         "complement": data.taker_complement, "district": data.taker_district,
                         "ibge_code": data.taker_ibge_code}
    inv.service_id, inv.tax_service_code_id = data.service_id, code.id
    inv.national_code, inv.municipal_code, inv.nbs_code = code.national_code, code.municipal_code, code.nbs_code
    inv.description, inv.competence_date = data.description, data.competence_date
    inv.gross_amount = money(data.gross_amount)
    inv.unconditional_discount, inv.conditional_discount = money(data.unconditional_discount), money(data.conditional_discount)
    inv.deductions, inv.net_amount = money(data.deductions), amounts["net"]
    inv.incidence_ibge, inv.iss_rate, inv.iss_amount = data.incidence_ibge, data.iss_rate, amounts["iss"]
    inv.iss_withheld = data.iss_withheld
    inv.retentions = {k: str(money(v)) for k, v in data.retentions.items() if v and v > 0}
    inv.tax_info = {"pTotTribSN": str(data.total_tax_sn_percent)} if data.total_tax_sn_percent is not None else {}
    inv.additional_info = data.additional_info


def _get_invoice(db: Session, invoice_id: uuid.UUID) -> FiscalInvoice:
    inv = db.get(FiscalInvoice, invoice_id)
    if inv is None:
        raise NotFound("Nota fiscal")
    return inv


def _invoice_detail(db: Session, inv: FiscalInvoice) -> dict:
    data = {c.name: getattr(inv, c.name) for c in inv.__table__.columns if c.name not in ("dps_xml", "nfse_xml")}
    data["has_dps_xml"], data["has_nfse_xml"] = bool(inv.dps_xml), bool(inv.nfse_xml)
    data["events"] = [{"type": e.event_type, "code": e.event_code, "success": e.success, "message": e.message,
                       "http_status": e.http_status, "created_at": e.created_at} for e in inv.events]
    for k in ("gross_amount", "unconditional_discount", "conditional_discount", "deductions", "net_amount", "iss_amount", "iss_rate"):
        data[k] = float(data[k]) if data[k] is not None else None
    return data


@router.get("/invoices", response_model=Page[InvoiceListItem])
def list_invoices(status: str | None = None, environment: str | None = None, start: date | None = None,
                  end: date | None = None, q: str | None = None, customer_id: uuid.UUID | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(50, le=200), db: Session = Depends(get_db),
                  user: User = Depends(require("fiscal.read"))):
    stmt = select(FiscalInvoice)
    if status:
        stmt = stmt.where(FiscalInvoice.status.in_(status.split(",")))
    if environment:
        stmt = stmt.where(FiscalInvoice.environment == environment)
    if start:
        stmt = stmt.where(FiscalInvoice.competence_date >= start)
    if end:
        stmt = stmt.where(FiscalInvoice.competence_date <= end)
    if customer_id:
        stmt = stmt.where(FiscalInvoice.customer_id == customer_id)
    if q:
        stmt = stmt.where(or_(FiscalInvoice.taker_name.ilike(f"%{q}%"), FiscalInvoice.nfse_number == q,
                              FiscalInvoice.taker_document == only_digits(q), FiscalInvoice.access_key == q))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(FiscalInvoice.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[InvoiceListItem.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/invoices/prefill")
def prefill(receivable_id: uuid.UUID | None = None, package_id: uuid.UUID | None = None,
            appointment_id: uuid.UUID | None = None, db: Session = Depends(get_db), user: User = Depends(require("fiscal.issue"))):
    """Sugere os dados da nota a partir da operação (o usuário revisa antes de salvar)."""
    key, links = svc.source_for(db, receivable_id=receivable_id, package_id=package_id, appointment_id=appointment_id)
    rec = db.get(AccountsReceivable, links["receivable_id"]) if links.get("receivable_id") else None
    pkg = db.get(Package, links["package_id"]) if links.get("package_id") else None
    customer = (rec.customer if rec else None) or (pkg.customer if pkg else None)
    service: Service | None = pkg.service if pkg else None
    if rec and rec.appointment_id and service is None:
        from app.models.schedule import Appointment

        appt = db.get(Appointment, rec.appointment_id)
        service = appt.service if appt else None
    if rec:
        gross, discount, competence = rec.amount, rec.discount, rec.competence_date
    elif pkg:
        recs = db.scalars(select(AccountsReceivable).where(AccountsReceivable.package_id == pkg.id,
                                                           AccountsReceivable.status != "cancelado")).all()
        gross = sum((r.amount for r in recs), Decimal("0")) or pkg.price
        discount = sum((r.discount for r in recs), Decimal("0"))
        competence = pkg.purchased_at
    else:
        raise AppError("Informe a operação de origem.")
    code = service.tax_service_code if service else None
    desc = (service.nfse_description if service and service.nfse_description else None) or (
        f"Serviço de {service.name}" if service else (rec.description if rec else ""))
    if pkg:
        desc = f"{desc} — pacote com {pkg.sessions_total} sessões"
    return {
        "receivable_id": links.get("receivable_id"), "package_id": links.get("package_id"),
        "appointment_id": links.get("appointment_id"), "customer_id": customer.id if customer else None,
        "taker_document": customer.cpf if customer else None, "taker_name": customer.full_name if customer else None,
        "taker_email": customer.email if customer else None, "taker_phone": customer.whatsapp or customer.phone if customer else None,
        "taker_zip_code": customer.zip_code if customer else None, "taker_street": customer.street if customer else None,
        "taker_number": customer.number if customer else None, "taker_complement": customer.complement if customer else None,
        "taker_district": customer.district if customer else None, "taker_ibge_code": customer.ibge_code if customer else None,
        "service_id": service.id if service else None, "tax_service_code_id": code.id if code else None,
        "tax_code_validated": code.validated if code else None,
        "iss_rate": float(code.iss_rate) if code and code.iss_rate is not None else None,
        "iss_withheld": code.iss_withheld_default if code else False,
        "description": desc, "competence_date": competence, "gross_amount": float(gross),
        "unconditional_discount": float(discount),
    }


@router.get("/invoices/pending-billing")
def pending_billing(start: date, end: date, db: Session = Depends(get_db), user: User = Depends(require("fiscal.read"))):
    """Receita ainda não faturada: contas a receber sem nota ativa (por título ou pacote)."""
    rows = db.scalars(select(AccountsReceivable).where(AccountsReceivable.competence_date.between(start, end),
                                                       AccountsReceivable.status != "cancelado")
                      .order_by(AccountsReceivable.competence_date)).all()
    active = set(db.scalars(select(FiscalInvoice.source_key).where(FiscalInvoice.status.in_(ACTIVE_INVOICE_STATUSES),
                                                                   FiscalInvoice.source_key.is_not(None))).all())
    out = []
    for r in rows:
        if f"receivable:{r.id}" in active or (r.package_id and f"package:{r.package_id}" in active):
            continue
        out.append({"receivable_id": str(r.id), "package_id": str(r.package_id) if r.package_id else None,
                    "customer": r.customer.full_name if r.customer else None, "description": r.description,
                    "competence_date": r.competence_date, "amount": float(r.net_amount), "status": r.status,
                    "has_cpf": bool(r.customer and r.customer.cpf)})
    return {"items": out, "total": sum(o["amount"] for o in out)}


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.read"))):
    return _invoice_detail(db, _get_invoice(db, invoice_id))


@router.post("/invoices", status_code=201)
def create_invoice(data: InvoiceIn, db: Session = Depends(get_db), user: User = Depends(require("fiscal.issue"))):
    key, links = svc.source_for(db, receivable_id=data.receivable_id, package_id=data.package_id,
                                appointment_id=data.appointment_id)
    s = svc.company(db)
    inv = FiscalInvoice(status="rascunho", environment=s.nfse_environment, provider=s.nfse_provider, source_key=key,
                        receivable_id=links.get("receivable_id"), package_id=links.get("package_id"),
                        appointment_id=links.get("appointment_id"), created_by=user.id, attempts=0)
    _apply_invoice(db, inv, data)
    db.add(inv)
    db.flush()
    svc._event(db, inv, "criacao", success=True, message="Rascunho criado", user_id=user.id)
    audit(db, "nfse_rascunho_criado", user=user, entity="fiscal_invoice", entity_id=inv.id)
    db.commit()
    return {"message": "Rascunho salvo. Revise a prévia antes de transmitir.", "invoice": _invoice_detail(db, inv)}


@router.put("/invoices/{invoice_id}")
def update_invoice(invoice_id: uuid.UUID, data: InvoiceIn, db: Session = Depends(get_db), user: User = Depends(require("fiscal.issue"))):
    inv = _get_invoice(db, invoice_id)
    if inv.status not in ("rascunho", "rejeitada"):
        raise AppError("Somente rascunhos ou notas rejeitadas podem ser editados.")
    _apply_invoice(db, inv, data)
    if inv.status == "rejeitada":
        inv.status = "rascunho"
    audit(db, "nfse_rascunho_alterado", user=user, entity="fiscal_invoice", entity_id=inv.id)
    db.commit()
    return {"message": "Rascunho atualizado.", "invoice": _invoice_detail(db, inv)}


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.issue"))):
    inv = _get_invoice(db, invoice_id)
    if inv.status not in ("rascunho", "rejeitada") or inv.access_key:
        raise AppError("Somente rascunhos e notas rejeitadas podem ser descartados.")
    if inv.dps_number:
        inv.status = "rejeitada"
        inv.source_key = None
        inv.last_error = (inv.last_error or "") + " | Descartada pelo usuário."
        msg = "Nota descartada (mantida no histórico pois a numeração da DPS já foi utilizada)."
    else:
        db.delete(inv)
        msg = "Rascunho excluído."
    audit(db, "nfse_descartada", user=user, entity="fiscal_invoice", entity_id=invoice_id)
    db.commit()
    return {"message": msg}


@router.get("/invoices/{invoice_id}/preview")
def preview_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.issue"))):
    inv = _get_invoice(db, invoice_id)
    s = svc.company(db)
    checks = [c.__dict__ for c in svc.readiness(db)]
    try:
        p = svc.preview(db, inv)
    except Exception as exc:  # noqa: BLE001
        p = {"xml": None, "error": str(exc)}
    return {"invoice": _invoice_detail(db, inv), "environment": s.nfse_environment, "readiness": checks, **p}


@router.post("/invoices/{invoice_id}/transmit")
def transmit_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.issue"))):
    inv = _get_invoice(db, invoice_id)
    svc.transmit(db, inv, user.id)
    audit(db, "nfse_transmitida", user=user, entity="fiscal_invoice", entity_id=inv.id, details={"status": inv.status})
    db.commit()
    messages = {"autorizada": f"NFS-e autorizada pelo serviço oficial (nº {inv.nfse_number}).",
                "rejeitada": "NFS-e rejeitada. Corrija os dados conforme o retorno e transmita novamente.",
                "aguardando_transmissao": "Sem confirmação do serviço fiscal. A nota NÃO foi considerada emitida; reprocesse em instantes."}
    return {"message": messages.get(inv.status, inv.status), "invoice": _invoice_detail(db, inv)}


@router.post("/invoices/{invoice_id}/reprocess")
def reprocess_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.issue"))):
    inv = _get_invoice(db, invoice_id)
    svc.reprocess(db, inv, user.id)
    audit(db, "nfse_reprocessada", user=user, entity="fiscal_invoice", entity_id=inv.id, details={"status": inv.status})
    db.commit()
    return {"message": f"Situação atual: {inv.status}.", "invoice": _invoice_detail(db, inv)}


@router.post("/invoices/{invoice_id}/cancel")
def cancel_invoice(invoice_id: uuid.UUID, data: CancelInvoiceIn, db: Session = Depends(get_db),
                   user: User = Depends(require("fiscal.cancel"))):
    inv = _get_invoice(db, invoice_id)
    try:
        svc.cancel(db, inv, reason_code=data.reason_code, reason=data.reason, user_id=user.id)
    except AppError:
        db.commit()  # registra o evento de tentativa
        raise
    audit(db, "nfse_cancelada", user=user, entity="fiscal_invoice", entity_id=inv.id, details=data.model_dump())
    db.commit()
    return {"message": "Cancelamento homologado pelo serviço fiscal.", "invoice": _invoice_detail(db, inv)}


@router.post("/invoices/{invoice_id}/substitute", status_code=201)
def substitute_invoice(invoice_id: uuid.UUID, data: SubstituteIn, db: Session = Depends(get_db),
                       user: User = Depends(require("fiscal.cancel", "fiscal.issue"))):
    old = _get_invoice(db, invoice_id)
    if old.status != "autorizada" or not old.access_key:
        raise AppError("Somente NFS-e autorizadas podem ser substituídas.")
    if db.scalar(select(FiscalInvoice.id).where(FiscalInvoice.replaces_id == old.id,
                                                FiscalInvoice.status.in_(ACTIVE_INVOICE_STATUSES))):
        raise AppError("Já existe uma nota substituta em andamento.")
    new = FiscalInvoice(status="rascunho", environment=old.environment, provider=old.provider, source_key=None,
                        receivable_id=old.receivable_id, package_id=old.package_id, appointment_id=old.appointment_id,
                        replaces_id=old.id, substitution_reason_code=data.reason_code, substitution_reason=data.reason,
                        created_by=user.id, attempts=0)
    _apply_invoice(db, new, data)
    db.add(new)
    db.flush()
    svc._event(db, new, "criacao", success=True, message=f"Rascunho substituto da NFS-e {old.nfse_number}", user_id=user.id)
    audit(db, "nfse_substituicao_iniciada", user=user, entity="fiscal_invoice", entity_id=old.id, details={"nova": str(new.id)})
    db.commit()
    return {"message": "Rascunho de substituição criado. Ao ser autorizado, a nota original será cancelada por substituição pelo serviço oficial.",
            "invoice": _invoice_detail(db, new)}


@router.post("/invoices/{invoice_id}/refresh")
def refresh_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.read"))):
    inv = _get_invoice(db, invoice_id)
    result = svc.refresh(db, inv, user.id)
    db.commit()
    return {"message": "Consulta realizada.", "result": result, "invoice": _invoice_detail(db, inv)}


@router.post("/invoices/{invoice_id}/danfse")
def fetch_danfse(invoice_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.read"))):
    inv = _get_invoice(db, invoice_id)
    ok = svc.fetch_danfse(db, inv, user.id)
    db.commit()
    if not ok:
        raise AppError("DANFSe não disponibilizado pelo serviço oficial no momento.")
    return {"message": "DANFSe obtido e armazenado."}


@router.get("/invoices/{invoice_id}/danfse")
def download_danfse(invoice_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.read"))):
    inv = _get_invoice(db, invoice_id)
    if not inv.danfse_file_id:
        raise NotFound("DANFSe")
    f = db.get(StoredFile, inv.danfse_file_id)
    return Response(read_file(f), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{f.original_name}"'})


@router.get("/invoices/{invoice_id}/xml")
def download_xml(invoice_id: uuid.UUID, kind: str = Query("nfse", pattern=r"^(nfse|dps)$"), db: Session = Depends(get_db),
                 user: User = Depends(require("fiscal.read"))):
    inv = _get_invoice(db, invoice_id)
    content = inv.nfse_xml if kind == "nfse" else inv.dps_xml
    if not content:
        raise NotFound("XML")
    name = f"{kind}_{inv.nfse_number or inv.dps_id or inv.id}.xml"
    return Response(content, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ================================================================ Documentos recebidos
class DocumentIn(StrippedModel):
    direction: str = Field(default="recebido", pattern=r"^(recebido|emitido_externo)$")
    doc_type: str = Field(pattern=r"^(nfse|nfe|nfce|cte|recibo|fatura|guia|outro)$")
    number: str | None = Field(default=None, max_length=30)
    series: str | None = Field(default=None, max_length=10)
    access_key: str | None = Field(default=None, max_length=60)
    issuer_name: str = Field(min_length=2, max_length=150)
    issuer_document: DocumentStr = None
    issue_date: date
    competence_date: date | None = None
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    retentions: dict[str, Decimal] = Field(default_factory=dict)
    service_taken: bool = True
    description: str | None = None
    notes: str | None = None


def _doc_out(d: FiscalDocument, db: Session) -> dict:
    files = db.scalars(select(StoredFile).where(StoredFile.fiscal_document_id == d.id)).all()
    return {**{c.name: getattr(d, c.name) for c in d.__table__.columns if c.name != "xml"},
            "amount": float(d.amount), "retention_total": float(d.retention_total), "has_xml": bool(d.xml),
            "files": [{"id": str(f.id), "name": f.original_name} for f in files]}


@router.get("/documents")
def list_documents(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
                   user: User = Depends(require("fiscal.read"))):
    stmt = select(FiscalDocument)
    if start:
        stmt = stmt.where(FiscalDocument.issue_date >= start)
    if end:
        stmt = stmt.where(FiscalDocument.issue_date <= end)
    return [_doc_out(d, db) for d in db.scalars(stmt.order_by(FiscalDocument.issue_date.desc()).limit(1000)).all()]


def _doc_values(data: DocumentIn) -> dict:
    allowed = {"iss", "irrf", "pis", "cofins", "csll", "inss"}
    if set(data.retentions) - allowed:
        raise AppError("Tipo de retenção inválido.")
    ret = {k: str(money(v)) for k, v in data.retentions.items() if v and v > 0}
    values = data.model_dump()
    values["retentions"] = ret
    values["retention_total"] = money(sum((Decimal(v) for v in ret.values()), Decimal("0")))
    return values


@router.post("/documents", status_code=201)
def create_document(data: DocumentIn, db: Session = Depends(get_db), user: User = Depends(require("fiscal.documents"))):
    d = FiscalDocument(**_doc_values(data), created_by=user.id)
    db.add(d)
    db.flush()
    audit(db, "documento_fiscal_registrado", user=user, entity="fiscal_document", entity_id=d.id)
    db.commit()
    return {"message": "Documento registrado.", "document": _doc_out(d, db)}


@router.put("/documents/{doc_id}")
def update_document(doc_id: uuid.UUID, data: DocumentIn, db: Session = Depends(get_db), user: User = Depends(require("fiscal.documents"))):
    d = db.get(FiscalDocument, doc_id)
    if d is None:
        raise NotFound("Documento")
    for k, v in _doc_values(data).items():
        setattr(d, k, v)
    db.commit()
    return {"message": "Documento atualizado.", "document": _doc_out(d, db)}


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.documents"))):
    d = db.get(FiscalDocument, doc_id)
    if d is None:
        raise NotFound("Documento")
    from app.core.storage import delete_file

    for f in db.scalars(select(StoredFile).where(StoredFile.fiscal_document_id == d.id)).all():
        delete_file(db, f)
    db.delete(d)
    audit(db, "documento_fiscal_excluido", user=user, entity="fiscal_document", entity_id=doc_id)
    db.commit()
    return {"message": "Documento excluído."}


@router.post("/documents/{doc_id}/files", status_code=201)
async def attach_document(doc_id: uuid.UUID, file: UploadFile = File(...), db: Session = Depends(get_db),
                          user: User = Depends(require("fiscal.documents"))):
    d = db.get(FiscalDocument, doc_id)
    if d is None:
        raise NotFound("Documento")
    data = await file.read()
    if (file.filename or "").lower().endswith(".xml") and not d.xml:
        try:
            d.xml = data.decode("utf-8")
        except UnicodeDecodeError:
            pass
    rec = save_file(db, data, filename=file.filename or "documento", content_type=file.content_type, category="fiscal",
                    user_id=user.id, fiscal_document_id=d.id)
    db.commit()
    return {"message": "Arquivo anexado.", "id": str(rec.id)}


@router.get("/files/{file_id}")
def download_fiscal_file(file_id: uuid.UUID, db: Session = Depends(get_db),
                         user: User = Depends(require_any("fiscal.read", "finance.read"))):
    f = db.get(StoredFile, file_id)
    if f is None or f.sensitive or f.category not in ("fiscal", "expense", "obligation", "tax_guide", "accounting"):
        raise NotFound("Arquivo")
    if f.category == "expense" and not has_perm(user, "finance.read") and not has_perm(user, "fiscal.read"):
        raise NotFound("Arquivo")
    return Response(read_file(f), media_type=f.content_type,
                    headers={"Content-Disposition": f'attachment; filename="{f.original_name}"'})


# ================================================================ Regras tributárias
class TaxRateIn(StrippedModel):
    tax: str
    regime: str
    description: str | None = Field(default=None, max_length=300)
    rate: Decimal = Field(ge=0, le=100, decimal_places=4)
    base: str = Field(default="receita_bruta", pattern=r"^(receita_bruta|presuncao|fixo)$")
    presumption_percent: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=4)
    tax_service_code_id: uuid.UUID | None = None
    municipality_ibge: IbgeStr = None
    valid_from: date
    valid_to: date | None = None
    due_day: int | None = Field(default=None, ge=1, le=31)
    validated: bool = False
    validated_by: str | None = Field(default=None, max_length=150)
    notes: str | None = None
    is_active: bool = True


class TaxRateOut(ORM):
    id: uuid.UUID
    tax: str
    regime: str
    description: str | None
    rate: Money
    base: str
    presumption_percent: Money | None
    tax_service_code_id: uuid.UUID | None
    municipality_ibge: str | None
    valid_from: date
    valid_to: date | None
    due_day: int | None
    validated: bool
    validated_by: str | None
    notes: str | None
    is_active: bool


def _validate_rate(db: Session, values: dict, obj) -> None:
    if values["tax"] not in tax_svc.TAXES:
        raise AppError("Tributo inválido.")
    if values["regime"] not in TAX_REGIMES:
        raise AppError("Regime inválido.")
    if values.get("valid_to") and values["valid_to"] < values["valid_from"]:
        raise AppError("Fim de vigência anterior ao início.")
    if values["base"] == "presuncao" and not values.get("presumption_percent"):
        raise AppError("Informe o percentual de presunção.")
    if values.get("validated") and not values.get("validated_by"):
        raise AppError("Informe quem validou a regra.")


make_crud(router, path="/tax-rates", model=TaxRate, schema_in=TaxRateIn, schema_out=TaxRateOut,
          read_perms=("fiscal.read",), write_perms=("fiscal.taxes",), entity="regra_tributaria",
          order_by=TaxRate.tax, validate=_validate_rate)


@router.get("/taxes/catalog")
def taxes_catalog(user: User = Depends(require("fiscal.read"))):
    return {"taxes": tax_svc.TAXES, "regimes": list(TAX_REGIMES)}


# ================================================================ Apurações
class AssessmentUpdate(BaseModel):
    final_amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    status: str = Field(pattern=r"^(estimado|validado|pago|cancelado)$")
    due_date: date | None = None
    paid_at: date | None = None
    paid_amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    validated_by: str | None = Field(default=None, max_length=150)
    notes: str | None = None


def _assessment_out(t: TaxAssessment, db: Session) -> dict:
    files = db.scalars(select(StoredFile).where(StoredFile.tax_assessment_id == t.id)).all()
    return {"id": str(t.id), "period": t.period, "tax": t.tax, "regime": t.regime, "base_amount": float(t.base_amount),
            "rate": float(t.rate) if t.rate is not None else None, "estimated_amount": float(t.estimated_amount),
            "final_amount": float(t.final_amount) if t.final_amount is not None else None, "status": t.status,
            "due_date": t.due_date, "paid_at": t.paid_at,
            "paid_amount": float(t.paid_amount) if t.paid_amount is not None else None,
            "calculation_notes": t.calculation_notes, "validated_by": t.validated_by, "notes": t.notes,
            "payable_id": str(t.payable_id) if t.payable_id else None,
            "files": [{"id": str(f.id), "name": f.original_name} for f in files]}


@router.get("/assessments")
def list_assessments(year: int = Query(..., ge=2000, le=2100), db: Session = Depends(get_db), user: User = Depends(require("fiscal.read"))):
    rows = db.scalars(select(TaxAssessment).where(TaxAssessment.period.like(f"{year}-%"))
                      .order_by(TaxAssessment.period, TaxAssessment.tax)).all()
    return [_assessment_out(t, db) for t in rows]


@router.post("/assessments/estimate")
def estimate(period: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
             source: str = Query("faturada", pattern=r"^(faturada|contratada)$"),
             db: Session = Depends(get_db), user: User = Depends(require("fiscal.taxes"))):
    rows = tax_svc.estimate_period(db, period, source)
    audit(db, "tributos_estimados", user=user, details={"periodo": period, "base": source})
    db.commit()
    return {"message": f"{len(rows)} tributo(s) estimado(s) para {period}. Valores sujeitos à validação do contador.",
            "items": [_assessment_out(t, db) for t in rows]}


@router.put("/assessments/{assessment_id}")
def update_assessment(assessment_id: uuid.UUID, data: AssessmentUpdate, db: Session = Depends(get_db),
                      user: User = Depends(require("fiscal.taxes"))):
    t = db.get(TaxAssessment, assessment_id)
    if t is None:
        raise NotFound("Apuração")
    if data.status in ("validado", "pago") and data.final_amount is None:
        raise AppError("Informe o valor final apurado.")
    if data.status == "pago" and (data.paid_at is None or data.paid_amount is None):
        raise AppError("Informe a data e o valor pago.")
    for k, v in data.model_dump().items():
        setattr(t, k, v)
    audit(db, "apuracao_atualizada", user=user, entity="tax_assessment", entity_id=t.id, details=data.model_dump(mode="json"))
    db.commit()
    return {"message": "Apuração atualizada.", "item": _assessment_out(t, db)}


@router.post("/assessments/{assessment_id}/payable")
def assessment_payable(assessment_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.taxes", "finance.write"))):
    t = db.get(TaxAssessment, assessment_id)
    if t is None:
        raise NotFound("Apuração")
    if t.payable_id:
        raise AppError("Já existe conta a pagar para esta guia.")
    if t.final_amount is None or t.due_date is None:
        raise AppError("Valide o valor final e o vencimento antes de lançar a guia.")
    from app.services.finance import category_id
    from app.core.utils import month_bounds

    p = AccountsPayable(description=f"Guia {t.tax} — competência {t.period}", supplier_name="Receita/Prefeitura",
                        category_id=category_id(db, "Tributos", "despesa"), competence_date=month_bounds(t.period)[1],
                        due_date=t.due_date, amount=t.final_amount, created_by=user.id)
    db.add(p)
    db.flush()
    t.payable_id = p.id
    audit(db, "guia_lancada_contas_pagar", user=user, entity="tax_assessment", entity_id=t.id)
    db.commit()
    return {"message": "Guia lançada em contas a pagar.", "payable_id": str(p.id)}


@router.post("/assessments/{assessment_id}/files", status_code=201)
async def attach_guide(assessment_id: uuid.UUID, file: UploadFile = File(...), db: Session = Depends(get_db),
                       user: User = Depends(require("fiscal.taxes"))):
    if db.get(TaxAssessment, assessment_id) is None:
        raise NotFound("Apuração")
    rec = save_file(db, await file.read(), filename=file.filename or "guia.pdf", content_type=file.content_type,
                    category="tax_guide", user_id=user.id, tax_assessment_id=assessment_id)
    db.commit()
    return {"message": "Guia anexada.", "id": str(rec.id)}


# ================================================================ Obrigações
class TemplateIn(StrippedModel):
    name: str = Field(min_length=3, max_length=150)
    code: str = Field(min_length=2, max_length=30)
    frequency: str = Field(pattern=r"^(mensal|anual)$")
    due_day: int = Field(ge=1, le=31)
    due_month: int | None = Field(default=None, ge=1, le=12)
    reference_offset_months: int = Field(default=1, ge=0, le=12)
    applicable_regimes: list[str] = Field(default_factory=list)
    requires_employees: bool = False
    responsible: str | None = None
    description: str | None = None
    is_active: bool = False


class TemplateOut(ORM):
    id: uuid.UUID
    name: str
    code: str
    frequency: str
    due_day: int
    due_month: int | None
    reference_offset_months: int
    applicable_regimes: list
    requires_employees: bool
    responsible: str | None
    description: str | None
    is_active: bool


def _validate_template(db: Session, values: dict, obj) -> None:
    if values["frequency"] == "anual" and not values.get("due_month"):
        raise AppError("Informe o mês de vencimento da obrigação anual.")
    bad = set(values.get("applicable_regimes") or []) - set(TAX_REGIMES)
    if bad:
        raise AppError("Regimes inválidos: " + ", ".join(bad))


make_crud(router, path="/obligation-templates", model=TaxObligationTemplate, schema_in=TemplateIn, schema_out=TemplateOut,
          read_perms=("fiscal.read",), write_perms=("fiscal.obligations",), entity="modelo_obrigacao",
          order_by=TaxObligationTemplate.name, validate=_validate_template)


class ObligationUpdate(BaseModel):
    status: str = Field(pattern=r"^(pendente|em_preparacao|enviado|concluido|atrasado|nao_aplicavel)$")
    due_date: date
    responsible: str | None = Field(default=None, max_length=120)
    delivered_at: date | None = None
    receipt_number: str | None = Field(default=None, max_length=80)
    notes: str | None = None


class ObligationIn(BaseModel):
    name: str = Field(min_length=3, max_length=150)
    code: str = Field(min_length=2, max_length=30)
    reference_period: str = Field(pattern=r"^\d{4}(-(0[1-9]|1[0-2]))?$")
    due_date: date
    responsible: str | None = None
    notes: str | None = None


def _obligation_out(o: TaxObligation, db: Session) -> dict:
    files = db.scalars(select(StoredFile).where(StoredFile.tax_obligation_id == o.id)).all()
    return {"id": str(o.id), "name": o.name, "code": o.code, "reference_period": o.reference_period, "due_date": o.due_date,
            "responsible": o.responsible, "status": o.status, "delivered_at": o.delivered_at,
            "receipt_number": o.receipt_number, "notes": o.notes,
            "days_to_due": (o.due_date - local_today()).days,
            "files": [{"id": str(f.id), "name": f.original_name} for f in files]}


@router.get("/obligations")
def list_obligations(start: date | None = None, end: date | None = None, status: str | None = None,
                     db: Session = Depends(get_db), user: User = Depends(require("fiscal.read"))):
    stmt = select(TaxObligation)
    if start:
        stmt = stmt.where(TaxObligation.due_date >= start)
    if end:
        stmt = stmt.where(TaxObligation.due_date <= end)
    if status:
        stmt = stmt.where(TaxObligation.status.in_(status.split(",")))
    return [_obligation_out(o, db) for o in db.scalars(stmt.order_by(TaxObligation.due_date)).all()]


@router.post("/obligations", status_code=201)
def create_obligation(data: ObligationIn, db: Session = Depends(get_db), user: User = Depends(require("fiscal.obligations"))):
    o = TaxObligation(**data.model_dump(), status="pendente", updated_by=user.id)
    db.add(o)
    db.commit()
    return {"message": "Obrigação incluída no calendário.", "item": _obligation_out(o, db)}


@router.post("/obligations/generate")
def generate_obligations(period: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), db: Session = Depends(get_db),
                         user: User = Depends(require("fiscal.obligations"))):
    n = tax_svc.generate_obligations(db, period)
    audit(db, "obrigacoes_geradas", user=user, details={"periodo": period, "quantidade": n})
    db.commit()
    return {"message": f"{n} obrigação(ões) gerada(s) para {period} a partir dos modelos ativos."}


@router.put("/obligations/{obligation_id}")
def update_obligation(obligation_id: uuid.UUID, data: ObligationUpdate, db: Session = Depends(get_db),
                      user: User = Depends(require("fiscal.obligations"))):
    o = db.get(TaxObligation, obligation_id)
    if o is None:
        raise NotFound("Obrigação")
    if data.status in ("enviado", "concluido") and not data.delivered_at:
        raise AppError("Informe a data de entrega/envio.")
    for k, v in data.model_dump().items():
        setattr(o, k, v)
    o.updated_by = user.id
    audit(db, "obrigacao_atualizada", user=user, entity="tax_obligation", entity_id=o.id, details=data.model_dump(mode="json"))
    db.commit()
    return {"message": "Obrigação atualizada. Status informado manualmente — o sistema não transmite declarações.",
            "item": _obligation_out(o, db)}


@router.post("/obligations/{obligation_id}/files", status_code=201)
async def attach_receipt(obligation_id: uuid.UUID, file: UploadFile = File(...), db: Session = Depends(get_db),
                         user: User = Depends(require("fiscal.obligations"))):
    if db.get(TaxObligation, obligation_id) is None:
        raise NotFound("Obrigação")
    rec = save_file(db, await file.read(), filename=file.filename or "comprovante.pdf", content_type=file.content_type,
                    category="obligation", user_id=user.id, tax_obligation_id=obligation_id)
    db.commit()
    return {"message": "Comprovante anexado.", "id": str(rec.id)}


# ================================================================ Exportação para o contador
class ExportIn(BaseModel):
    start: date
    end: date
    formats: list[str] = Field(default_factory=lambda: ["csv", "xlsx", "pdf", "xml", "anexos"])
    notes: str | None = Field(default=None, max_length=1000)


class ExportMarkIn(BaseModel):
    status: str = Field(pattern=r"^(disponibilizado|enviado)$")
    sent_to: str | None = Field(default=None, max_length=200)
    sent_method: str | None = Field(default=None, max_length=60)


def _export_out(e: AccountingExport) -> dict:
    return {"id": str(e.id), "period_start": e.period_start, "period_end": e.period_end, "formats": e.formats,
            "contents": e.contents, "status": e.status, "sent_at": e.sent_at, "sent_to": e.sent_to,
            "sent_method": e.sent_method, "downloaded_at": e.downloaded_at, "notes": e.notes, "created_at": e.created_at}


@router.get("/exports")
def list_exports(db: Session = Depends(get_db), user: User = Depends(require("fiscal.read"))):
    return [_export_out(e) for e in db.scalars(select(AccountingExport).order_by(AccountingExport.created_at.desc()).limit(200)).all()]


@router.post("/exports", status_code=201)
def create_export(data: ExportIn, db: Session = Depends(get_db), user: User = Depends(require("fiscal.export"))):
    exp = accounting.build_export(db, data.start, data.end, data.formats, user.id, data.notes)
    audit(db, "exportacao_contabil_gerada", user=user, entity="accounting_export", entity_id=exp.id,
          details={"inicio": str(data.start), "fim": str(data.end), "formatos": data.formats})
    db.commit()
    return {"message": "Pacote para o contador gerado.", "export": _export_out(exp)}


@router.get("/exports/{export_id}/download")
def download_export(export_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("fiscal.export"))):
    e = db.get(AccountingExport, export_id)
    if e is None or not e.file_id:
        raise NotFound("Exportação")
    f = db.get(StoredFile, e.file_id)
    if user.role.code == "contador" or e.downloaded_at is None:
        e.downloaded_at, e.downloaded_by = utcnow(), user.id
        if user.role.code == "contador":
            e.status = "baixado"
    audit(db, "exportacao_contabil_baixada", user=user, entity="accounting_export", entity_id=e.id)
    db.commit()
    return Response(read_file(f), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{f.original_name}"'})


@router.put("/exports/{export_id}")
def mark_export(export_id: uuid.UUID, data: ExportMarkIn, db: Session = Depends(get_db), user: User = Depends(require("fiscal.export"))):
    e = db.get(AccountingExport, export_id)
    if e is None:
        raise NotFound("Exportação")
    e.status, e.sent_to, e.sent_method = data.status, data.sent_to, data.sent_method
    e.sent_at = utcnow()
    db.commit()
    return {"message": "Histórico de envio atualizado.", "export": _export_out(e)}
