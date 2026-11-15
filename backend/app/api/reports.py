from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import get_current_user, has_perm
from app.core.errors import AppError, Forbidden, NotFound
from app.models.auth import User
from app.models.system import Clinic
from app.services import reports as svc
from app.services.exporters import to_csv, to_pdf, to_xlsx

router = APIRouter(prefix="/reports", tags=["Relatórios"])


def _check(user: User, key: str) -> dict:
    meta = svc.REGISTRY.get(key)
    if meta is None:
        raise NotFound("Relatório")
    if not has_perm(user, svc.CATEGORY_PERMS[meta["category"]]):
        raise Forbidden("Sem permissão para este relatório.")
    return meta


@router.get("")
def catalog(user: User = Depends(get_current_user)):
    return [{"key": m["key"], "title": m["title"], "category": m["category"]}
            for m in svc.REGISTRY.values() if has_perm(user, svc.CATEGORY_PERMS[m["category"]])]


@router.get("/{key}")
def run_report(key: str, start: date, end: date, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _check(user, key)
    if end < start or (end - start).days > 1100:
        raise AppError("Período inválido (máximo de 3 anos).")
    r = svc.run(db, key, start, end)
    return {
        "title": r.title, "period": r.period, "notes": r.notes,
        "columns": [{"key": c.key, "label": c.label, "kind": c.kind} for c in r.columns],
        "rows": [{k: (float(v) if hasattr(v, "quantize") else v) for k, v in row.items()} for row in r.rows],
        "totals": {k: (float(v) if hasattr(v, "quantize") else v) for k, v in r.totals.items()},
    }


@router.get("/{key}/export")
def export_report(key: str, start: date, end: date, format: str = Query(..., pattern=r"^(csv|xlsx|pdf)$"),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _check(user, key)
    r = svc.run(db, key, start, end)
    name = f"{key}_{start:%Y%m%d}_{end:%Y%m%d}"
    if format == "csv":
        content, media = to_csv(r), "text/csv; charset=utf-8"
    elif format == "xlsx":
        content, media = to_xlsx([r]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        clinic = db.scalar(select(Clinic).limit(1))
        content = to_pdf([r], (clinic.trade_name or clinic.name) if clinic else "Corpo Sano", clinic.logo if clinic else None)
        media = "application/pdf"
    audit(db, "relatorio_exportado", user=user, entity="report", entity_id=key, details={"formato": format})
    db.commit()
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{format}"'})
