import { Download, Paperclip } from "lucide-react";
import { useState } from "react";
import { CrudList, PeriodPicker } from "../../components/shared";
import { ReportViewer } from "../../components/ReportViewer";
import { Alert, Badge, Button, Card, Checkbox, DataTable, Empty, Field, Input, Modal, PageHeader, Select, StatusBadge, Tabs, Textarea, useToast } from "../../components/ui";
import { del, download, post, put, upload } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { addDays, date, dateTime, doc, isoDay, money, monthEnd, monthStart } from "../../lib/format";
import { useAction, useGet } from "../../lib/hooks";

function pickFile(accept: string, onFile: (f: File) => void) {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = accept;
  input.onchange = () => input.files?.[0] && onFile(input.files[0]);
  input.click();
}

function useUploader() {
  const toast = useToast();
  return (path: string, after?: () => void) => pickFile(".pdf,image/*,.xml", async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    try { await upload(path, fd); toast.success("Arquivo anexado."); after?.(); } catch (e) { toast.error(e); }
  });
}

/* ------------------------------------------------------------------ Notas recebidas */
export function ReceivedPage() {
  const { can } = useAuth();
  const [p, setP] = useState({ start: monthStart(), end: monthEnd() });
  const list = useGet<any[]>(["fiscal-docs"], "/fiscal/documents", p);
  const [editing, setEditing] = useState<any>(null);
  const uploadTo = useUploader();
  const toast = useToast();
  const remove = useAction((id: string) => del(`/fiscal/documents/${id}`), { invalidate: [["fiscal-docs"]] });
  return (
    <div>
      <PageHeader title="Notas e documentos fiscais recebidos" subtitle="Serviços tomados, notas de compra e comprovantes com retenções."
        actions={can("fiscal.documents") && <Button onClick={() => setEditing({})}>Registrar documento</Button>} />
      <Card padded={false} actions={<PeriodPicker start={p.start} end={p.end} onChange={(s, e) => setP({ start: s, end: e })} />} title="Documentos">
        <DataTable rows={list.data || []} empty={<Empty title="Nenhum documento no período" />} columns={[
          { key: "issue_date", label: "Emissão", render: (r) => date(r.issue_date) },
          { key: "doc_type", label: "Tipo", render: (r) => <Badge color="blue">{r.doc_type.toUpperCase()}</Badge> },
          { key: "number", label: "Número", render: (r) => r.number || "—" },
          { key: "issuer_name", label: "Emitente", render: (r) => <span>{r.issuer_name} <span className="text-xs text-slate-500">{r.issuer_document ? doc(r.issuer_document) : ""}</span></span> },
          { key: "amount", label: "Valor", render: (r) => money(r.amount) },
          { key: "retention_total", label: "Retenções", render: (r) => money(r.retention_total) },
          { key: "files", label: "Arquivos", render: (r) => r.files.map((f: any) => <button key={f.id} className="mr-2 text-xs text-brand-600" onClick={() => download(`/fiscal/files/${f.id}`).catch((e) => toast.error(e))}>{f.name}</button>) },
          { key: "a", label: "", render: (r) => can("fiscal.documents") && (
            <div className="flex justify-end gap-1">
              <Button size="sm" variant="ghost" icon={<Paperclip className="h-3.5 w-3.5" />} onClick={() => uploadTo(`/fiscal/documents/${r.id}/files`, () => list.refetch())}>Anexar</Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Editar</Button>
              <Button size="sm" variant="ghost" onClick={() => remove.mutate(r.id)}>Excluir</Button>
            </div>) },
        ]} />
      </Card>
      {editing && <DocumentForm doc0={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function DocumentForm({ doc0, onClose }: { doc0: any; onClose: () => void }) {
  const [f, setF] = useState<any>({ direction: doc0.direction || "recebido", doc_type: doc0.doc_type || "nfse", number: doc0.number || "", series: doc0.series || "",
    access_key: doc0.access_key || "", issuer_name: doc0.issuer_name || "", issuer_document: doc0.issuer_document || "", issue_date: doc0.issue_date || isoDay(),
    competence_date: doc0.competence_date || "", amount: doc0.amount ?? "", service_taken: doc0.service_taken ?? true, description: doc0.description || "", notes: doc0.notes || "",
    retentions: { iss: "", irrf: "", pis: "", cofins: "", csll: "", inss: "", ...(doc0.retentions || {}) } });
  const save = useAction(() => {
    const body = { ...f, amount: String(f.amount || 0), competence_date: f.competence_date || null, issuer_document: f.issuer_document || null,
      retentions: Object.fromEntries(Object.entries(f.retentions).filter(([, v]) => v !== "" && Number(v) > 0).map(([k, v]) => [k, String(v)])) };
    return doc0.id ? put(`/fiscal/documents/${doc0.id}`, body) : post("/fiscal/documents", body);
  }, { invalidate: [["fiscal-docs"]], onDone: onClose });
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal open onClose={onClose} title={doc0.id ? "Editar documento" : "Registrar documento"} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={save.isPending} disabled={!f.issuer_name} onClick={() => save.mutate(undefined)}>Salvar</Button></>}>
      <div className="grid gap-3 sm:grid-cols-6">
        <Field label="Tipo" className="sm:col-span-2"><Select value={f.doc_type} onChange={set("doc_type")}>{["nfse", "nfe", "nfce", "cte", "recibo", "fatura", "guia", "outro"].map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}</Select></Field>
        <Field label="Número" className="sm:col-span-2"><Input value={f.number} onChange={set("number")} /></Field>
        <Field label="Série" className="sm:col-span-2"><Input value={f.series} onChange={set("series")} /></Field>
        <Field label="Emitente" required className="sm:col-span-4"><Input value={f.issuer_name} onChange={set("issuer_name")} /></Field>
        <Field label="CPF/CNPJ do emitente" className="sm:col-span-2"><Input value={f.issuer_document} onChange={set("issuer_document")} /></Field>
        <Field label="Emissão" className="sm:col-span-2"><Input type="date" value={f.issue_date} onChange={set("issue_date")} /></Field>
        <Field label="Competência" className="sm:col-span-2"><Input type="date" value={f.competence_date} onChange={set("competence_date")} /></Field>
        <Field label="Valor" className="sm:col-span-2"><Input type="number" step="0.01" value={f.amount} onChange={set("amount")} /></Field>
        <Field label="Chave de acesso" className="sm:col-span-6"><Input value={f.access_key} onChange={set("access_key")} /></Field>
        <div className="sm:col-span-6">
          <p className="label">Retenções (R$)</p>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            {Object.keys(f.retentions).map((k) => <Field key={k} label={k.toUpperCase()}><Input type="number" step="0.01" value={f.retentions[k]} onChange={(e) => setF({ ...f, retentions: { ...f.retentions, [k]: e.target.value } })} /></Field>)}
          </div>
        </div>
        <div className="sm:col-span-6"><Checkbox label="Serviço tomado pela clínica" checked={f.service_taken} onChange={(v) => setF({ ...f, service_taken: v })} /></div>
        <Field label="Descrição" className="sm:col-span-6"><Textarea value={f.description} onChange={set("description")} /></Field>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ Tributos */
export function TaxesPage() {
  const { can } = useAuth();
  const [tab, setTab] = useState("apuracoes");
  const catalog = useGet<any>(["tax-catalog"], "/fiscal/taxes/catalog");
  const taxes = Object.entries(catalog.data?.taxes || {}).map(([value, label]) => ({ value, label: `${value} — ${label}` }));
  const regimes = (catalog.data?.regimes || []).map((r: string) => ({ value: r, label: r }));
  return (
    <div>
      <PageHeader title="Tributos" subtitle="Estimativas parametrizáveis por regime e vigência. Todos os valores são estimativas até validação do contador." />
      <Alert kind="warning">O sistema não aplica tributação automaticamente: somente regras cadastradas (e vigentes) para o regime configurado são usadas. Considere a transição da Reforma Tributária (IBS/CBS) conforme orientação do contador.</Alert>
      <div className="mt-4"><Tabs value={tab} onChange={setTab} tabs={[{ key: "apuracoes", label: "Apurações e guias" }, { key: "regras", label: "Regras tributárias" }]} /></div>
      {tab === "apuracoes" && <Assessments />}
      {tab === "regras" && (
        <CrudList title="Regras tributárias (com vigência)" path="/fiscal/tax-rates" queryKey="tax-rates" canWrite={can("fiscal.taxes")}
          columns={[
            { key: "tax", label: "Tributo" }, { key: "regime", label: "Regime" }, { key: "rate", label: "Alíquota %", render: (r) => r.base === "fixo" ? `valor fixo ${money(r.rate)}` : `${r.rate}%` },
            { key: "base", label: "Base", render: (r) => r.base === "presuncao" ? `presunção ${r.presumption_percent}%` : r.base },
            { key: "v", label: "Vigência", render: (r) => `${date(r.valid_from)} → ${r.valid_to ? date(r.valid_to) : "atual"}` },
            { key: "validated", label: "Validação", render: (r) => r.validated ? <Badge color="green">{r.validated_by}</Badge> : <Badge color="yellow">pendente</Badge> },
          ]}
          transform={(b) => ({ ...b, rate: String(b.rate ?? 0), presumption_percent: b.presumption_percent === null ? null : String(b.presumption_percent), due_day: b.due_day ? Number(b.due_day) : null })}
          fields={[
            { key: "tax", label: "Tributo", type: "select", options: taxes, required: true, span: 3 },
            { key: "regime", label: "Regime", type: "select", options: regimes, required: true, span: 3 },
            { key: "rate", label: "Alíquota (%) ou valor fixo (R$)", type: "money", required: true, span: 2 },
            { key: "base", label: "Base de cálculo", type: "select", options: [{ value: "receita_bruta", label: "Receita bruta" }, { value: "presuncao", label: "Base presumida" }, { value: "fixo", label: "Valor fixo mensal" }], defaultValue: "receita_bruta", span: 2 },
            { key: "presumption_percent", label: "Presunção (%)", type: "money", span: 2 },
            { key: "valid_from", label: "Vigência inicial", type: "date", required: true, span: 2 },
            { key: "valid_to", label: "Vigência final", type: "date", span: 2 },
            { key: "due_day", label: "Dia de vencimento", type: "number", span: 2 },
            { key: "description", label: "Descrição", span: 6 },
            { key: "validated", label: "Validada pelo contador", type: "checkbox", span: 3 },
            { key: "validated_by", label: "Validada por", span: 3 },
            { key: "is_active", label: "Ativa", type: "checkbox", defaultValue: true, span: 3 },
            { key: "notes", label: "Observações", type: "textarea", span: 6 },
          ]} />
      )}
    </div>
  );
}

function Assessments() {
  const { can } = useAuth();
  const toast = useToast();
  const [year, setYear] = useState(new Date().getFullYear());
  const [period, setPeriod] = useState(isoDay().slice(0, 7));
  const [source, setSource] = useState("faturada");
  const list = useGet<any[]>(["assessments"], "/fiscal/assessments", { year });
  const estimate = useAction(() => post(`/fiscal/assessments/estimate`, undefined, { period, source }), { invalidate: [["assessments"]] });
  const payable = useAction((id: string) => post(`/fiscal/assessments/${id}/payable`), { invalidate: [["assessments"]] });
  const uploadTo = useUploader();
  const [editing, setEditing] = useState<any>(null);
  return (
    <div className="space-y-4">
      {can("fiscal.taxes") && (
        <Card title="Calcular estimativa">
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Competência"><Input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} /></Field>
            <Field label="Base de receita"><Select value={source} onChange={(e) => setSource(e.target.value)}><option value="faturada">Faturada (NFS-e autorizadas)</option><option value="contratada">Contratada (contas a receber)</option></Select></Field>
            <Button loading={estimate.isPending} onClick={() => estimate.mutate(undefined)}>Estimar tributos</Button>
          </div>
        </Card>
      )}
      <Card padded={false} title="Apurações" actions={<Input type="number" className="!w-24" value={year} onChange={(e) => setYear(Number(e.target.value))} />}>
        <DataTable rows={list.data || []} empty={<Empty title="Nenhuma apuração no ano" />} columns={[
          { key: "period", label: "Competência" }, { key: "tax", label: "Tributo" },
          { key: "base_amount", label: "Base", render: (r) => money(r.base_amount) },
          { key: "estimated_amount", label: "Estimado", render: (r) => money(r.estimated_amount) },
          { key: "final_amount", label: "Validado", render: (r) => money(r.final_amount) },
          { key: "due_date", label: "Vencimento", render: (r) => date(r.due_date) },
          { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
          { key: "files", label: "Guias", render: (r) => r.files.map((f: any) => <button key={f.id} className="mr-1 text-xs text-brand-600" onClick={() => download(`/fiscal/files/${f.id}`).catch((e) => toast.error(e))}>{f.name}</button>) },
          { key: "a", label: "", render: (r) => can("fiscal.taxes") && (
            <div className="flex justify-end gap-1">
              <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Atualizar</Button>
              <Button size="sm" variant="ghost" icon={<Paperclip className="h-3.5 w-3.5" />} onClick={() => uploadTo(`/fiscal/assessments/${r.id}/files`, () => list.refetch())}>Guia</Button>
              {can("finance.write") && !r.payable_id && r.final_amount !== null && <Button size="sm" variant="ghost" onClick={() => payable.mutate(r.id)}>Lançar a pagar</Button>}
            </div>) },
        ]} />
      </Card>
      {editing && <AssessmentForm a={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function AssessmentForm({ a, onClose }: { a: any; onClose: () => void }) {
  const [f, setF] = useState({ final_amount: a.final_amount ?? "", status: a.status, due_date: a.due_date || "", paid_at: a.paid_at || "", paid_amount: a.paid_amount ?? "", validated_by: a.validated_by || "", notes: a.notes || "" });
  const save = useAction(() => put(`/fiscal/assessments/${a.id}`, { ...f, final_amount: f.final_amount === "" ? null : String(f.final_amount), paid_amount: f.paid_amount === "" ? null : String(f.paid_amount),
    due_date: f.due_date || null, paid_at: f.paid_at || null, validated_by: f.validated_by || null, notes: f.notes || null }), { invalidate: [["assessments"]], onDone: onClose });
  return (
    <Modal open onClose={onClose} title={`${a.tax} — ${a.period}`} size="sm" footer={<Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Salvar</Button>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <p className="text-xs text-slate-500 sm:col-span-2">{a.calculation_notes}</p>
        <Field label="Situação"><Select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="estimado">Estimado</option><option value="validado">Validado</option><option value="pago">Pago</option><option value="cancelado">Cancelado</option></Select></Field>
        <Field label="Valor validado/final"><Input type="number" step="0.01" value={f.final_amount} onChange={(e) => setF({ ...f, final_amount: e.target.value })} /></Field>
        <Field label="Vencimento"><Input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></Field>
        <Field label="Validado por"><Input value={f.validated_by} onChange={(e) => setF({ ...f, validated_by: e.target.value })} /></Field>
        <Field label="Pago em"><Input type="date" value={f.paid_at} onChange={(e) => setF({ ...f, paid_at: e.target.value })} /></Field>
        <Field label="Valor pago"><Input type="number" step="0.01" value={f.paid_amount} onChange={(e) => setF({ ...f, paid_amount: e.target.value })} /></Field>
        <Field label="Observações" className="sm:col-span-2"><Textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ Obrigações */
export function ObligationsPage() {
  const { can } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState("calendario");
  const [p, setP] = useState({ start: addDays(monthStart(), -31), end: addDays(monthEnd(), 62) });
  const [period, setPeriod] = useState(isoDay().slice(0, 7));
  const list = useGet<any[]>(["obligations"], "/fiscal/obligations", p);
  const generate = useAction(() => post("/fiscal/obligations/generate", undefined, { period }), { invalidate: [["obligations"]] });
  const uploadTo = useUploader();
  const [editing, setEditing] = useState<any>(null);
  return (
    <div>
      <PageHeader title="Obrigações contábeis e fiscais" subtitle="Calendário configurável. O status é informado pela equipe/contador: o sistema não transmite declarações." />
      <Tabs value={tab} onChange={setTab} tabs={[{ key: "calendario", label: "Calendário" }, { key: "modelos", label: "Modelos aplicáveis" }]} />
      {tab === "calendario" ? (
        <div className="space-y-4">
          {can("fiscal.obligations") && (
            <Card title="Gerar obrigações do mês (a partir dos modelos ativos)">
              <div className="flex flex-wrap items-end gap-2">
                <Field label="Mês"><Input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} /></Field>
                <Button loading={generate.isPending} onClick={() => generate.mutate(undefined)}>Gerar</Button>
                <Button variant="secondary" onClick={() => setEditing({ __new: true })}>Incluir obrigação avulsa</Button>
              </div>
            </Card>
          )}
          <Card padded={false} title="Obrigações" actions={<PeriodPicker start={p.start} end={p.end} onChange={(s, e) => setP({ start: s, end: e })} />}>
            <DataTable rows={list.data || []} empty={<Empty title="Nenhuma obrigação no período" text="Ative os modelos aplicáveis à clínica e gere o calendário." />} columns={[
              { key: "due_date", label: "Prazo", render: (r) => <span className={r.status === "atrasado" ? "font-semibold text-rose-600" : ""}>{date(r.due_date)}</span> },
              { key: "name", label: "Obrigação" }, { key: "reference_period", label: "Referência" },
              { key: "responsible", label: "Responsável", render: (r) => r.responsible || "—" },
              { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
              { key: "delivered_at", label: "Entrega", render: (r) => date(r.delivered_at) },
              { key: "files", label: "Comprovantes", render: (r) => r.files.map((f: any) => <button key={f.id} className="mr-1 text-xs text-brand-600" onClick={() => download(`/fiscal/files/${f.id}`).catch((e) => toast.error(e))}>{f.name}</button>) },
              { key: "a", label: "", render: (r) => can("fiscal.obligations") && (
                <div className="flex justify-end gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Atualizar</Button>
                  <Button size="sm" variant="ghost" icon={<Paperclip className="h-3.5 w-3.5" />} onClick={() => uploadTo(`/fiscal/obligations/${r.id}/files`, () => list.refetch())}>Comprovante</Button>
                </div>) },
            ]} />
          </Card>
        </div>
      ) : (
        <CrudList title="Modelos de obrigações" path="/fiscal/obligation-templates" queryKey="obligation-templates" canWrite={can("fiscal.obligations")}
          columns={[
            { key: "name", label: "Obrigação" }, { key: "frequency", label: "Periodicidade" },
            { key: "due", label: "Prazo de referência", render: (r) => r.frequency === "anual" ? `${r.due_day}/${String(r.due_month).padStart(2, "0")}` : `dia ${r.due_day}` },
            { key: "applicable_regimes", label: "Regimes", render: (r) => (r.applicable_regimes || []).join(", ") },
            { key: "is_active", label: "Aplica-se à clínica", render: (r) => r.is_active ? <Badge color="green">sim</Badge> : <Badge color="gray">não</Badge> },
          ]}
          transform={(b) => ({ ...b, due_day: Number(b.due_day), due_month: b.due_month ? Number(b.due_month) : null, reference_offset_months: Number(b.reference_offset_months ?? 1),
            applicable_regimes: typeof b.applicable_regimes === "string" ? b.applicable_regimes.split(",").map((x: string) => x.trim()).filter(Boolean) : b.applicable_regimes || [] })}
          fields={[
            { key: "name", label: "Nome", required: true, span: 4 }, { key: "code", label: "Código", required: true, span: 2 },
            { key: "frequency", label: "Periodicidade", type: "select", options: [{ value: "mensal", label: "Mensal" }, { value: "anual", label: "Anual" }], required: true, span: 2 },
            { key: "due_day", label: "Dia do prazo", type: "number", required: true, span: 2 }, { key: "due_month", label: "Mês (anual)", type: "number", span: 2 },
            { key: "reference_offset_months", label: "Meses de defasagem da referência", type: "number", defaultValue: 1, span: 3 },
            { key: "applicable_regimes", label: "Regimes (separados por vírgula)", span: 3, hint: "mei, simples_nacional, lucro_presumido, lucro_real" },
            { key: "responsible", label: "Responsável", span: 3 },
            { key: "requires_employees", label: "Somente com empregados", type: "checkbox", span: 3 },
            { key: "is_active", label: "Aplica-se à clínica (ativo)", type: "checkbox", span: 3 },
            { key: "description", label: "Descrição", type: "textarea", span: 6 },
          ]} />
      )}
      {editing && <ObligationForm o={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ObligationForm({ o, onClose }: { o: any; onClose: () => void }) {
  const isNew = !!o.__new;
  const [f, setF] = useState({ name: o.name || "", code: o.code || "", reference_period: o.reference_period || isoDay().slice(0, 7), status: o.status || "pendente",
    due_date: o.due_date || isoDay(), responsible: o.responsible || "", delivered_at: o.delivered_at || "", receipt_number: o.receipt_number || "", notes: o.notes || "" });
  const save = useAction(() => isNew
    ? post("/fiscal/obligations", { name: f.name, code: f.code, reference_period: f.reference_period, due_date: f.due_date, responsible: f.responsible || null, notes: f.notes || null })
    : put(`/fiscal/obligations/${o.id}`, { status: f.status, due_date: f.due_date, responsible: f.responsible || null, delivered_at: f.delivered_at || null, receipt_number: f.receipt_number || null, notes: f.notes || null }),
  { invalidate: [["obligations"]], onDone: onClose });
  return (
    <Modal open onClose={onClose} title={isNew ? "Nova obrigação" : o.name} size="sm" footer={<Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Salvar</Button>}>
      <div className="grid gap-3 sm:grid-cols-2">
        {isNew && <>
          <Field label="Nome" className="sm:col-span-2"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Código"><Input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>
          <Field label="Referência (AAAA-MM ou AAAA)"><Input value={f.reference_period} onChange={(e) => setF({ ...f, reference_period: e.target.value })} /></Field>
        </>}
        {!isNew && <Field label="Situação"><Select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
          {["pendente", "em_preparacao", "enviado", "concluido", "atrasado", "nao_aplicavel"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
        </Select></Field>}
        <Field label="Prazo"><Input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></Field>
        <Field label="Responsável"><Input value={f.responsible} onChange={(e) => setF({ ...f, responsible: e.target.value })} /></Field>
        {!isNew && <Field label="Data de entrega/envio"><Input type="date" value={f.delivered_at} onChange={(e) => setF({ ...f, delivered_at: e.target.value })} /></Field>}
        {!isNew && <Field label="Nº do recibo/protocolo" className="sm:col-span-2"><Input value={f.receipt_number} onChange={(e) => setF({ ...f, receipt_number: e.target.value })} /></Field>}
        <Field label="Observações" className="sm:col-span-2"><Textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        {!isNew && ["enviado", "concluido"].includes(f.status) && <div className="sm:col-span-2"><Alert kind="info">Informe o recibo oficial e anexe o comprovante: o sistema registra a informação prestada, sem confirmação automática do órgão.</Alert></div>}
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ Receitas e despesas / documentos / exportação */
export function LedgerPage() {
  return (
    <div>
      <PageHeader title="Receitas e despesas" subtitle="Escrituração auxiliar por competência e pagamento, com categoria, centro de custo, documento e forma de pagamento." />
      <ReportViewer reportKey="receitas_despesas" initialStart={monthStart()} initialEnd={monthEnd()} />
    </div>
  );
}

export function DocumentsPage() {
  const toast = useToast();
  const year = new Date().getFullYear();
  const docs = useGet<any[]>(["fiscal-docs-all"], "/fiscal/documents", { start: `${year - 1}-01-01`, end: isoDay() });
  const obligations = useGet<any[]>(["obligations-all"], "/fiscal/obligations", { start: `${year - 1}-01-01`, end: `${year}-12-31` });
  const assessments = useGet<any[]>(["assessments"], "/fiscal/assessments", { year });
  const exports = useGet<any[]>(["exports"], "/fiscal/exports");
  const rows = [
    ...(docs.data || []).flatMap((d) => d.files.map((f: any) => ({ id: f.id, name: f.name, kind: `Documento recebido (${d.doc_type.toUpperCase()} ${d.number || ""})`, when: d.issue_date }))),
    ...(obligations.data || []).flatMap((o) => o.files.map((f: any) => ({ id: f.id, name: f.name, kind: `Comprovante — ${o.name} ${o.reference_period}`, when: o.delivered_at || o.due_date }))),
    ...(assessments.data || []).flatMap((a) => a.files.map((f: any) => ({ id: f.id, name: f.name, kind: `Guia — ${a.tax} ${a.period}`, when: a.due_date }))),
  ];
  return (
    <div>
      <PageHeader title="Documentos contábeis" subtitle="Guias, comprovantes e documentos fiscais anexados, disponíveis ao contador." />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card padded={false} title="Arquivos" className="lg:col-span-2">
          <DataTable rows={rows} empty={<Empty title="Nenhum arquivo anexado" />} columns={[
            { key: "kind", label: "Documento" }, { key: "name", label: "Arquivo" }, { key: "when", label: "Data", render: (r) => date(r.when) },
            { key: "a", label: "", render: (r) => <Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} onClick={() => download(`/fiscal/files/${r.id}`).catch((e) => toast.error(e))}>Baixar</Button> },
          ]} />
        </Card>
        <Card title="Últimos pacotes gerados">
          {(exports.data || []).slice(0, 8).map((e) => (
            <div key={e.id} className="flex items-center justify-between border-b border-slate-100 py-2 text-sm last:border-0 dark:border-slate-800">
              <span>{date(e.period_start)} → {date(e.period_end)}</span><Badge color={e.status === "gerado" ? "gray" : "green"}>{e.status}</Badge>
            </div>
          ))}
          {(exports.data || []).length === 0 && <p className="text-sm text-slate-500">Nenhum pacote gerado.</p>}
        </Card>
      </div>
    </div>
  );
}

export function ExportPage() {
  const { can } = useAuth();
  const toast = useToast();
  const prevStart = addDays(monthStart(), -1).slice(0, 8) + "01";
  const [f, setF] = useState({ start: prevStart, end: addDays(monthStart(), -1), formats: ["csv", "xlsx", "pdf", "xml", "anexos"], notes: "" });
  const list = useGet<any[]>(["exports"], "/fiscal/exports");
  const create = useAction(() => post("/fiscal/exports", f), { invalidate: [["exports"]] });
  const [marking, setMarking] = useState<any>(null);
  const [mark, setMark] = useState({ status: "enviado", sent_to: "", sent_method: "e-mail" });
  const markSave = useAction(() => put(`/fiscal/exports/${marking.id}`, mark), { invalidate: [["exports"]], onDone: () => setMarking(null) });
  const toggle = (fmt: string) => setF({ ...f, formats: f.formats.includes(fmt) ? f.formats.filter((x) => x !== fmt) : [...f.formats, fmt] });
  return (
    <div>
      <PageHeader title="Exportação para o contador" subtitle="Pacote ZIP com relatórios (CSV, XLSX, PDF), XMLs das notas, DANFSe e comprovantes. Dados de saúde nunca são exportados." />
      <div className="grid gap-4 lg:grid-cols-3">
        {can("fiscal.export") && (
          <Card title="Gerar pacote">
            <div className="space-y-3">
              <PeriodPicker start={f.start} end={f.end} onChange={(s, e) => setF({ ...f, start: s, end: e })} />
              <div className="space-y-1.5">
                {[["csv", "Relatórios em CSV"], ["xlsx", "Planilha Excel (XLSX)"], ["pdf", "Relatórios em PDF"], ["xml", "XMLs de NFS-e, eventos e documentos recebidos"], ["anexos", "Comprovantes e documentos anexados"]].map(([k, l]) => (
                  <Checkbox key={k} label={l} checked={f.formats.includes(k)} onChange={() => toggle(k)} />
                ))}
              </div>
              <Field label="Observações"><Textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
              <Button loading={create.isPending} disabled={!f.formats.length} onClick={() => create.mutate(undefined)}>Gerar pacote</Button>
            </div>
          </Card>
        )}
        <Card padded={false} title="Histórico de pacotes" className="lg:col-span-2">
          <DataTable rows={list.data || []} empty={<Empty title="Nenhum pacote gerado" />} columns={[
            { key: "p", label: "Período", render: (r) => `${date(r.period_start)} → ${date(r.period_end)}` },
            { key: "contents", label: "Conteúdo", render: (r) => <span className="text-xs">{r.contents.xml_nfse} XML · {r.contents.danfse} DANFSe · {r.contents.anexos} anexos</span> },
            { key: "created_at", label: "Gerado em", render: (r) => dateTime(r.created_at) },
            { key: "status", label: "Situação", render: (r) => <span><Badge color={r.status === "gerado" ? "gray" : "green"}>{r.status}</Badge> {r.sent_to && <span className="text-xs text-slate-500">para {r.sent_to}</span>}</span> },
            { key: "a", label: "", render: (r) => can("fiscal.export") && (
              <div className="flex justify-end gap-1">
                <Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} onClick={() => download(`/fiscal/exports/${r.id}/download`).then(() => list.refetch()).catch((e) => toast.error(e))}>ZIP</Button>
                <Button size="sm" variant="ghost" onClick={() => setMarking(r)}>Registrar envio</Button>
              </div>) },
          ]} />
        </Card>
      </div>
      <Modal open={!!marking} onClose={() => setMarking(null)} title="Registrar envio ao contador" size="sm" footer={<Button loading={markSave.isPending} onClick={() => markSave.mutate(undefined)}>Salvar</Button>}>
        <div className="grid gap-3">
          <Field label="Situação"><Select value={mark.status} onChange={(e) => setMark({ ...mark, status: e.target.value })}><option value="disponibilizado">Disponibilizado no sistema</option><option value="enviado">Enviado</option></Select></Field>
          <Field label="Enviado para"><Input value={mark.sent_to} onChange={(e) => setMark({ ...mark, sent_to: e.target.value })} /></Field>
          <Field label="Meio"><Input value={mark.sent_method} onChange={(e) => setMark({ ...mark, sent_method: e.target.value })} /></Field>
        </div>
      </Modal>
    </div>
  );
}
