import { FileUp, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CustomerPicker } from "../components/shared";
import { Alert, Badge, Button, Card, Checkbox, ConfirmButton, DataTable, Drawer, Empty, Field, Input, Modal, PageHeader, StatusBadge, Tabs, Textarea, useToast } from "../components/ui";
import { del, download, get, post, upload } from "../lib/api";
import { useAuth } from "../lib/auth";
import { addDays, date, dateTime, isoDay } from "../lib/format";
import { useAction, useGet } from "../lib/hooks";

const REGIONS = ["Cervical", "Ombros", "Costas (superior)", "Lombar", "Braços", "Mãos", "Quadril", "Pernas", "Pés", "Rosto", "Abdômen"];

export default function Treatments() {
  const [params] = useSearchParams();
  const [customer, setCustomer] = useState<any>(null);
  const [tab, setTab] = useState("atendimentos");
  const [openTreatment, setOpenTreatment] = useState<string | null>(null);
  const [start, setStart] = useState(addDays(isoDay(), -30));

  useEffect(() => {
    const cid = params.get("cliente");
    if (cid) get(`/customers/${cid}`).then((c) => setCustomer({ id: c.id, full_name: c.full_name })).catch(() => undefined);
  }, [params]);
  const list = useGet<any[]>(["treatments"], "/clinical/treatments", customer ? { customer_id: customer.id } : { start, end: isoDay() });
  useEffect(() => {
    const appt = params.get("agendamento");
    if (appt && list.data) {
      const t = list.data.find((x) => x.appointment_id === appt);
      if (t) setOpenTreatment(t.id);
    }
  }, [params, list.data]);

  return (
    <div>
      <PageHeader title="Atendimentos e anamnese" subtitle="Dados de saúde protegidos: criptografados, com acesso restrito e registrado em auditoria." />
      <Alert kind="info" title="Registro, não diagnóstico">O sistema apenas registra o que foi relatado pelo cliente e o que foi realizado. Não gera diagnósticos nem prescrições.</Alert>
      <div className="my-4 grid gap-3 sm:grid-cols-3">
        <Field label="Cliente" className="sm:col-span-2"><CustomerPicker value={customer} onChange={setCustomer} allowCreate={false} /></Field>
        {!customer && <Field label="Atendimentos desde"><Input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>}
      </div>
      {customer ? (
        <>
          <Tabs value={tab} onChange={setTab} tabs={[{ key: "atendimentos", label: "Atendimentos" }, { key: "anamnese", label: "Anamnese" }, { key: "documentos", label: "Documentos" }]} />
          {tab === "atendimentos" && <TreatmentList rows={list.data || []} onOpen={setOpenTreatment} />}
          {tab === "anamnese" && <HealthRecords customer={customer} />}
          {tab === "documentos" && <Documents customer={customer} />}
        </>
      ) : (
        <TreatmentList rows={list.data || []} onOpen={setOpenTreatment} showCustomer />
      )}
      {openTreatment && <TreatmentDrawer id={openTreatment} onClose={() => setOpenTreatment(null)} />}
    </div>
  );
}

function TreatmentList({ rows, onOpen, showCustomer }: { rows: any[]; onOpen: (id: string) => void; showCustomer?: boolean }) {
  return (
    <Card padded={false}>
      <DataTable rows={rows} onRowClick={(r) => onOpen(r.id)} empty={<Empty title="Nenhum atendimento" text="Atendimentos são criados ao iniciar ou finalizar um agendamento na Agenda." />}
        columns={[
          { key: "started_at", label: "Data", render: (r) => dateTime(r.started_at) },
          ...(showCustomer ? [{ key: "customer_name", label: "Cliente" }] : []),
          { key: "service", label: "Serviço" },
          { key: "professional", label: "Profissional" },
          { key: "records", label: "Fichas", render: (r: any) => (r.records ? <Badge color="green">{r.records}</Badge> : <Badge color="yellow">pendente</Badge>) },
          { key: "status", label: "Situação", render: (r: any) => <StatusBadge status={r.status === "em_andamento" ? "em_atendimento" : "concluido"} /> },
        ]} />
    </Card>
  );
}

function TreatmentDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useAuth();
  const q = useGet<any>(["treatment", id], `/clinical/treatments/${id}`);
  const [f, setF] = useState({ technique: "", duration_minutes: "", products: "", notes: "", evolution: "", recommendations: "", next_return_date: "" });
  const save = useAction(() => post(`/clinical/treatments/${id}/records`, {
    ...f, duration_minutes: f.duration_minutes ? Number(f.duration_minutes) : null, next_return_date: f.next_return_date || null,
    products: f.products || null, notes: f.notes || null, evolution: f.evolution || null, recommendations: f.recommendations || null,
  }), { success: "Ficha registrada.", invalidate: [["treatment", id], ["treatments"]], onDone: () => setF({ technique: "", duration_minutes: "", products: "", notes: "", evolution: "", recommendations: "", next_return_date: "" }) });
  const t = q.data?.treatment;
  return (
    <Drawer open onClose={onClose} title="Ficha de atendimento">
      {!t ? <p className="text-sm text-slate-500">Carregando...</p> : (
        <div className="space-y-4">
          <div>
            <p className="text-lg font-semibold">{t.customer_name}</p>
            <p className="text-sm text-slate-500">{t.service} · {t.professional} · {dateTime(t.started_at)}</p>
          </div>
          {q.data.records.length === 0 ? <p className="text-sm text-slate-500">Nenhuma ficha registrada para este atendimento.</p> : (
            <ol className="space-y-3">
              {q.data.records.map((r: any) => (
                <li key={r.id} className="rounded-xl border border-slate-100 p-3 text-sm dark:border-slate-800">
                  <p className="text-xs text-slate-500">{dateTime(r.created_at)} {r.duration_minutes ? `· ${r.duration_minutes} min` : ""}</p>
                  <p className="mt-1"><b>Técnica:</b> {r.technique}</p>
                  {r.products && <p><b>Produtos:</b> {r.products}</p>}
                  {r.evolution && <p><b>Evolução relatada:</b> {r.evolution}</p>}
                  {r.recommendations && <p><b>Recomendações de retorno:</b> {r.recommendations}</p>}
                  {r.notes && <p className="whitespace-pre-wrap"><b>Observações:</b> {r.notes}</p>}
                  {r.next_return_date && <p><b>Retorno sugerido:</b> {date(r.next_return_date)}</p>}
                </li>
              ))}
            </ol>
          )}
          {can("clinical.write") && (
            <div className="space-y-3 rounded-xl bg-slate-50 p-3 dark:bg-slate-800/50">
              <p className="text-sm font-semibold">Registrar ficha</p>
              <Field label="Técnica utilizada" required><Input value={f.technique} onChange={(e) => setF({ ...f, technique: e.target.value })} /></Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Duração (min)"><Input type="number" value={f.duration_minutes} onChange={(e) => setF({ ...f, duration_minutes: e.target.value })} /></Field>
                <Field label="Retorno sugerido"><Input type="date" value={f.next_return_date} onChange={(e) => setF({ ...f, next_return_date: e.target.value })} /></Field>
              </div>
              <Field label="Produtos utilizados"><Input value={f.products} onChange={(e) => setF({ ...f, products: e.target.value })} /></Field>
              <Field label="Evolução relatada pelo cliente"><Textarea value={f.evolution} onChange={(e) => setF({ ...f, evolution: e.target.value })} /></Field>
              <Field label="Recomendações de retorno"><Textarea value={f.recommendations} onChange={(e) => setF({ ...f, recommendations: e.target.value })} /></Field>
              <Field label="Observações"><Textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
              <Button loading={save.isPending} disabled={f.technique.length < 2} onClick={() => save.mutate(undefined)}>Salvar ficha</Button>
              <p className="text-xs text-slate-500">Fichas não são editáveis (rastreabilidade): para corrigir, registre uma nova ficha complementar.</p>
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
}

function HealthRecords({ customer }: { customer: any }) {
  const { can } = useAuth();
  const q = useGet<any[]>(["health", customer.id], `/clinical/customers/${customer.id}/health-records`);
  const [open, setOpen] = useState(false);
  const latest = q.data?.[0];
  return (
    <div className="space-y-4">
      <div className="flex justify-end">{can("clinical.write") && <Button onClick={() => setOpen(true)}>{latest ? "Atualizar anamnese (nova versão)" : "Registrar anamnese"}</Button>}</div>
      {!q.data?.length ? <Empty title="Sem anamnese registrada" /> : q.data.map((r, i) => (
        <Card key={r.id} title={<span>Versão {r.version} {i === 0 && <Badge color="green" className="ml-2">vigente</Badge>}</span>}
          actions={<span className="flex items-center gap-1 text-xs text-slate-500"><ShieldCheck className="h-4 w-4 text-emerald-600" /> Aceite de {r.consent_accepted_name} em {dateTime(r.consent_accepted_at)}</span>}>
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            {[["Objetivo informado", r.objective], ["Histórico de saúde informado", r.health_history], ["Alergias relatadas", r.allergies],
              ["Sensibilidades", r.sensitivities], ["Restrições relatadas", r.restrictions], ["Preferências", r.preferences], ["Observações", r.notes]].map(([k, v]) => (
              <div key={k as string}><dt className="label">{k}</dt><dd className="whitespace-pre-wrap">{(v as string) || "—"}</dd></div>
            ))}
            <div><dt className="label">Regiões de interesse</dt><dd>{(r.body_regions || []).join(", ") || "—"}</dd></div>
          </dl>
          <p className="mt-3 break-all text-xs text-slate-500 dark:text-slate-400">Comprovante de integridade do aceite (SHA-256): {r.consent_hash}</p>
        </Card>
      ))}
      {open && <HealthForm customer={customer} latest={latest} onClose={() => { setOpen(false); q.refetch(); }} />}
    </div>
  );
}

function HealthForm({ customer, latest, onClose }: { customer: any; latest?: any; onClose: () => void }) {
  const toast = useToast();
  const consentText = useGet<any>(["lgpd-params"], "/settings/params/lgpd");
  const [f, setF] = useState<any>({
    objective: latest?.objective || "", health_history: latest?.health_history || "", allergies: latest?.allergies || "",
    sensitivities: latest?.sensitivities || "", restrictions: latest?.restrictions || "", preferences: latest?.preferences || "",
    notes: latest?.notes || "", body_regions: latest?.body_regions || [], consent_given: false, consent_name: customer.full_name, consent_document: "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal open onClose={onClose} title="Ficha de anamnese" size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button>
        <Button loading={busy} disabled={!f.consent_given || f.consent_name.length < 3} onClick={async () => {
          setBusy(true);
          try {
            const r = await post(`/clinical/customers/${customer.id}/health-records`, { ...f, consent_document: f.consent_document || null });
            toast.success(r.message);
            onClose();
          } catch (e) { toast.error(e); } finally { setBusy(false); }
        }}>Salvar com aceite</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Objetivo informado pelo cliente" className="sm:col-span-2"><Textarea value={f.objective} onChange={set("objective")} /></Field>
        <Field label="Histórico de saúde informado"><Textarea value={f.health_history} onChange={set("health_history")} /></Field>
        <Field label="Alergias relatadas"><Textarea value={f.allergies} onChange={set("allergies")} /></Field>
        <Field label="Sensibilidades"><Textarea value={f.sensitivities} onChange={set("sensitivities")} /></Field>
        <Field label="Restrições relatadas"><Textarea value={f.restrictions} onChange={set("restrictions")} /></Field>
        <div className="sm:col-span-2">
          <p className="label">Regiões corporais de interesse</p>
          <div className="flex flex-wrap gap-1.5">
            {REGIONS.map((r) => {
              const on = f.body_regions.includes(r);
              return <button key={r} type="button" onClick={() => setF({ ...f, body_regions: on ? f.body_regions.filter((x: string) => x !== r) : [...f.body_regions, r] })}
                className={`rounded-full border px-2.5 py-1 text-xs ${on ? "border-brand-600 bg-brand-600 text-white" : "border-slate-200 dark:border-slate-700"}`}>{r}</button>;
            })}
          </div>
        </div>
        <Field label="Preferências"><Textarea value={f.preferences} onChange={set("preferences")} /></Field>
        <Field label="Observações"><Textarea value={f.notes} onChange={set("notes")} /></Field>
        <div className="space-y-2 rounded-xl border border-brand-100 bg-brand-50 p-3 text-sm dark:border-brand-900 dark:bg-brand-900/20 sm:col-span-2">
          <p className="font-semibold">Consentimento informado</p>
          <p className="text-[13px] leading-relaxed">{consentText.data?.["lgpd.consent_text"]}</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Nome de quem aceita" required><Input value={f.consent_name} onChange={set("consent_name")} /></Field>
            <Field label="CPF (opcional)"><Input value={f.consent_document} onChange={set("consent_document")} /></Field>
          </div>
          <Checkbox label="O cliente leu e aceitou o termo acima (aceite eletrônico com data, hora e responsável registrados)." checked={f.consent_given} onChange={(v) => setF({ ...f, consent_given: v })} />
        </div>
      </div>
    </Modal>
  );
}

function Documents({ customer }: { customer: any }) {
  const { can } = useAuth();
  const toast = useToast();
  const q = useGet<any[]>(["clinical-files", customer.id], `/clinical/customers/${customer.id}/files`);
  const [file, setFile] = useState<File | null>(null);
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const remove = useAction((id: string) => del(`/clinical/files/${id}`), { invalidate: [["clinical-files", customer.id]] });
  return (
    <Card title="Documentos anexos (criptografados)">
      {can("clinical.write") && (
        <div className="mb-4 flex flex-wrap items-end gap-2">
          <Field label="Arquivo (PDF ou imagem, até 15 MB)"><Input type="file" accept=".pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] || null)} /></Field>
          <Field label="Descrição"><Input value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
          <Button icon={<FileUp className="h-4 w-4" />} loading={busy} disabled={!file} onClick={async () => {
            if (!file) return;
            setBusy(true);
            try {
              const fd = new FormData();
              fd.append("file", file);
              if (desc) fd.append("description", desc);
              await upload(`/clinical/customers/${customer.id}/files`, fd);
              toast.success("Documento anexado.");
              setFile(null); setDesc("");
              q.refetch();
            } catch (e) { toast.error(e); } finally { setBusy(false); }
          }}>Anexar</Button>
        </div>
      )}
      <DataTable rows={q.data || []} empty={<Empty title="Nenhum documento" />} columns={[
        { key: "name", label: "Arquivo" },
        { key: "description", label: "Descrição", render: (r) => r.description || "—" },
        { key: "created_at", label: "Enviado em", render: (r) => dateTime(r.created_at) },
        { key: "a", label: "", render: (r) => (
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="ghost" onClick={() => download(`/clinical/files/${r.id}`).catch((e) => toast.error(e))}>Baixar</Button>
            {can("clinical.write") && <ConfirmButton size="sm" message="Remover este documento definitivamente?" onConfirm={() => remove.mutateAsync(r.id)}>Remover</ConfirmButton>}
          </div>
        ) },
      ]} />
    </Card>
  );
}
