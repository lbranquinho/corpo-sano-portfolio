import { ArrowLeft, CheckCircle2, Circle, Download, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { CustomerPicker, PeriodPicker } from "../../components/shared";
import {
  Alert, Badge, Button, Card, Checkbox, DataTable, Empty, Field, Input, Loading, Modal, PageHeader, Pagination, Select, StatusBadge, Textarea, useToast,
} from "../../components/ui";
import { del, download, get, post, put } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { date, dateTime, doc, isoDay, money, monthEnd, monthStart } from "../../lib/format";
import { useAction, useGet } from "../../lib/hooks";

const EMPTY: any = {
  customer_id: null, taker_document: "", taker_name: "", taker_email: "", taker_phone: "", taker_zip_code: "", taker_street: "", taker_number: "",
  taker_complement: "", taker_district: "", taker_ibge_code: "", service_id: "", tax_service_code_id: "", description: "", competence_date: isoDay(),
  gross_amount: "", unconditional_discount: "0", conditional_discount: "0", deductions: "0", incidence_ibge: "", iss_rate: "", iss_withheld: false,
  retentions: { irrf: "", csll: "", cp: "", pis: "", cofins: "" }, total_tax_sn_percent: "", additional_info: "", receivable_id: null, package_id: null, appointment_id: null,
};

export function Readiness({ compact = false }: { compact?: boolean }) {
  const q = useGet<any>(["fiscal-readiness"], "/fiscal/readiness");
  if (!q.data) return null;
  const failed = q.data.checks.filter((c: any) => !c.ok && (c.required_for === "ambos" || q.data.environment === "producao"));
  if (compact && failed.length === 0) return <Alert kind="success">Configuração fiscal pronta para emissão em <b>{q.data.environment}</b>.</Alert>;
  return (
    <Card title={`Pré-requisitos para emissão (${q.data.environment === "producao" ? "Produção" : "Homologação"})`}>
      <ul className="grid gap-1.5 text-sm sm:grid-cols-2">
        {q.data.checks.map((c: any) => (
          <li key={c.key} className="flex items-start gap-2">
            {c.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />}
            <span className={c.ok ? "" : "text-slate-600 dark:text-slate-300"}>{c.message}{c.required_for === "producao" && <span className="text-xs text-slate-500 dark:text-slate-400"> (produção)</span>}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function IssuePage() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [p, setP] = useState({ start: monthStart(), end: monthEnd() });
  const pending = useGet<any>(["pending-billing"], "/fiscal/invoices/pending-billing", p);
  const [form, setForm] = useState<any>(null);
  const toast = useToast();
  async function startFrom(q: Record<string, string>) {
    try {
      const data = await get("/fiscal/invoices/prefill", q);
      setForm({ ...EMPTY, ...Object.fromEntries(Object.entries(data).map(([k, v]) => [k, v ?? EMPTY[k] ?? ""])) });
    } catch (e) {
      toast.error(e);
    }
  }
  useEffect(() => {
    const r = params.get("receber"), pk = params.get("pacote"), ap = params.get("agendamento");
    if (r) startFrom({ receivable_id: r });
    else if (pk) startFrom({ package_id: pk });
    else if (ap) startFrom({ appointment_id: ap });
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps
  if (form) return <InvoiceForm initial={form} onCancel={() => setForm(null)} onSaved={(inv) => navigate(`/fiscal/notas/${inv.id}`)} />;
  return (
    <div>
      <PageHeader title="Emissão de NFS-e" subtitle="Emita a partir de uma operação (evita duplicidade) ou manualmente." actions={can("fiscal.issue") && <Button variant="secondary" onClick={() => setForm({ ...EMPTY })}>Nota avulsa</Button>} />
      <div className="mb-4"><Readiness compact /></div>
      <Card padded={false} title={`Receita ainda não faturada — ${money(pending.data?.total)}`} actions={<PeriodPicker start={p.start} end={p.end} onChange={(s, e) => setP({ start: s, end: e })} />}>
        <DataTable rowKey="receivable_id" rows={pending.data?.items || []} empty={<Empty title="Toda a receita do período já está documentada" />} columns={[
          { key: "competence_date", label: "Competência", render: (r) => date(r.competence_date) },
          { key: "customer", label: "Cliente", render: (r) => <span>{r.customer || "—"} {r.customer && !r.has_cpf && <Badge color="gray">sem CPF</Badge>}</span> },
          { key: "description", label: "Operação" },
          { key: "amount", label: "Valor", render: (r) => money(r.amount) },
          { key: "status", label: "Pagamento", render: (r) => <StatusBadge status={r.status} /> },
          { key: "a", label: "", render: (r) => can("fiscal.issue") && (
            <div className="flex justify-end gap-1">
              <Button size="sm" onClick={() => startFrom({ receivable_id: r.receivable_id })}>Emitir</Button>
              {r.package_id && <Button size="sm" variant="ghost" onClick={() => startFrom({ package_id: r.package_id })}>Pacote inteiro</Button>}
            </div>) },
        ]} />
      </Card>
    </div>
  );
}

function InvoiceForm({ initial, invoiceId, onCancel, onSaved, substituteOf }: { initial: any; invoiceId?: string; onCancel: () => void; onSaved: (inv: any) => void; substituteOf?: string }) {
  const toast = useToast();
  const codes = useGet<any[]>(["tax-codes"], "/tax-service-codes");
  const services = useGet<any[]>(["services"], "/services", { active: true });
  const [f, setF] = useState<any>(initial);
  const [customer, setCustomer] = useState<any>(initial.customer_id ? { id: initial.customer_id, full_name: initial.taker_name } : null);
  const [subst, setSubst] = useState({ reason_code: "99", reason: "" });
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  const code = (codes.data || []).find((c) => c.id === f.tax_service_code_id);
  async function pickCustomer(c: any) {
    setCustomer(c);
    if (!c) return setF({ ...f, customer_id: null });
    const full = await get(`/customers/${c.id}`);
    setF({ ...f, customer_id: c.id, taker_document: full.cpf || "", taker_name: full.full_name, taker_email: full.email || "", taker_phone: full.whatsapp || full.phone || "",
      taker_zip_code: full.zip_code || "", taker_street: full.street || "", taker_number: full.number || "", taker_complement: full.complement || "",
      taker_district: full.district || "", taker_ibge_code: full.ibge_code || "" });
  }
  async function save() {
    setBusy(true);
    try {
      const n = (v: any) => (v === "" || v === null || v === undefined ? null : v);
      const retentions = Object.fromEntries(Object.entries(f.retentions || {}).filter(([, v]) => v !== "" && Number(v) > 0).map(([k, v]) => [k, String(v)]));
      const body: any = {
        ...Object.fromEntries(Object.entries(f).map(([k, v]) => [k, typeof v === "string" ? n(v) : v])),
        gross_amount: String(f.gross_amount), unconditional_discount: String(f.unconditional_discount || 0), conditional_discount: String(f.conditional_discount || 0),
        deductions: String(f.deductions || 0), iss_rate: n(f.iss_rate) === null ? null : String(f.iss_rate), total_tax_sn_percent: n(f.total_tax_sn_percent) === null ? null : String(f.total_tax_sn_percent),
        retentions, customer_id: customer?.id || null,
      };
      delete body.tax_code_validated;
      let r;
      if (substituteOf) r = await post(`/fiscal/invoices/${substituteOf}/substitute`, { ...body, ...subst });
      else if (invoiceId) r = await put(`/fiscal/invoices/${invoiceId}`, body);
      else r = await post("/fiscal/invoices", body);
      toast.success(r.message);
      onSaved(r.invoice);
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <button className="mb-3 flex items-center gap-1 text-sm text-slate-500 hover:text-brand-600" onClick={onCancel}><ArrowLeft className="h-4 w-4" /> Voltar</button>
      <PageHeader title={substituteOf ? "Substituir NFS-e" : invoiceId ? "Editar rascunho de NFS-e" : "Nova NFS-e (rascunho)"}
        subtitle="Revise os dados; a transmissão ao serviço oficial ocorre somente após a prévia." />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Tomador do serviço" className="lg:col-span-2">
          <div className="grid gap-3 sm:grid-cols-6">
            <Field label="Cliente" className="sm:col-span-6"><CustomerPicker value={customer} onChange={pickCustomer} allowCreate={false} /></Field>
            <Field label="CPF ou CNPJ" hint="Opcional para pessoa física não identificada, conforme regras do município." className="sm:col-span-2"><Input value={f.taker_document} onChange={set("taker_document")} /></Field>
            <Field label="Nome / razão social" className="sm:col-span-4"><Input value={f.taker_name} onChange={set("taker_name")} /></Field>
            <Field label="E-mail" className="sm:col-span-3"><Input value={f.taker_email} onChange={set("taker_email")} /></Field>
            <Field label="Telefone" className="sm:col-span-3"><Input value={f.taker_phone} onChange={set("taker_phone")} /></Field>
            <Field label="CEP" className="sm:col-span-2"><Input value={f.taker_zip_code} onChange={set("taker_zip_code")} /></Field>
            <Field label="Logradouro" className="sm:col-span-3"><Input value={f.taker_street} onChange={set("taker_street")} /></Field>
            <Field label="Número" className="sm:col-span-1"><Input value={f.taker_number} onChange={set("taker_number")} /></Field>
            <Field label="Complemento" className="sm:col-span-2"><Input value={f.taker_complement} onChange={set("taker_complement")} /></Field>
            <Field label="Bairro" className="sm:col-span-2"><Input value={f.taker_district} onChange={set("taker_district")} /></Field>
            <Field label="Cód. IBGE do município" className="sm:col-span-2"><Input value={f.taker_ibge_code} onChange={set("taker_ibge_code")} /></Field>
          </div>
        </Card>
        <Card title="Origem da operação">
          <div className="space-y-2 text-sm">
            {f.receivable_id && <p>Conta a receber vinculada ✔</p>}
            {f.package_id && <p>Venda de pacote vinculada ✔</p>}
            {f.appointment_id && <p>Atendimento vinculado ✔</p>}
            {!f.receivable_id && !f.package_id && !f.appointment_id && <Alert kind="warning">Nota avulsa sem operação vinculada: não há proteção automática contra duplicidade.</Alert>}
            {substituteOf && (
              <>
                <Field label="Código do motivo da substituição"><Input value={subst.reason_code} onChange={(e) => setSubst({ ...subst, reason_code: e.target.value })} /></Field>
                <Field label="Justificativa (15 a 255 caracteres)" required><Textarea value={subst.reason} onChange={(e) => setSubst({ ...subst, reason: e.target.value })} /></Field>
              </>
            )}
          </div>
        </Card>
        <Card title="Serviço e valores" className="lg:col-span-3">
          <div className="grid gap-3 sm:grid-cols-6">
            <Field label="Serviço prestado" className="sm:col-span-2">
              <Select value={f.service_id || ""} onChange={(e) => {
                const s = (services.data || []).find((x) => x.id === e.target.value);
                setF({ ...f, service_id: e.target.value, tax_service_code_id: s?.tax_service_code_id || f.tax_service_code_id, description: f.description || s?.nfse_description || (s ? `Serviço de ${s.name}` : "") });
              }}><option value="">—</option>{(services.data || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>
            </Field>
            <Field label="Código de serviço (tributação nacional)" required className="sm:col-span-4"
              hint={code && !code.validated ? "Atenção: código ainda não validado pelo contador." : undefined}>
              <Select value={f.tax_service_code_id || ""} onChange={(e) => {
                const c = (codes.data || []).find((x) => x.id === e.target.value);
                setF({ ...f, tax_service_code_id: e.target.value, iss_rate: c?.iss_rate ?? f.iss_rate, iss_withheld: c?.iss_withheld_default ?? f.iss_withheld });
              }}><option value="">Selecione</option>{(codes.data || []).filter((c) => c.is_active).map((c) => <option key={c.id} value={c.id}>{c.national_code} — {c.description}</option>)}</Select>
            </Field>
            <Field label="Descrição do serviço (aparece na nota)" required className="sm:col-span-6"><Textarea value={f.description} onChange={set("description")} /></Field>
            <Field label="Competência" className="sm:col-span-2"><Input type="date" max={isoDay()} value={f.competence_date} onChange={set("competence_date")} /></Field>
            <Field label="Valor bruto (R$)" required className="sm:col-span-2"><Input type="number" step="0.01" value={f.gross_amount} onChange={set("gross_amount")} /></Field>
            <Field label="Desconto incondicionado" className="sm:col-span-2"><Input type="number" step="0.01" value={f.unconditional_discount} onChange={set("unconditional_discount")} /></Field>
            <Field label="Desconto condicionado" className="sm:col-span-2"><Input type="number" step="0.01" value={f.conditional_discount} onChange={set("conditional_discount")} /></Field>
            <Field label="Deduções (quando legalmente permitidas)" className="sm:col-span-2"><Input type="number" step="0.01" value={f.deductions} onChange={set("deductions")} /></Field>
            <Field label="Município de incidência (IBGE)" hint="Vazio = município do prestador" className="sm:col-span-2"><Input value={f.incidence_ibge} onChange={set("incidence_ibge")} /></Field>
            <Field label="Alíquota ISS (%)" hint="Informada na DPS apenas para ME/EPP do Simples Nacional." className="sm:col-span-2"><Input type="number" step="0.01" value={f.iss_rate ?? ""} onChange={set("iss_rate")} /></Field>
            <div className="flex items-end sm:col-span-2"><Checkbox label="ISS retido pelo tomador" checked={!!f.iss_withheld} onChange={(v) => setF({ ...f, iss_withheld: v })} /></div>
            <Field label="% tributos Simples (pTotTribSN)" hint="Opcional — informado pelo contador" className="sm:col-span-2"><Input type="number" step="0.01" value={f.total_tax_sn_percent ?? ""} onChange={set("total_tax_sn_percent")} /></Field>
            <div className="sm:col-span-6">
              <p className="label">Retenções federais aplicáveis (R$)</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                {["irrf", "csll", "cp", "pis", "cofins"].map((k) => (
                  <Field key={k} label={k.toUpperCase()}><Input type="number" step="0.01" value={f.retentions?.[k] ?? ""} onChange={(e) => setF({ ...f, retentions: { ...f.retentions, [k]: e.target.value } })} /></Field>
                ))}
              </div>
            </div>
            <Field label="Informações adicionais" className="sm:col-span-6"><Textarea value={f.additional_info || ""} onChange={set("additional_info")} /></Field>
          </div>
        </Card>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>Cancelar</Button>
        <Button loading={busy} disabled={!f.tax_service_code_id || !Number(f.gross_amount) || (f.description || "").length < 5} onClick={save}>Salvar rascunho</Button>
      </div>
    </div>
  );
}

export function InvoicesPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [f, setF] = useState({ status: params.get("status") || "", start: "", end: "", q: "", environment: "" });
  const [page, setPage] = useState(1);
  const list = useGet<any>(["invoices"], "/fiscal/invoices", { ...f, page, status: f.status || undefined });
  return (
    <div>
      <PageHeader title="Notas fiscais emitidas" subtitle="Somente notas com status Autorizada foram confirmadas pelo serviço fiscal oficial." />
      <Card padded={false} actions={<>
        <Input className="!w-48" placeholder="Número, tomador, CPF/CNPJ" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        <Select className="!w-auto" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
          <option value="">Todas</option>
          {Object.entries(STATUS_TXT).map(([s, t]) => <option key={s} value={s}>{t}</option>)}
        </Select>
        <Select className="!w-auto" value={f.environment} onChange={(e) => setF({ ...f, environment: e.target.value })}><option value="">Ambos ambientes</option><option value="homologacao">Homologação</option><option value="producao">Produção</option></Select>
        <PeriodPicker start={f.start} end={f.end} onChange={(s, e) => setF({ ...f, start: s, end: e })} />
      </>} title="Notas">
        <DataTable rows={list.data?.items || []} onRowClick={(r) => navigate(`/fiscal/notas/${r.id}`)} empty={<Empty title="Nenhuma nota" />} columns={[
          { key: "nfse_number", label: "Número", render: (r) => r.nfse_number || <span className="text-slate-500 dark:text-slate-400">DPS {r.dps_number || "—"}</span> },
          { key: "competence_date", label: "Competência", render: (r) => date(r.competence_date) },
          { key: "taker_name", label: "Tomador", render: (r) => <span>{r.taker_name || "Não identificado"} <span className="text-xs text-slate-500">{r.taker_document ? doc(r.taker_document) : ""}</span></span> },
          { key: "gross_amount", label: "Valor", render: (r) => money(r.gross_amount) },
          { key: "environment", label: "Ambiente", render: (r) => <Badge color={r.environment === "producao" ? "blue" : "yellow"}>{r.environment === "producao" ? "Produção" : "Homologação"}</Badge> },
          { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
        ]} />
        <Pagination page={page} pageSize={50} total={list.data?.total || 0} onPage={setPage} />
      </Card>
    </div>
  );
}

const STATUS_TXT: Record<string, string> = {
  rascunho: "Rascunho", aguardando_transmissao: "Aguardando transmissão", transmitindo: "Transmitindo", autorizada: "Autorizada",
  rejeitada: "Rejeitada", cancelada: "Cancelada", substituida: "Substituída",
};

export function InvoiceDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const q = useGet<any>(["invoice", id], `/fiscal/invoices/${id}`);
  const [preview, setPreview] = useState<any>(null);
  const [editing, setEditing] = useState(false);
  const [substituting, setSubstituting] = useState(false);
  const [cancel, setCancel] = useState(false);
  const [cf, setCf] = useState({ reason_code: "1", reason: "" });
  const inv = q.data;
  const inval = [["invoice", id], ["invoices"], ["pending-billing"], ["dashboard"]];
  const transmit = useAction(() => post(`/fiscal/invoices/${id}/transmit`), { invalidate: inval, onDone: () => setPreview(null) });
  const reprocess = useAction(() => post(`/fiscal/invoices/${id}/reprocess`), { invalidate: inval });
  const refresh = useAction(() => post(`/fiscal/invoices/${id}/refresh`), { invalidate: inval });
  const danfse = useAction(() => post(`/fiscal/invoices/${id}/danfse`), { invalidate: inval });
  const doCancel = useAction(() => post(`/fiscal/invoices/${id}/cancel`, cf), { invalidate: inval, onDone: () => setCancel(false) });
  const discard = useAction(() => del(`/fiscal/invoices/${id}`), { invalidate: inval, onDone: () => navigate("/fiscal/notas") });
  if (q.isLoading) return <Loading />;
  if (!inv) return <Alert kind="danger">Nota não encontrada.</Alert>;
  if (editing || substituting) {
    const a = inv.taker_address || {};
    const init = { ...EMPTY, ...inv, taker_zip_code: a.zip_code || "", taker_street: a.street || "", taker_number: a.number || "", taker_complement: a.complement || "",
      taker_district: a.district || "", taker_ibge_code: a.ibge_code || "", retentions: { ...EMPTY.retentions, ...(inv.retentions || {}) },
      total_tax_sn_percent: inv.tax_info?.pTotTribSN || "", iss_rate: inv.iss_rate ?? "", incidence_ibge: inv.incidence_ibge || "" };
    return <InvoiceForm initial={init} invoiceId={editing ? inv.id : undefined} substituteOf={substituting ? inv.id : undefined}
      onCancel={() => { setEditing(false); setSubstituting(false); }} onSaved={(n) => { setEditing(false); setSubstituting(false); q.refetch(); navigate(`/fiscal/notas/${n.id}`); }} />;
  }
  return (
    <div>
      <button className="mb-3 flex items-center gap-1 text-sm text-slate-500 hover:text-brand-600" onClick={() => navigate("/fiscal/notas")}><ArrowLeft className="h-4 w-4" /> Notas</button>
      <PageHeader title={inv.nfse_number ? `NFS-e nº ${inv.nfse_number}` : `Nota — ${inv.status === "rascunho" ? "rascunho" : "DPS " + (inv.dps_number || "")}`}
        subtitle={`${inv.environment === "producao" ? "Produção" : "Homologação (produção restrita — sem validade jurídica)"} · competência ${date(inv.competence_date)}`}
        actions={<StatusBadge status={inv.status} />} />
      {inv.last_error && <div className="mb-4"><Alert kind={inv.status === "aguardando_transmissao" ? "warning" : "danger"} title="Retorno do serviço fiscal">{inv.last_error}</Alert></div>}
      {inv.status === "aguardando_transmissao" && <div className="mb-4"><Alert kind="warning">Esta nota NÃO foi confirmada como emitida. Use "Reprocessar": o sistema consulta a DPS no serviço oficial antes de qualquer reenvio, evitando duplicidade.</Alert></div>}
      <div className="mb-4 flex flex-wrap gap-2">
        {can("fiscal.issue") && ["rascunho", "rejeitada"].includes(inv.status) && <>
          <Button icon={<Send className="h-4 w-4" />} onClick={async () => { try { setPreview(await get(`/fiscal/invoices/${id}/preview`)); } catch (e) { toast.error(e); } }}>Prévia e transmissão</Button>
          <Button variant="secondary" onClick={() => setEditing(true)}>Editar</Button>
          <Button variant="ghost" loading={discard.isPending} onClick={() => discard.mutate(undefined)}>Descartar</Button>
        </>}
        {can("fiscal.issue") && ["aguardando_transmissao", "transmitindo"].includes(inv.status) && <Button loading={reprocess.isPending} onClick={() => reprocess.mutate(undefined)}>Reprocessar</Button>}
        {inv.status === "autorizada" && <>
          <Button variant="secondary" loading={refresh.isPending} onClick={() => refresh.mutate(undefined)}>Consultar situação</Button>
          {inv.danfse_file_id ? <Button variant="secondary" icon={<Download className="h-4 w-4" />} onClick={() => download(`/fiscal/invoices/${id}/danfse`).catch((e) => toast.error(e))}>DANFSe (PDF)</Button>
            : <Button variant="secondary" loading={danfse.isPending} onClick={() => danfse.mutate(undefined)}>Obter DANFSe</Button>}
          {can("fiscal.cancel") && <Button variant="secondary" onClick={() => setSubstituting(true)}>Substituir</Button>}
          {can("fiscal.cancel") && <Button variant="danger" onClick={() => setCancel(true)}>Cancelar NFS-e</Button>}
        </>}
        {inv.has_nfse_xml && <Button variant="ghost" icon={<Download className="h-4 w-4" />} onClick={() => download(`/fiscal/invoices/${id}/xml`, { kind: "nfse" }).catch((e) => toast.error(e))}>XML da NFS-e</Button>}
        {inv.has_dps_xml && <Button variant="ghost" icon={<Download className="h-4 w-4" />} onClick={() => download(`/fiscal/invoices/${id}/xml`, { kind: "dps" }).catch((e) => toast.error(e))}>XML da DPS</Button>}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Dados da nota" className="lg:col-span-2">
          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            <div><dt className="label">Tomador</dt><dd>{inv.taker_name || "Não identificado"}</dd></div>
            <div><dt className="label">CPF/CNPJ</dt><dd>{inv.taker_document ? doc(inv.taker_document) : "—"}</dd></div>
            <div><dt className="label">Código de serviço</dt><dd>{inv.national_code}{inv.municipal_code ? ` / ${inv.municipal_code}` : ""}</dd></div>
            <div className="sm:col-span-3"><dt className="label">Descrição</dt><dd className="whitespace-pre-wrap">{inv.description}</dd></div>
            <div><dt className="label">Valor do serviço</dt><dd>{money(inv.gross_amount)}</dd></div>
            <div><dt className="label">Descontos</dt><dd>{money(Number(inv.unconditional_discount) + Number(inv.conditional_discount))}</dd></div>
            <div><dt className="label">ISS estimado</dt><dd>{money(inv.iss_amount)} {inv.iss_withheld && <Badge color="yellow">retido</Badge>}</dd></div>
            <div><dt className="label">Chave de acesso</dt><dd className="break-all text-xs">{inv.access_key || "—"}</dd></div>
            <div><dt className="label">Nº DFS-e / protocolo</dt><dd>{inv.protocol || "—"}</dd></div>
            <div><dt className="label">Autorizada em</dt><dd>{dateTime(inv.authorized_at)}</dd></div>
            {inv.access_key && inv.query_url && <div className="sm:col-span-3"><dt className="label">Consulta pública</dt><dd><a className="text-brand-600" href={inv.query_url} target="_blank" rel="noreferrer">{inv.query_url}</a> (informe a chave de acesso)</dd></div>}
            {inv.cancel_reason && <div className="sm:col-span-3"><dt className="label">Motivo do cancelamento</dt><dd>{inv.cancel_reason}</dd></div>}
          </dl>
        </Card>
        <Card title="Histórico de transmissão e eventos">
          <ol className="space-y-2 text-sm">
            {inv.events.map((e: any, i: number) => (
              <li key={i} className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/50">
                <p className="flex items-center justify-between font-medium"><span className="capitalize">{e.type.replace("_", " ")}</span><Badge color={e.success ? "green" : "red"}>{e.success ? "ok" : "falha"}</Badge></p>
                <p className="text-xs text-slate-500">{dateTime(e.created_at)} {e.http_status ? `· HTTP ${e.http_status}` : ""}</p>
                {e.message && <p className="mt-1 text-xs">{e.message}</p>}
              </li>
            ))}
          </ol>
        </Card>
      </div>
      <Modal open={!!preview} onClose={() => setPreview(null)} title="Prévia da transmissão" size="xl"
        footer={<><Button variant="secondary" onClick={() => setPreview(null)}>Voltar</Button>
          <Button loading={transmit.isPending} disabled={!preview?.xml} onClick={() => transmit.mutate(undefined)}>Transmitir para {preview?.environment === "producao" ? "PRODUÇÃO" : "homologação"}</Button></>}>
        {preview && (
          <div className="space-y-3">
            {preview.environment === "producao" ? <Alert kind="warning">Ambiente de PRODUÇÃO: a nota terá validade jurídica.</Alert> : <Alert kind="info">Ambiente de homologação (produção restrita): para testes, sem validade jurídica.</Alert>}
            {preview.error && <Alert kind="danger">{preview.error}</Alert>}
            {preview.xsd_available === false && <Alert kind="info">Esquemas XSD oficiais não instalados: a validação será feita pelo serviço fiscal. Em produção a instalação é obrigatória.</Alert>}
            {preview.xsd_errors?.length > 0 && <Alert kind="danger" title="Erros de validação (XSD)">{preview.xsd_errors.join(" · ")}</Alert>}
            <Readiness />
            {preview.xml && <><p className="text-xs text-slate-500">{preview.note} — Id: {preview.dps_id}</p>
              <pre className="max-h-80 overflow-auto rounded-xl bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100">{preview.xml.replace(/></g, ">\n<")}</pre></>}
          </div>
        )}
      </Modal>
      <Modal open={cancel} onClose={() => setCancel(false)} title="Cancelar NFS-e" size="sm"
        footer={<Button variant="danger" loading={doCancel.isPending} disabled={cf.reason.length < 15} onClick={() => doCancel.mutate(undefined)}>Enviar pedido de cancelamento</Button>}>
        <div className="space-y-3">
          <Field label="Motivo"><Select value={cf.reason_code} onChange={(e) => setCf({ ...cf, reason_code: e.target.value })}><option value="1">Erro na emissão</option><option value="2">Serviço não prestado</option><option value="9">Outros</option></Select></Field>
          <Field label="Justificativa (mínimo 15 caracteres)" required><Textarea value={cf.reason} onChange={(e) => setCf({ ...cf, reason: e.target.value })} /></Field>
          <p className="text-xs text-slate-500">O cancelamento só é registrado após homologação do evento pelo serviço oficial. Prazos e condições dependem do município.</p>
        </div>
      </Modal>
    </div>
  );
}
