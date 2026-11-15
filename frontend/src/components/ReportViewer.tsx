import { Download, Printer } from "lucide-react";
import { useState } from "react";
import { download } from "../lib/api";
import { date, dateTime, money } from "../lib/format";
import { useGet } from "../lib/hooks";
import { PeriodPicker } from "./shared";
import { Alert, Button, Card, DataTable, Loading, useToast } from "./ui";

function fmt(v: any, kind: string) {
  if (v === null || v === undefined || v === "") return "—";
  if (kind === "money") return money(v);
  if (kind === "date") return date(v);
  if (kind === "datetime") return dateTime(v);
  if (kind === "percent") return `${Number(v).toLocaleString("pt-BR")}%`;
  return String(v);
}

export function ReportViewer({ reportKey, initialStart, initialEnd }: { reportKey: string; initialStart: string; initialEnd: string }) {
  const [p, setP] = useState({ start: initialStart, end: initialEnd });
  const q = useGet<any>(["report", reportKey], `/reports/${reportKey}`, p);
  const toast = useToast();
  const exp = (format: string) => download(`/reports/${reportKey}/export`, { ...p, format }).catch((e) => toast.error(e));
  return (
    <div className="space-y-3">
      <div className="no-print flex flex-wrap items-center justify-between gap-2">
        <PeriodPicker start={p.start} end={p.end} onChange={(s, e) => setP({ start: s, end: e })} />
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} onClick={() => exp("pdf")}>PDF</Button>
          <Button size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} onClick={() => exp("xlsx")}>Excel</Button>
          <Button size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} onClick={() => exp("csv")}>CSV</Button>
          <Button size="sm" variant="ghost" icon={<Printer className="h-4 w-4" />} onClick={() => window.print()}>Imprimir</Button>
        </div>
      </div>
      {q.isLoading ? <Loading /> : q.error ? <Alert kind="danger">{(q.error as Error).message}</Alert> : q.data && (
        <Card title={q.data.title} actions={<span className="text-xs text-slate-500">{q.data.period}</span>} padded={false}>
          <DataTable rowKey="__i" rows={[...q.data.rows.map((r: any, i: number) => ({ ...r, __i: i })),
            ...(Object.keys(q.data.totals).length ? [{ ...q.data.totals, __i: "total", __total: true }] : [])]}
            empty={<p className="px-4 py-6 text-sm text-slate-500">Sem registros no período.</p>}
            columns={q.data.columns.map((c: any, idx: number) => ({
              key: c.key, label: c.label,
              className: ["money", "int", "percent"].includes(c.kind) ? "text-right tabular-nums" : undefined,
              render: (r: any) => r.__total ? <b>{idx === 0 && !(c.key in q.data.totals) ? "TOTAL" : c.key in q.data.totals ? fmt(r[c.key], c.kind) : ""}</b> : fmt(r[c.key], c.kind),
            }))} />
          {q.data.notes.map((n: string) => <p key={n} className="px-4 py-2 text-xs text-slate-500">{n}</p>)}
        </Card>
      )}
    </div>
  );
}
