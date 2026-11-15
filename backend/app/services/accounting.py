"""Pacote mensal para o contador (ZIP com relatórios, XMLs, DANFSe e comprovantes)."""
from __future__ import annotations

import io
import uuid
import zipfile
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.storage import read_file, save_file
from app.core.utils import local_now
from app.models.fiscal import AccountingExport, FiscalDocument, FiscalInvoice, FiscalInvoiceEvent, TaxAssessment, TaxObligation
from app.models.finance import Expense
from app.models.system import Clinic, StoredFile
from app.services import reports
from app.services.exporters import to_csv, to_pdf, to_xlsx

EXPORT_REPORTS = [
    "faturamento", "receitas_recebidas", "receitas_pendentes", "despesas", "notas_emitidas", "notas_canceladas",
    "notas_rejeitadas", "retencoes", "documentos_recebidos", "receitas_despesas", "tributos_estimados",
    "obrigacoes_pendentes", "fluxo_caixa", "resultado_operacional",
]
FORMATS = {"csv", "xlsx", "pdf", "xml", "anexos"}


def build_export(db: Session, start: date, end: date, formats: list[str], user_id: uuid.UUID | None,
                 notes: str | None = None) -> AccountingExport:
    fmts = set(formats) & FORMATS
    if not fmts:
        raise AppError("Selecione ao menos um formato.")
    if end < start or (end - start).days > 400:
        raise AppError("Período inválido (máximo de 400 dias).")
    clinic = db.scalar(select(Clinic).limit(1))
    data = [reports.run(db, key, start, end) for key in EXPORT_REPORTS]
    buf = io.BytesIO()
    contents: dict = {"relatorios": len(data), "xml_nfse": 0, "xml_eventos": 0, "danfse": 0, "anexos": 0}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if "csv" in fmts:
            for key, r in zip(EXPORT_REPORTS, data):
                z.writestr(f"relatorios/csv/{key}.csv", to_csv(r))
        if "xlsx" in fmts:
            z.writestr("relatorios/relatorios.xlsx", to_xlsx(data))
        if "pdf" in fmts:
            z.writestr("relatorios/relatorios.pdf", to_pdf(data, (clinic.trade_name or clinic.name) if clinic else "Corpo Sano",
                                                          clinic.logo if clinic else None))
        if "xml" in fmts:
            invs = db.scalars(select(FiscalInvoice).where(FiscalInvoice.competence_date.between(start, end),
                                                          FiscalInvoice.nfse_xml.is_not(None))).all()
            for inv in invs:
                name = f"{inv.environment}_{inv.nfse_number or inv.access_key}"
                z.writestr(f"xml/nfse/{name}.xml", inv.nfse_xml)
                contents["xml_nfse"] += 1
                for ev in db.scalars(select(FiscalInvoiceEvent).where(FiscalInvoiceEvent.invoice_id == inv.id,
                                                                      FiscalInvoiceEvent.xml.is_not(None))).all():
                    z.writestr(f"xml/eventos/{name}_{ev.event_code or ev.event_type}.xml", ev.xml)
                    contents["xml_eventos"] += 1
                if inv.danfse_file_id:
                    f = db.get(StoredFile, inv.danfse_file_id)
                    if f:
                        z.writestr(f"danfse/{name}.pdf", read_file(f))
                        contents["danfse"] += 1
            for doc in db.scalars(select(FiscalDocument).where(FiscalDocument.issue_date.between(start, end),
                                                               FiscalDocument.xml.is_not(None))).all():
                z.writestr(f"xml/recebidos/{doc.doc_type}_{doc.number or doc.id}.xml", doc.xml)
        if "anexos" in fmts:
            doc_ids = db.scalars(select(FiscalDocument.id).where(FiscalDocument.issue_date.between(start, end))).all()
            exp_ids = db.scalars(select(Expense.id).where(Expense.competence_date.between(start, end))).all()
            periods = [f"{start.year}-{m:02d}" for m in range(1, 13)]
            obl_ids = db.scalars(select(TaxObligation.id).where(TaxObligation.due_date.between(start, end))).all()
            tax_ids = db.scalars(select(TaxAssessment.id).where(TaxAssessment.period.in_(periods))).all()
            conds = []
            if doc_ids:
                conds.append(StoredFile.fiscal_document_id.in_(doc_ids))
            if exp_ids:
                conds.append(StoredFile.expense_id.in_(exp_ids))
            if obl_ids:
                conds.append(StoredFile.tax_obligation_id.in_(obl_ids))
            if tax_ids:
                conds.append(StoredFile.tax_assessment_id.in_(tax_ids))
            if conds:
                for f in db.scalars(select(StoredFile).where(and_(StoredFile.sensitive.is_(False), or_(*conds)))).all():
                    z.writestr(f"anexos/{f.category}/{f.id.hex[:8]}_{f.original_name}", read_file(f))
                    contents["anexos"] += 1
        z.writestr("LEIAME.txt", (
            f"Corpo Sano — pacote para a contabilidade\nPeríodo: {start:%d/%m/%Y} a {end:%d/%m/%Y}\n"
            f"Gerado em: {local_now():%d/%m/%Y %H:%M}\nConteúdo: {contents}\n\n"
            "Material de apoio gerencial/fiscal. Não constitui escrituração contábil oficial, balanço patrimonial ou\n"
            "demonstrações contábeis. Tributos apresentados são ESTIMATIVAS até validação pelo contador.\n"
            "Dados de saúde/anamnese NÃO fazem parte deste pacote.\n").encode("utf-8"))
    content = buf.getvalue()
    exp = AccountingExport(period_start=start, period_end=end, formats=sorted(fmts), contents=contents, status="gerado",
                           notes=notes, created_by=user_id)
    db.add(exp)
    db.flush()
    f = save_file(db, content, filename=f"contabilidade_{start:%Y%m%d}_{end:%Y%m%d}.zip", content_type="application/zip",
                  category="accounting", user_id=user_id, internal=True, accounting_export_id=exp.id)
    exp.file_id = f.id
    db.flush()
    return exp
