import { DatabaseBackup, Download, ImageUp, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Logo } from "../components/Logo";
import { CrudList } from "../components/shared";
import { Alert, Badge, Button, Card, Checkbox, DataTable, Empty, Field, Input, Modal, PageHeader, Select, Tabs, Textarea, useToast } from "../components/ui";
import { del, download, post, put, upload } from "../lib/api";
import { useAuth } from "../lib/auth";
import { date, dateTime, money, WEEKDAYS } from "../lib/format";
import { useAction, useGet } from "../lib/hooks";

export default function SettingsPage() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const tabs = [
    ...(can("settings.manage") ? [{ key: "clinica", label: "Clínica" }] : []),
    ...(can("agenda.settings") || can("settings.manage") ? [{ key: "agenda", label: "Agenda, salas e profissionais" }] : []),
    ...(can("finance.settings") ? [{ key: "financeiro", label: "Financeiro" }] : []),
    ...(can("settings.manage") ? [{ key: "relacionamento", label: "CRM e pacotes" }, { key: "seguranca", label: "Segurança e LGPD" }] : []),
    ...(can("backups.manage") ? [{ key: "backups", label: "Backups" }] : []),
    { key: "integracoes", label: "Integrações" },
  ];
  const [tab, setTab] = useState(params.get("aba") || tabs[0].key);
  return (
    <div>
      <PageHeader title="Configurações" subtitle="Tudo configurável pela interface, sem alteração de código." />
      <Tabs value={tab} onChange={setTab} tabs={tabs} />
      {tab === "clinica" && <Clinic />}
      {tab === "agenda" && <AgendaSettings />}
      {tab === "financeiro" && <FinanceSettings />}
      {tab === "relacionamento" && <Params group="crm" title="CRM" extra="packages" />}
      {tab === "seguranca" && <Params group="security" title="Segurança" extra="lgpd" />}
      {tab === "backups" && <Backups />}
      {tab === "integracoes" && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card title="WhatsApp Business Cloud API"><p className="mb-3 text-sm text-slate-500">Credenciais, webhook, templates e automações.</p><Button variant="secondary" onClick={() => navigate("/whatsapp")}>Abrir configuração do WhatsApp</Button></Card>
          <Card title="NFS-e e certificado digital"><p className="mb-3 text-sm text-slate-500">Cadastro fiscal, certificado A1, códigos de serviço e ambiente de emissão.</p><Button variant="secondary" onClick={() => navigate("/fiscal/configuracoes")}>Abrir cadastro fiscal</Button></Card>
        </div>
      )}
    </div>
  );
}

function Clinic() {
  const toast = useToast();
  const { reload } = useAuth();
  const q = useGet<any>(["clinic"], "/settings/clinic");
  const [f, setF] = useState<any>(null);
  const [v, setV] = useState(0);
  useEffect(() => { if (q.data) setF(q.data); }, [q.data]);
  const save = useAction(() => {
    const keys = ["name", "trade_name", "document", "phone", "whatsapp", "email", "website", "zip_code", "street", "number", "complement", "district", "city", "state"];
    return put("/settings/clinic", Object.fromEntries(keys.map((k) => [k, f[k] === "" ? null : f[k]])));
  }, { success: "Dados da clínica salvos.", invalidate: [["clinic"]] });
  const removeLogo = useAction(() => del("/settings/clinic/logo"), { invalidate: [["clinic"]], onDone: () => { setV(v + 1); reload(); } });
  if (!f) return null;
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Logotipo">
        <div className="flex flex-col items-center gap-3">
          <div className="flex h-40 w-full items-center justify-center rounded-xl bg-slate-50 dark:bg-slate-800/50" key={v}><Logo hasLogo={f.has_logo} className="!h-36" /></div>
          <div className="flex gap-2">
            <Button variant="secondary" icon={<ImageUp className="h-4 w-4" />} onClick={() => {
              const input = document.createElement("input");
              input.type = "file"; input.accept = "image/png,image/jpeg,image/webp";
              input.onchange = async () => {
                const file = input.files?.[0];
                if (!file) return;
                const fd = new FormData(); fd.append("file", file);
                try { await upload("/settings/clinic/logo", fd); toast.success("Logotipo atualizado."); q.refetch(); setV(v + 1); reload(); } catch (e) { toast.error(e); }
              };
              input.click();
            }}>Enviar logotipo</Button>
            {f.has_logo && <Button variant="ghost" onClick={() => removeLogo.mutate(undefined)}>Remover</Button>}
          </div>
          <p className="text-center text-xs text-slate-500">PNG, JPEG ou WEBP até 2 MB. Usado no login, no menu e nos relatórios em PDF.</p>
        </div>
      </Card>
      <Card title="Dados da clínica" className="lg:col-span-2">
        <div className="grid gap-3 sm:grid-cols-6">
          <Field label="Nome" required className="sm:col-span-3"><Input value={f.name || ""} onChange={set("name")} /></Field>
          <Field label="Nome fantasia" className="sm:col-span-3"><Input value={f.trade_name || ""} onChange={set("trade_name")} /></Field>
          <Field label="CNPJ/CPF" className="sm:col-span-2"><Input value={f.document || ""} onChange={set("document")} /></Field>
          <Field label="Telefone" className="sm:col-span-2"><Input value={f.phone || ""} onChange={set("phone")} /></Field>
          <Field label="WhatsApp" className="sm:col-span-2"><Input value={f.whatsapp || ""} onChange={set("whatsapp")} /></Field>
          <Field label="E-mail" className="sm:col-span-3"><Input value={f.email || ""} onChange={set("email")} /></Field>
          <Field label="Site" className="sm:col-span-3"><Input value={f.website || ""} onChange={set("website")} /></Field>
          <Field label="CEP" className="sm:col-span-2"><Input value={f.zip_code || ""} onChange={set("zip_code")} /></Field>
          <Field label="Endereço" className="sm:col-span-3"><Input value={f.street || ""} onChange={set("street")} /></Field>
          <Field label="Número" className="sm:col-span-1"><Input value={f.number || ""} onChange={set("number")} /></Field>
          <Field label="Complemento" className="sm:col-span-2"><Input value={f.complement || ""} onChange={set("complement")} /></Field>
          <Field label="Bairro" className="sm:col-span-2"><Input value={f.district || ""} onChange={set("district")} /></Field>
          <Field label="Cidade" className="sm:col-span-1"><Input value={f.city || ""} onChange={set("city")} /></Field>
          <Field label="UF" className="sm:col-span-1"><Input maxLength={2} value={f.state || ""} onChange={set("state")} /></Field>
        </div>
        <div className="mt-4 flex justify-end"><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Salvar</Button></div>
      </Card>
    </div>
  );
}

function AgendaSettings() {
  const hours = useGet<any[]>(["business-hours"], "/settings/business-hours");
  const [rows, setRows] = useState<any[]>([]);
  const [availability, setAvailability] = useState<any>(null);
  useEffect(() => {
    if (hours.data) setRows(Array.from({ length: 7 }, (_, i) => hours.data!.find((h) => h.weekday === i) || { weekday: i, is_open: false, open_time: null, close_time: null, break_start: null, break_end: null }));
  }, [hours.data]);
  const save = useAction(() => put("/settings/business-hours", rows.map((r) => ({ ...r, open_time: r.is_open ? r.open_time : null, close_time: r.is_open ? r.close_time : null,
    break_start: r.is_open && r.break_start ? r.break_start : null, break_end: r.is_open && r.break_end ? r.break_end : null }))), { success: "Horários salvos.", invalidate: [["business-hours"]] });
  const upd = (i: number, k: string, v: any) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Dias e horários de funcionamento" className="lg:col-span-2">
          <div className="space-y-2">
            {rows.map((r, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 border-b border-slate-100 pb-2 last:border-0 dark:border-slate-800">
                <div className="w-28"><Checkbox label={WEEKDAYS[i]} checked={r.is_open} onChange={(v) => upd(i, "is_open", v)} /></div>
                <Input type="time" className="!w-[7.5rem]" disabled={!r.is_open} value={(r.open_time || "").slice(0, 5)} onChange={(e) => upd(i, "open_time", e.target.value)} aria-label="Abertura" />
                <span className="text-xs text-slate-500">às</span>
                <Input type="time" className="!w-[7.5rem]" disabled={!r.is_open} value={(r.close_time || "").slice(0, 5)} onChange={(e) => upd(i, "close_time", e.target.value)} aria-label="Fechamento" />
                <span className="text-xs text-slate-500">intervalo</span>
                <Input type="time" className="!w-[7.5rem]" disabled={!r.is_open} value={(r.break_start || "").slice(0, 5)} onChange={(e) => upd(i, "break_start", e.target.value)} aria-label="Início do intervalo" />
                <span className="text-xs text-slate-500">–</span>
                <Input type="time" className="!w-[7.5rem]" disabled={!r.is_open} value={(r.break_end || "").slice(0, 5)} onChange={(e) => upd(i, "break_end", e.target.value)} aria-label="Fim do intervalo" />
              </div>
            ))}
          </div>
          <div className="mt-4 flex justify-end"><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Salvar horários</Button></div>
        </Card>
        <Params group="agenda" title="Parâmetros da agenda" compact />
      </div>
      <CrudList title="Profissionais" path="/settings/professionals" queryKey="professionals" canWrite
        columns={[{ key: "name", label: "Nome", render: (r) => <span className="flex items-center gap-2"><span className="h-3 w-3 rounded-full" style={{ background: r.color }} />{r.name}</span> },
          { key: "registration", label: "Registro", render: (r) => r.registration || "—" }, { key: "specialties", label: "Especialidades", render: (r) => r.specialties || "—" },
          { key: "is_active", label: "Ativo", render: (r) => (r.is_active ? "Sim" : "Não") },
          { key: "disp", label: "", render: (r) => <Button size="sm" variant="ghost" onClick={() => setAvailability(r)}>Disponibilidade</Button> }]}
        fields={[{ key: "name", label: "Nome", required: true, span: 4 }, { key: "color", label: "Cor na agenda", type: "color", defaultValue: "#2563EB", span: 2 },
          { key: "cpf", label: "CPF", span: 2 }, { key: "phone", label: "Telefone", span: 2 }, { key: "email", label: "E-mail", span: 2 },
          { key: "registration", label: "Registro profissional", span: 3 }, { key: "specialties", label: "Técnicas/especialidades", span: 3 },
          { key: "is_active", label: "Ativo", type: "checkbox", defaultValue: true, span: 3 }]} />
      <div className="grid gap-4 lg:grid-cols-2">
        <CrudList title="Salas" path="/settings/rooms" queryKey="rooms" canWrite
          columns={[{ key: "name", label: "Sala" }, { key: "description", label: "Descrição", render: (r) => r.description || "—" }, { key: "is_active", label: "Ativa", render: (r) => (r.is_active ? "Sim" : "Não") }]}
          fields={[{ key: "name", label: "Nome", required: true, span: 4 }, { key: "color", label: "Cor", type: "color", defaultValue: "#8B5CF6", span: 2 },
            { key: "description", label: "Descrição", span: 6 }, { key: "is_active", label: "Ativa", type: "checkbox", defaultValue: true }]} />
        <CrudList title="Feriados e dias sem expediente" path="/settings/holidays" queryKey="holidays" canWrite
          columns={[{ key: "date", label: "Data", render: (r) => date(r.date) }, { key: "name", label: "Descrição" }, { key: "recurring", label: "Anual", render: (r) => (r.recurring ? "Sim" : "Não") }]}
          fields={[{ key: "date", label: "Data", type: "date", required: true, span: 2 }, { key: "name", label: "Descrição", required: true, span: 4 },
            { key: "recurring", label: "Repete todo ano", type: "checkbox", span: 3 }]} />
      </div>
      {availability && <AvailabilityForm prof={availability} onClose={() => setAvailability(null)} />}
    </div>
  );
}

function AvailabilityForm({ prof, onClose }: { prof: any; onClose: () => void }) {
  const q = useGet<any[]>(["availability", prof.id], `/settings/professionals/${prof.id}/availability`);
  const [rows, setRows] = useState<any[] | null>(null);
  const items = rows ?? (q.data || []).map((r) => ({ ...r, start_time: r.start_time.slice(0, 5), end_time: r.end_time.slice(0, 5) }));
  const save = useAction(() => put(`/settings/professionals/${prof.id}/availability`, items), { success: "Disponibilidade salva.", onDone: onClose });
  return (
    <Modal open onClose={onClose} title={`Disponibilidade — ${prof.name}`} footer={<Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Salvar</Button>}>
      <Alert kind="info">Sem faixas cadastradas, o profissional segue o horário de funcionamento da clínica.</Alert>
      <div className="mt-3 space-y-2">
        {items.map((r, i) => (
          <div key={i} className="grid grid-cols-2 items-center gap-2 border-b border-slate-100 pb-2 last:border-0 dark:border-slate-800 sm:grid-cols-4 sm:border-0 sm:pb-0">
            <Select value={r.weekday} onChange={(e) => setRows(items.map((x, j) => (j === i ? { ...x, weekday: Number(e.target.value) } : x)))}>{WEEKDAYS.map((d, k) => <option key={k} value={k}>{d}</option>)}</Select>
            <Input type="time" value={r.start_time} onChange={(e) => setRows(items.map((x, j) => (j === i ? { ...x, start_time: e.target.value } : x)))} />
            <Input type="time" value={r.end_time} onChange={(e) => setRows(items.map((x, j) => (j === i ? { ...x, end_time: e.target.value } : x)))} />
            <Button size="sm" variant="ghost" onClick={() => setRows(items.filter((_, j) => j !== i))}>Remover</Button>
          </div>
        ))}
        <Button size="sm" variant="secondary" onClick={() => setRows([...items, { weekday: 0, start_time: "08:00", end_time: "12:00" }])}>Adicionar faixa</Button>
      </div>
    </Modal>
  );
}

function FinanceSettings() {
  const accounts = useGet<any[]>(["accounts"], "/settings/financial-accounts");
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <CrudList title="Contas financeiras" path="/settings/financial-accounts" queryKey="accounts" canWrite
          columns={[{ key: "name", label: "Conta" }, { key: "kind", label: "Tipo" }, { key: "opening_balance", label: "Saldo inicial", render: (r) => money(r.opening_balance) }]}
          transform={(b) => ({ ...b, opening_balance: String(b.opening_balance ?? 0) })}
          fields={[{ key: "name", label: "Nome", required: true, span: 3 },
            { key: "kind", label: "Tipo", type: "select", options: [{ value: "caixa", label: "Caixa" }, { value: "banco", label: "Banco" }, { value: "carteira", label: "Carteira digital" }, { value: "outro", label: "Outro" }], required: true, defaultValue: "banco", span: 3 },
            { key: "bank_name", label: "Banco", span: 2 }, { key: "agency", label: "Agência", span: 2 }, { key: "account_number", label: "Conta", span: 2 },
            { key: "opening_balance", label: "Saldo inicial", type: "money", defaultValue: "0", span: 3 }, { key: "opening_date", label: "Data do saldo inicial", type: "date", span: 3 },
            { key: "is_active", label: "Ativa", type: "checkbox", defaultValue: true }]} />
        <CrudList title="Formas de pagamento" path="/settings/payment-methods" queryKey="payment-methods" canWrite
          columns={[{ key: "name", label: "Forma" }, { key: "fee_percent", label: "Taxa %" }, { key: "settlement_days", label: "Prazo (dias)" }, { key: "is_active", label: "Ativa", render: (r) => (r.is_active ? "Sim" : "Não") }]}
          transform={(b) => ({ ...b, fee_percent: String(b.fee_percent ?? 0), settlement_days: Number(b.settlement_days ?? 0) })}
          fields={[{ key: "name", label: "Nome", required: true, span: 3 }, { key: "code", label: "Código (minúsculas, sem espaço)", required: true, span: 3 },
            { key: "fee_percent", label: "Taxa (%)", type: "money", defaultValue: "0", span: 2 }, { key: "settlement_days", label: "Prazo de recebimento (dias)", type: "number", defaultValue: 0, span: 2 },
            { key: "is_active", label: "Ativa", type: "checkbox", defaultValue: true, span: 2 }]} />
        <CrudList title="Categorias financeiras" path="/settings/financial-categories" queryKey="fin-cats" canWrite
          columns={[{ key: "name", label: "Categoria" }, { key: "kind", label: "Tipo", render: (r) => <Badge color={r.kind === "receita" ? "green" : "pink"}>{r.kind}</Badge> }, { key: "is_active", label: "Ativa", render: (r) => (r.is_active ? "Sim" : "Não") }]}
          fields={[{ key: "name", label: "Nome", required: true, span: 4 }, { key: "kind", label: "Tipo", type: "select", options: [{ value: "receita", label: "Receita" }, { value: "despesa", label: "Despesa" }], required: true, defaultValue: "despesa", span: 2 },
            { key: "is_active", label: "Ativa", type: "checkbox", defaultValue: true }]} />
        <CrudList title="Centros de custo" path="/settings/cost-centers" queryKey="cost-centers" canWrite
          columns={[{ key: "name", label: "Centro de custo" }, { key: "description", label: "Descrição", render: (r) => r.description || "—" }]}
          fields={[{ key: "name", label: "Nome", required: true, span: 3 }, { key: "description", label: "Descrição", span: 3 }, { key: "is_active", label: "Ativo", type: "checkbox", defaultValue: true }]} />
      </div>
      <Params group="finance" title="Parâmetros financeiros" accounts={accounts.data || []} />
    </div>
  );
}

const PARAM_LABELS: Record<string, { label: string; hint?: string }> = {
  "agenda.buffer_minutes": { label: "Intervalo padrão entre sessões (min)", hint: "Somado ao intervalo do serviço, prevalece o maior" },
  "agenda.slot_minutes": { label: "Grade de horários livres (min)" },
  "agenda.allow_overbooking_rooms": { label: "Permitir encaixe em salas (não utilizado)" },
  "crm.return_alert_days": { label: "Alertas de retorno (dias, separados por vírgula)" },
  "crm.inactive_after_days": { label: "Cliente inativo após (dias sem atendimento)" },
  "crm.recurring_min_visits": { label: "Cliente recorrente a partir de (atendimentos)" },
  "packages.low_balance_threshold": { label: "Alerta de saldo baixo (sessões restantes)" },
  "packages.expiry_alert_days": { label: "Alerta de vencimento de pacote (dias antes)" },
  "finance.default_account_id": { label: "Conta padrão para recebimentos e pagamentos" },
  "finance.default_receivable_due_days": { label: "Prazo padrão de vencimento (dias)" },
  "security.session_idle_minutes": { label: "Bloqueio automático por inatividade (minutos)" },
  "lgpd.retention_years_inactive": { label: "Revisão de retenção de clientes inativos (anos)", hint: "Clientes sem atividade há mais tempo devem ser avaliados para anonimização, respeitando obrigações legais" },
  "lgpd.consent_text": { label: "Texto do consentimento informado (anamnese)" },
};

function Params({ group, title, extra, compact, accounts }: { group: string; title: string; extra?: string; compact?: boolean; accounts?: any[] }) {
  const a = useGet<any>(["params", group], `/settings/params/${group}`);
  const b = useGet<any>(["params", extra], extra ? `/settings/params/${extra}` : null);
  const [vals, setVals] = useState<Record<string, any>>({});
  useEffect(() => { setVals({ ...(a.data || {}), ...(b.data || {}) }); }, [a.data, b.data]);
  const save = useAction(async () => {
    const groups: Record<string, any> = {};
    Object.entries(vals).forEach(([k, v]) => {
      const g = k.split(".")[0];
      const original = { ...(a.data || {}), ...(b.data || {}) }[k];
      (groups[g] ||= {})[k] = Array.isArray(original) && typeof v === "string" ? v.split(",").map((x) => Number(x.trim())).filter((x) => x > 0) : v;
    });
    for (const [g, body] of Object.entries(groups)) await put(`/settings/params/${g}`, body);
    return { message: "Parâmetros salvos." };
  }, { invalidate: [["params"]] });
  const entries = Object.entries(vals).filter(([k]) => PARAM_LABELS[k] && k !== "agenda.allow_overbooking_rooms");
  return (
    <Card title={title} className={compact ? "" : ""}>
      <div className={compact ? "space-y-3" : "grid gap-3 sm:grid-cols-2"}>
        {entries.map(([k, v]) => {
          const meta = PARAM_LABELS[k];
          if (typeof v === "boolean") return <Checkbox key={k} label={meta.label} checked={v} onChange={(x) => setVals({ ...vals, [k]: x })} />;
          if (k === "finance.default_account_id") return (
            <Field key={k} label={meta.label}><Select value={v || ""} onChange={(e) => setVals({ ...vals, [k]: e.target.value || null })}><option value="">Primeira conta ativa</option>{(accounts || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select></Field>
          );
          if (k === "lgpd.consent_text") return <Field key={k} label={meta.label} className="sm:col-span-2"><Textarea className="min-h-[120px]" value={v} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} /></Field>;
          if (Array.isArray(v) || (typeof v === "string" && k === "crm.return_alert_days")) return <Field key={k} label={meta.label} hint={meta.hint}><Input value={Array.isArray(v) ? v.join(", ") : v} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} /></Field>;
          return <Field key={k} label={meta.label} hint={meta.hint}><Input type="number" min={0} value={v ?? ""} onChange={(e) => setVals({ ...vals, [k]: e.target.value === "" ? null : Number(e.target.value) })} /></Field>;
        })}
      </div>
      <div className="mt-4 flex justify-end"><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Salvar</Button></div>
    </Card>
  );
}

const OFFSITE_LABEL: Record<string, string> = {
  enviado: "enviada (S3)",
  pasta: "pasta extra",
  nao_configurado: "não configurada",
  falha: "falha",
};

function Backups() {
  const toast = useToast();
  const q = useGet<any>(["backups"], "/backups");
  const run = useAction(() => post("/backups/run"), { invalidate: [["backups"]] });
  const verify = useAction((id: string) => post(`/backups/${id}/verify`), { invalidate: [["backups"]] });
  const cfg = q.data?.config;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Política de backup" className="lg:col-span-2">
          {cfg && (
            <div className="grid gap-2 text-sm sm:grid-cols-2">
              <p className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-600" /> Criptografia {cfg.encryption}</p>
              <p>Backup automático diário a partir das {cfg.daily_hour}h</p>
              <p>Retenção local: {cfg.retention_days} dias</p>
              <p>Cópia externa: {cfg.offsite_configured ? <Badge color="green">ativa</Badge> : <Badge color="red">não configurada</Badge>}</p>
              {cfg.offsite_configured && cfg.offsite_bucket && <p className="break-all text-xs text-slate-500">{cfg.offsite_bucket}</p>}
            </div>
          )}
          {cfg && !cfg.offsite_configured && <div className="mt-3"><Alert kind="warning">Sem cópia externa: os backups ficam somente neste computador. Na instalação Windows, execute o instalador novamente e informe uma pasta de cópia extra (HD externo ou pasta sincronizada do OneDrive/Google Drive); no servidor, configure o armazenamento S3 compatível (ver docs/BACKUP_E_RESTAURACAO.md).</Alert></div>}
          <p className="mt-3 text-xs text-slate-500">A restauração é feita pelo administrador do servidor via linha de comando (procedimento documentado), evitando sobrescrita acidental do banco em produção.</p>
        </Card>
        <Card title="Backup manual">
          <Button icon={<DatabaseBackup className="h-4 w-4" />} loading={run.isPending} onClick={() => run.mutate(undefined)}>Executar backup agora</Button>
          <p className="mt-2 text-xs text-slate-500">O arquivo é verificado (integridade e leitura pelo pg_restore) após a geração.</p>
        </Card>
      </div>
      <Card padded={false} title="Histórico">
        <DataTable rows={q.data?.items || []} empty={<Empty title="Nenhum backup executado" />} columns={[
          { key: "started_at", label: "Início", render: (r) => dateTime(r.started_at) },
          { key: "kind", label: "Tipo" },
          { key: "status", label: "Situação", render: (r) => <Badge color={r.status === "sucesso" ? "green" : r.status === "falha" ? "red" : "yellow"}>{r.status}</Badge> },
          { key: "size_bytes", label: "Tamanho", render: (r) => (r.size_bytes ? `${(r.size_bytes / 1024 / 1024).toFixed(2)} MB` : "—") },
          { key: "verify_status", label: "Verificação", render: (r) => r.verify_status ? <Badge color={r.verify_status === "ok" ? "green" : "red"}>{r.verify_status}</Badge> : "—" },
          { key: "offsite_status", label: "Cópia externa", render: (r) => OFFSITE_LABEL[r.offsite_status ?? ""] ?? (r.offsite_status || "—") },
          { key: "error", label: "Erro", render: (r) => <span className="text-xs text-rose-600">{r.error || ""}</span> },
          { key: "a", label: "", render: (r) => r.status === "sucesso" && !r.deleted_at && (
            <div className="flex justify-end gap-1">
              <Button size="sm" variant="ghost" onClick={() => verify.mutate(r.id)}>Verificar</Button>
              <Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} onClick={() => download(`/backups/${r.id}/download`).catch((e) => toast.error(e))}>Baixar</Button>
            </div>) },
        ]} />
      </Card>
    </div>
  );
}
