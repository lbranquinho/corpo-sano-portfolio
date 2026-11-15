"""Atendimentos e anamnese — dados sensíveis (LGPD art. 11).

- Conteúdo criptografado com chave exclusiva de saúde.
- Acesso somente com 'clinical.read'; toda leitura é registrada na auditoria.
- O sistema NÃO gera diagnósticos ou prescrições: registra apenas o que foi relatado/realizado.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.crypto import decrypt_health, encrypt_health, sha256_hex
from app.core.database import get_db
from app.core.deps import client_ip, has_perm, require
from app.core.errors import AppError, Forbidden, NotFound
from app.core.settings_store import get_setting
from app.core.storage import delete_file, read_file, save_file
from app.core.utils import day_bounds, utcnow
from app.models.auth import User
from app.models.clinical import CustomerHealthRecord, Treatment, TreatmentRecord
from app.models.system import StoredFile
from app.schemas.common import CpfStr
from app.services.customers import get_customer_for, record_consent

router = APIRouter(prefix="/clinical", tags=["Atendimentos e anamnese"])

HEALTH_FIELDS = ("objective", "health_history", "allergies", "sensitivities", "restrictions", "body_regions",
                 "preferences", "notes")
RECORD_FIELDS = ("technique", "products", "notes", "evolution", "recommendations")


class HealthRecordIn(BaseModel):
    objective: str | None = Field(default=None, max_length=4000)
    health_history: str | None = Field(default=None, max_length=8000)
    allergies: str | None = Field(default=None, max_length=4000)
    sensitivities: str | None = Field(default=None, max_length=4000)
    restrictions: str | None = Field(default=None, max_length=4000)
    body_regions: list[str] = Field(default_factory=list)
    preferences: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=8000)
    consent_given: bool
    consent_name: str = Field(min_length=3, max_length=150)
    consent_document: CpfStr = None


class TreatmentRecordIn(BaseModel):
    technique: str = Field(min_length=2, max_length=500)
    duration_minutes: int | None = Field(default=None, ge=1, le=600)
    products: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=8000)
    evolution: str | None = Field(default=None, max_length=8000)
    recommendations: str | None = Field(default=None, max_length=4000)
    next_return_date: date | None = None


def _own_treatment(user: User, t: Treatment) -> None:
    if not has_perm(user, "agenda.read_all") and t.professional_id != user.professional_id:
        raise Forbidden("Atendimento de outro profissional.")


@router.get("/customers/{customer_id}/health-records")
def list_health_records(customer_id: uuid.UUID, db: Session = Depends(get_db),
                        user: User = Depends(require("clinical.read"))):
    get_customer_for(db, user, customer_id)
    rows = db.scalars(select(CustomerHealthRecord).where(CustomerHealthRecord.customer_id == customer_id)
                      .order_by(CustomerHealthRecord.version.desc())).all()
    audit(db, "anamnese_visualizada", user=user, entity="customer", entity_id=customer_id, sensitive=True)
    db.commit()
    return [
        {"id": str(r.id), "version": r.version, "created_at": r.created_at, "consent_given": r.consent_given,
         "consent_accepted_at": r.consent_accepted_at, "consent_accepted_name": r.consent_accepted_name,
         "consent_hash": r.consent_hash, "consent_text": r.consent_text, **decrypt_health(r.data_enc)}
        for r in rows
    ]


@router.post("/customers/{customer_id}/health-records", status_code=201)
def create_health_record(customer_id: uuid.UUID, data: HealthRecordIn, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(require("clinical.write"))):
    c = get_customer_for(db, user, customer_id)
    if not data.consent_given:
        raise AppError("O consentimento informado do cliente é obrigatório para registrar a anamnese.")
    content = {k: getattr(data, k) for k in HEALTH_FIELDS}
    version = (db.scalar(select(func.max(CustomerHealthRecord.version))
                         .where(CustomerHealthRecord.customer_id == customer_id)) or 0) + 1
    accepted_at = utcnow()
    consent_text = get_setting(db, "lgpd.consent_text")
    digest = sha256_hex(json.dumps({"conteudo": content, "termo": consent_text, "nome": data.consent_name,
                                    "documento": data.consent_document, "data": accepted_at.isoformat()},
                                   ensure_ascii=False, sort_keys=True).encode())
    rec = CustomerHealthRecord(
        customer_id=c.id, version=version, data_enc=encrypt_health(content), consent_given=True,
        consent_text=consent_text, consent_accepted_at=accepted_at, consent_accepted_name=data.consent_name,
        consent_accepted_document=data.consent_document, consent_ip=client_ip(request), consent_hash=digest,
        created_by=user.id,
    )
    db.add(rec)
    record_consent(db, c.id, "dados_saude", True, source="anamnese", notes=f"Aceite eletrônico v{version}",
                   user_id=user.id, ip=client_ip(request))
    audit(db, "anamnese_registrada", user=user, entity="customer", entity_id=c.id, details={"versao": version},
          sensitive=True)
    db.commit()
    return {"message": f"Anamnese registrada (versão {version}).", "id": str(rec.id), "consent_hash": digest}


@router.get("/treatments")
def list_treatments(
    customer_id: uuid.UUID | None = None, start: date | None = None, end: date | None = None,
    professional_id: uuid.UUID | None = None, db: Session = Depends(get_db), user: User = Depends(require("clinical.read")),
):
    stmt = select(Treatment)
    if customer_id:
        get_customer_for(db, user, customer_id)
        stmt = stmt.where(Treatment.customer_id == customer_id)
    if not has_perm(user, "agenda.read_all"):
        stmt = stmt.where(Treatment.professional_id == user.professional_id)
    elif professional_id:
        stmt = stmt.where(Treatment.professional_id == professional_id)
    if start:
        stmt = stmt.where(Treatment.started_at >= day_bounds(start)[0])
    if end:
        stmt = stmt.where(Treatment.started_at < day_bounds(end)[1])
    rows = db.scalars(stmt.order_by(Treatment.started_at.desc()).limit(500)).all()
    counts = dict(db.execute(select(TreatmentRecord.treatment_id, func.count()).group_by(TreatmentRecord.treatment_id)
                             .where(TreatmentRecord.treatment_id.in_([t.id for t in rows]))).all()) if rows else {}
    return [
        {"id": str(t.id), "appointment_id": str(t.appointment_id) if t.appointment_id else None,
         "customer_id": str(t.customer_id), "customer_name": t.customer.full_name, "professional": t.professional.name,
         "service": t.service.name, "started_at": t.started_at, "ended_at": t.ended_at, "status": t.status,
         "records": counts.get(t.id, 0)}
        for t in rows
    ]


@router.get("/treatments/{treatment_id}")
def get_treatment(treatment_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("clinical.read"))):
    t = db.get(Treatment, treatment_id)
    if t is None:
        raise NotFound("Atendimento")
    _own_treatment(user, t)
    records = db.scalars(select(TreatmentRecord).where(TreatmentRecord.treatment_id == t.id)
                         .order_by(TreatmentRecord.created_at)).all()
    files = db.scalars(select(StoredFile).where(StoredFile.treatment_id == t.id)).all()
    audit(db, "ficha_atendimento_visualizada", user=user, entity="treatment", entity_id=t.id, sensitive=True)
    db.commit()
    return {
        "treatment": {"id": str(t.id), "customer_id": str(t.customer_id), "customer_name": t.customer.full_name,
                      "professional": t.professional.name, "service": t.service.name, "started_at": t.started_at,
                      "ended_at": t.ended_at, "status": t.status,
                      "appointment_id": str(t.appointment_id) if t.appointment_id else None},
        "records": [{"id": str(r.id), "created_at": r.created_at, "duration_minutes": r.duration_minutes,
                     "next_return_date": r.next_return_date, **decrypt_health(r.data_enc)} for r in records],
        "files": [{"id": str(f.id), "name": f.original_name, "size": f.size_bytes, "created_at": f.created_at}
                  for f in files],
    }


@router.post("/treatments/{treatment_id}/records", status_code=201)
def add_record(treatment_id: uuid.UUID, data: TreatmentRecordIn, db: Session = Depends(get_db),
               user: User = Depends(require("clinical.write"))):
    t = db.get(Treatment, treatment_id)
    if t is None:
        raise NotFound("Atendimento")
    _own_treatment(user, t)
    content = {k: getattr(data, k) for k in RECORD_FIELDS}
    rec = TreatmentRecord(treatment_id=t.id, data_enc=encrypt_health(content), duration_minutes=data.duration_minutes,
                          next_return_date=data.next_return_date, created_by=user.id)
    db.add(rec)
    if data.next_return_date:
        from app.models.crm import CrmTask
        from datetime import time

        from app.core.utils import clinic_tz

        db.add(CrmTask(title=f"Retorno recomendado: {t.customer.full_name}", kind="retorno",
                       due_at=datetime.combine(data.next_return_date, time(9), tzinfo=clinic_tz()),
                       customer_id=t.customer_id, created_by=user.id,
                       description="Retorno sugerido na ficha de atendimento (sem detalhes clínicos)."))
    audit(db, "ficha_atendimento_registrada", user=user, entity="treatment", entity_id=t.id, sensitive=True)
    db.commit()
    return {"message": "Ficha de atendimento registrada.", "id": str(rec.id)}


@router.get("/customers/{customer_id}/files")
def list_files(customer_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("clinical.read"))):
    get_customer_for(db, user, customer_id)
    rows = db.scalars(select(StoredFile).where(StoredFile.customer_id == customer_id, StoredFile.category == "clinical")
                      .order_by(StoredFile.created_at.desc())).all()
    return [{"id": str(f.id), "name": f.original_name, "content_type": f.content_type, "size": f.size_bytes,
             "description": f.description, "created_at": f.created_at,
             "treatment_id": str(f.treatment_id) if f.treatment_id else None} for f in rows]


@router.post("/customers/{customer_id}/files", status_code=201)
async def upload_file(customer_id: uuid.UUID, file: UploadFile = File(...), description: str | None = Form(None),
                      treatment_id: uuid.UUID | None = Form(None), db: Session = Depends(get_db),
                      user: User = Depends(require("clinical.write"))):
    get_customer_for(db, user, customer_id)
    if treatment_id:
        t = db.get(Treatment, treatment_id)
        if t is None or t.customer_id != customer_id:
            raise NotFound("Atendimento")
        _own_treatment(user, t)
    data = await file.read()
    rec = save_file(db, data, filename=file.filename or "documento", content_type=file.content_type, category="clinical",
                    user_id=user.id, sensitive=True, description=description, customer_id=customer_id,
                    treatment_id=treatment_id)
    audit(db, "documento_clinico_anexado", user=user, entity="customer", entity_id=customer_id,
          details={"arquivo": rec.original_name}, sensitive=True)
    db.commit()
    return {"message": "Documento anexado.", "id": str(rec.id)}


@router.get("/files/{file_id}")
def download_file(file_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("clinical.read"))):
    f = db.get(StoredFile, file_id)
    if f is None or f.category != "clinical" or f.customer_id is None:
        raise NotFound("Documento")
    get_customer_for(db, user, f.customer_id)
    data = read_file(f)
    audit(db, "documento_clinico_baixado", user=user, entity="file", entity_id=f.id, sensitive=True)
    db.commit()
    return Response(content=data, media_type=f.content_type,
                    headers={"Content-Disposition": f'attachment; filename="{f.original_name}"'})


@router.delete("/files/{file_id}")
def remove_file(file_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("clinical.write"))):
    f = db.get(StoredFile, file_id)
    if f is None or f.category != "clinical" or f.customer_id is None:
        raise NotFound("Documento")
    get_customer_for(db, user, f.customer_id)
    delete_file(db, f)
    audit(db, "documento_clinico_removido", user=user, entity="file", entity_id=file_id, sensitive=True)
    db.commit()
    return {"message": "Documento removido."}
