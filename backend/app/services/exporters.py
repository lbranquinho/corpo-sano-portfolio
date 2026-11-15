"""Renderização de relatórios em CSV, XLSX e PDF."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.utils import local_now, to_local

BRAND = colors.HexColor("#1E3A8A")
LIGHT = colors.HexColor("#DBEAFE")


@dataclass
class Column:
    key: str
    label: str
    kind: str = "text"  # text | money | int | date | datetime | percent


@dataclass
class ReportData:
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    period: str = ""


def _fmt(value: Any, kind: str, csv_mode: bool = False) -> str:
    if value is None:
        return ""
    if kind == "money":
        v = Decimal(str(value)).quantize(Decimal("0.01"))
        s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return s if csv_mode else f"R$ {s}"
    if kind == "percent":
        return f"{Decimal(str(value)):.2f}%".replace(".", ",")
    if kind == "date" and isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    if kind == "datetime" and isinstance(value, datetime):
        return to_local(value).strftime("%d/%m/%Y %H:%M")
    return str(value)


def to_csv(r: ReportData) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow([c.label for c in r.columns])
    for row in r.rows:
        w.writerow([_fmt(row.get(c.key), c.kind, csv_mode=True) for c in r.columns])
    if r.totals:
        w.writerow([_fmt(r.totals.get(c.key), c.kind, csv_mode=True) if c.key in r.totals else ("TOTAL" if i == 0 else "")
                    for i, c in enumerate(r.columns)])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def to_xlsx(reports: list[ReportData]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for r in reports:
        ws = wb.create_sheet(title=r.title[:31].replace("/", "-"))
        ws.append([r.title])
        ws["A1"].font = Font(bold=True, size=13, color="1E3A8A")
        ws.append([f"Período: {r.period}" if r.period else "", f"Gerado em {local_now():%d/%m/%Y %H:%M}"])
        ws.append([])
        ws.append([c.label for c in r.columns])
        header_row = ws.max_row
        for i, _ in enumerate(r.columns, start=1):
            cell = ws.cell(row=header_row, column=i)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="2563EB")
            cell.alignment = Alignment(vertical="center")
        for row in r.rows:
            values = []
            for c in r.columns:
                v = row.get(c.key)
                if c.kind == "money" and v is not None:
                    v = float(v)
                elif c.kind == "datetime" and isinstance(v, datetime):
                    v = to_local(v).replace(tzinfo=None)
                values.append(v)
            ws.append(values)
        if r.totals:
            ws.append([("TOTAL" if i == 0 else (float(r.totals[c.key]) if c.kind == "money" and c.key in r.totals
                                                  else r.totals.get(c.key))) for i, c in enumerate(r.columns)])
            for i in range(1, len(r.columns) + 1):
                ws.cell(row=ws.max_row, column=i).font = Font(bold=True)
        for i, c in enumerate(r.columns, start=1):
            letter = get_column_letter(i)
            width = max([len(c.label)] + [len(_fmt(row.get(c.key), c.kind)) for row in r.rows[:200]] + [8])
            ws.column_dimensions[letter].width = min(width + 2, 60)
            fmt = {"money": '"R$" #,##0.00', "date": "DD/MM/YYYY", "datetime": "DD/MM/YYYY HH:MM", "percent": "0.00"}.get(c.kind)
            if fmt:
                for cell in ws[letter][header_row:]:
                    cell.number_format = fmt
        for note in r.notes:
            ws.append([])
            ws.append([note])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(reports: list[ReportData], clinic_name: str, logo: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=14 * mm, title=reports[0].title if reports else "Relatório")
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=7.5, leading=9)
    story: list = []
    for idx, r in enumerate(reports):
        if logo and idx == 0:
            try:
                img = Image(io.BytesIO(logo), width=22 * mm, height=22 * mm, kind="proportional")
                img.hAlign = "LEFT"
                story.append(img)
            except Exception:  # noqa: BLE001 — logotipo inválido não impede o relatório
                pass
        story.append(Paragraph(f"<b>{clinic_name}</b>", styles["Heading4"]))
        story.append(Paragraph(f"<font color='#1E3A8A'><b>{r.title}</b></font>", styles["Heading2"]))
        story.append(Paragraph(f"Período: {r.period} — gerado em {local_now():%d/%m/%Y %H:%M}", small))
        story.append(Spacer(1, 4 * mm))
        data = [[Paragraph(f"<b>{c.label}</b>", small) for c in r.columns]]
        for row in r.rows:
            data.append([Paragraph(_fmt(row.get(c.key), c.kind), small) for c in r.columns])
        if r.totals:
            data.append([Paragraph("<b>TOTAL</b>" if i == 0 else f"<b>{_fmt(r.totals.get(c.key), c.kind)}</b>", small)
                         for i, c in enumerate(r.columns)])
        if len(data) == 1:
            data.append([Paragraph("Sem registros no período.", small)] + [""] * (len(r.columns) - 1))
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#94A3B8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
        for note in r.notes:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(f"<i>{note}</i>", small))
        if idx < len(reports) - 1:
            story.append(Spacer(1, 10 * mm))

    def footer(canvas, doc_):  # noqa: ANN001
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(12 * mm, 7 * mm, "Corpo Sano — relatório gerencial de apoio. Não substitui escrituração contábil "
                                           "oficial nem demonstrações assinadas por contador habilitado.")
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 7 * mm, f"Página {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
