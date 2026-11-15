import { CheckCircle2, Circle, Copy, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CustomerPicker } from "../components/shared";
import { Alert, Badge, Button, Card, Checkbox, DataTable, Empty, Field, Input, Modal, PageHeader, Pagination, Select, StatCard, StatusBadge, Tabs, Textarea, useToast } from "../components/ui";
import { post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime, phone } from "../lib/format";
import { useAction, useGet } from "../lib/hooks";

export default function WhatsApp() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const [tab, setTab] = useState("mensagens");
  return (
    <div>
      <PageHeader title="WhatsApp Business" subtitle="Integração oficial com a WhatsApp Cloud API (Meta). Nenhuma informação de saúde é enviada por mensagem." />
      <Status />
      <div className="mt-4"><Tabs value={tab} onChange={setTab} tabs={[
        { key: "mensagens", label: "Mensagens" }, { key: "templates", label: "Templates" }, ...(can("whatsapp.settings") ? [{ key: "config", label: "Configuração" }] : []),
      ]} /></div>
      {tab === "mensagens" && <Messages initialStatus={params.get("status") || ""} />}
      {tab === "templates" && <Templates />}
      {tab === "config" && <Settings />}
    </div>
  );
}

function Status() {
  const q = useGet<any>(["wa-status"], "/whatsapp/status");
  const s = q.data;
  if (!s) return null;
  const Item = ({ ok, text }: { ok: boolean; text: string }) => (
    <span className="flex items-center gap-1.5 text-sm">{ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <Circle className="h-4 w-4 text-slate-400" />}{text}</span>
  );
  return (
    <div className="grid gap-3 lg:grid-cols-4">
      <Card className="lg:col-span-2">
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          <Item ok={s.enabled} text={s.enabled ? "Integração ativa" : "Integração desativada"} />
          <Item ok={s.configured} text="Credenciais configuradas" />
          <Item ok={s.webhook_configured} text="Webhook protegido" />
          <Item ok={s.approved_templates > 0} text={`${s.approved_templates} template(s) aprovado(s) e ativo(s)`} />
        </div>
        {!s.enabled && <p className="mt-2 text-xs text-slate-500">Com a integração desativada, agenda e demais módulos funcionam normalmente; nenhuma mensagem é enviada.</p>}
      </Card>
      <StatCard label="Na fila" value={(s.queue.pendente || 0) + (s.queue.enviando || 0)} tone="amber" />
      <StatCard label="Com falha" value={s.queue.falhou || 0} hint={`Entregues: ${s.queue.entregue || 0} · Lidas: ${s.queue.lida || 0}`} tone="pink" />
    </div>
  );
}

function Messages({ initialStatus }: { initialStatus: string }) {
  const { can } = useAuth();
  const [status, setStatus] = useState(initialStatus);
  const [direction, setDirection] = useState("");
  const [page, setPage] = useState(1);
  const [sending, setSending] = useState(false);
  const list = useGet<any>(["wa-messages"], "/whatsapp/messages", { status: status || undefined, direction: direction || undefined, page });
  const retry = useAction((id: string) => post(`/whatsapp/messages/${id}/retry`), { invalidate: [["wa-messages"], ["wa-status"]] });
  const cancel = useAction((id: string) => post(`/whatsapp/messages/${id}/cancel`), { invalidate: [["wa-messages"], ["wa-status"]] });
  return (
    <Card padded={false} title="Histórico de mensagens" actions={<>
      <Select className="!w-auto" value={direction} onChange={(e) => setDirection(e.target.value)}><option value="">Enviadas e recebidas</option><option value="saida">Enviadas</option><option value="entrada">Recebidas</option></Select>
      <Select className="!w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="">Todos os status</option>{["pendente", "enviada", "entregue", "lida", "falhou", "bloqueada", "cancelada", "recebida"].map((s) => <option key={s} value={s}>{s}</option>)}
      </Select>
      {can("whatsapp.send") && <Button size="sm" onClick={() => setSending(true)}>Enviar mensagem</Button>}
    </>}>
      <DataTable rows={list.data?.items || []} empty={<Empty title="Nenhuma mensagem" />} columns={[
        { key: "created_at", label: "Data", render: (r) => dateTime(r.created_at) },
        { key: "customer_name", label: "Cliente", render: (r) => r.customer_name || phone(r.phone) },
        { key: "direction", label: "", render: (r) => <Badge color={r.direction === "entrada" ? "pink" : "blue"}>{r.direction === "entrada" ? "recebida" : r.purpose || "enviada"}</Badge> },
        { key: "content", label: "Conteúdo", render: (r) => <span className="line-clamp-2 max-w-md text-slate-600 dark:text-slate-300">{r.content || "—"}</span> },
        { key: "status", label: "Status", render: (r) => <div><StatusBadge status={r.status} />{r.last_error && <p className="mt-1 max-w-xs text-[11px] text-rose-600">{r.last_error}</p>}</div> },
        { key: "a", label: "", render: (r) => can("whatsapp.send") && (r.status === "falhou" ? <Button size="sm" variant="ghost" onClick={() => retry.mutate(r.id)}>Reenviar</Button>
          : r.status === "pendente" ? <Button size="sm" variant="ghost" onClick={() => cancel.mutate(r.id)}>Cancelar</Button> : null) },
      ]} />
      <Pagination page={page} pageSize={50} total={list.data?.total || 0} onPage={setPage} />
      {sending && <SendForm onClose={() => setSending(false)} />}
    </Card>
  );
}

function SendForm({ onClose }: { onClose: () => void }) {
  const templates = useGet<any[]>(["wa-templates"], "/whatsapp/templates");
  const [customer, setCustomer] = useState<any>(null);
  const [mode, setMode] = useState("template");
  const [templateId, setTemplateId] = useState("");
  const [body, setBody] = useState("");
  const send = useAction(() => mode === "template" ? post("/whatsapp/messages/template", { customer_id: customer.id, template_id: templateId })
    : post("/whatsapp/messages/text", { customer_id: customer.id, body }), { invalidate: [["wa-messages"], ["wa-status"]], onDone: onClose });
  const approved = (templates.data || []).filter((t) => t.meta_status === "APPROVED" && t.is_active);
  return (
    <Modal open onClose={onClose} title="Enviar mensagem" size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={send.isPending} disabled={!customer || (mode === "template" ? !templateId : !body)} onClick={() => send.mutate(undefined)}>Enviar</Button></>}>
      <div className="space-y-3">
        <Field label="Cliente"><CustomerPicker value={customer} onChange={setCustomer} allowCreate={false} /></Field>
        <Field label="Tipo"><Select value={mode} onChange={(e) => setMode(e.target.value)}><option value="template">Template aprovado</option><option value="texto">Texto livre (somente até 24 h após a última mensagem do cliente)</option></Select></Field>
        {mode === "template" ? (
          <Field label="Template"><Select value={templateId} onChange={(e) => setTemplateId(e.target.value)}><option value="">Selecione</option>{approved.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.category})</option>)}</Select></Field>
        ) : (
          <Field label="Mensagem" hint="Não envie informações de saúde, anamnese ou detalhes do atendimento."><Textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={4000} /></Field>
        )}
      </div>
    </Modal>
  );
}

function Templates() {
  const { can } = useAuth();
  const list = useGet<any[]>(["wa-templates"], "/whatsapp/templates");
  const cfg = useGet<any>(["wa-settings"], can("whatsapp.settings") ? "/whatsapp/settings" : null);
  const sync = useAction(() => post("/whatsapp/templates/sync"), { invalidate: [["wa-templates"], ["wa-status"]] });
  const [editing, setEditing] = useState<any>(null);
  return (
    <Card padded={false} title="Templates da Meta" actions={can("whatsapp.settings") && <Button size="sm" icon={<RefreshCw className="h-4 w-4" />} loading={sync.isPending} onClick={() => sync.mutate(undefined)}>Sincronizar com a Meta</Button>}>
      <div className="p-3"><Alert kind="info">Os templates são criados e aprovados no Gerenciador do WhatsApp (Meta). Após sincronizar, vincule cada um a uma finalidade e mapeie as variáveis {"{{1}}, {{2}}..."} para dados permitidos.</Alert></div>
      <DataTable rows={list.data || []} empty={<Empty title="Nenhum template sincronizado" />} columns={[
        { key: "name", label: "Nome" }, { key: "language", label: "Idioma" }, { key: "category", label: "Categoria" },
        { key: "meta_status", label: "Status Meta", render: (r) => <Badge color={r.meta_status === "APPROVED" ? "green" : r.meta_status === "REJECTED" ? "red" : "yellow"}>{r.meta_status}</Badge> },
        { key: "purpose", label: "Finalidade", render: (r) => r.purpose ? cfg.data?.purposes?.[r.purpose] || r.purpose : "—" },
        { key: "body_text", label: "Texto", render: (r) => <span className="line-clamp-2 max-w-sm text-xs text-slate-500">{r.body_text}</span> },
        { key: "is_active", label: "Ativo", render: (r) => (r.is_active ? "Sim" : "Não") },
        { key: "a", label: "", render: (r) => can("whatsapp.settings") && <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Configurar</Button> },
      ]} />
      {editing && cfg.data && <TemplateForm t={editing} purposes={cfg.data.purposes} variables={cfg.data.variables} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function TemplateForm({ t, purposes, variables, onClose }: { t: any; purposes: Record<string, string>; variables: Record<string, string>; onClose: () => void }) {
  const count = (t.body_text?.match(/\{\{\d+\}\}/g) || []).length;
  const [f, setF] = useState({ purpose: t.purpose || "", is_active: t.is_active, parameters: Array.from({ length: count }, (_, i) => t.parameters?.[i] || "") });
  const save = useAction(() => put(`/whatsapp/templates/${t.id}`, { purpose: f.purpose || null, parameters: f.parameters, is_active: f.is_active }), { invalidate: [["wa-templates"], ["wa-status"]], onDone: onClose });
  return (
    <Modal open onClose={onClose} title={`Template: ${t.name}`} size="md" footer={<Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Salvar</Button>}>
      <div className="space-y-3">
        <pre className="whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-800">{t.body_text}</pre>
        <Field label="Finalidade"><Select value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })}><option value="">—</option>{Object.entries(purposes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
        {f.parameters.map((p, i) => (
          <Field key={i} label={`Variável {{${i + 1}}}`}>
            <Select value={p} onChange={(e) => { const ps = [...f.parameters]; ps[i] = e.target.value; setF({ ...f, parameters: ps }); }}>
              <option value="">Selecione</option>{Object.entries(variables).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
        ))}
        <Checkbox label="Ativo para uso automático" checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} />
        <p className="text-xs text-slate-500">Aniversário, retorno e campanhas exigem template da categoria MARKETING e consentimento específico do cliente.</p>
      </div>
    </Modal>
  );
}

function Settings() {
  const toast = useToast();
  const q = useGet<any>(["wa-settings"], "/whatsapp/settings");
  const [f, setF] = useState<any>(null);
  useEffect(() => {
    if (q.data) setF({ ...q.data, access_token: "", app_secret: "", verify_token: "" });
  }, [q.data]);
  const save = useAction(() => put("/whatsapp/settings", {
    enabled: f.enabled, api_version: f.api_version, business_id: f.business_id || null, waba_id: f.waba_id || null, phone_number_id: f.phone_number_id || null,
    access_token: f.access_token || null, app_secret: f.app_secret || null, verify_token: f.verify_token || null, reminder_hours_before: Number(f.reminder_hours_before),
    auto_confirmation: f.auto_confirmation, auto_reminder: f.auto_reminder, auto_reschedule: f.auto_reschedule, auto_cancellation: f.auto_cancellation,
    auto_thanks: f.auto_thanks, auto_birthday: f.auto_birthday, birthday_hour: Number(f.birthday_hour),
  }), { invalidate: [["wa-settings"], ["wa-status"]] });
  const test = useAction(() => post("/whatsapp/test"));
  if (!f) return null;
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Credenciais da Cloud API">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2"><Checkbox label="Integração ativa" checked={f.enabled} onChange={(v) => setF({ ...f, enabled: v })} /></div>
          <Field label="Meta Business ID"><Input value={f.business_id || ""} onChange={set("business_id")} /></Field>
          <Field label="WhatsApp Business Account ID"><Input value={f.waba_id || ""} onChange={set("waba_id")} /></Field>
          <Field label="Phone Number ID"><Input value={f.phone_number_id || ""} onChange={set("phone_number_id")} /></Field>
          <Field label="Versão da Graph API" hint="Atualize conforme o changelog da Meta"><Input value={f.api_version} onChange={set("api_version")} /></Field>
          <Field label="Access Token (permanente, de usuário do sistema)" hint={f.access_token_set ? "Configurado — deixe em branco para manter" : "Não configurado"} className="sm:col-span-2">
            <Input type="password" autoComplete="off" value={f.access_token} onChange={set("access_token")} /></Field>
          <Field label="App Secret (validação da assinatura do webhook)" hint={f.app_secret_set ? "Configurado — deixe em branco para manter" : "Não configurado"}>
            <Input type="password" autoComplete="off" value={f.app_secret} onChange={set("app_secret")} /></Field>
          <Field label="Webhook Verify Token" hint={f.verify_token_set ? "Configurado — deixe em branco para manter" : "Defina um texto aleatório"}>
            <Input type="password" autoComplete="off" value={f.verify_token} onChange={set("verify_token")} /></Field>
          <div className="sm:col-span-2">
            <p className="label">Webhook URL (cadastre no app da Meta)</p>
            <div className="flex gap-2"><Input readOnly value={f.webhook_url} /><Button variant="secondary" icon={<Copy className="h-4 w-4" />} onClick={() => { navigator.clipboard.writeText(f.webhook_url); toast.success("URL copiada."); }}>Copiar</Button></div>
          </div>
          <p className="text-xs text-slate-500 sm:col-span-2">Tokens são armazenados criptografados no servidor e nunca retornam ao navegador.</p>
        </div>
      </Card>
      <Card title="Automações">
        <div className="space-y-2.5">
          <Checkbox label="Confirmação ao agendar" checked={f.auto_confirmation} onChange={(v) => setF({ ...f, auto_confirmation: v })} />
          <Checkbox label="Lembrete antes do atendimento" checked={f.auto_reminder} onChange={(v) => setF({ ...f, auto_reminder: v })} />
          <Field label="Antecedência do lembrete (horas)"><Input type="number" min={1} max={72} value={f.reminder_hours_before} onChange={set("reminder_hours_before")} /></Field>
          <Checkbox label="Aviso de remarcação" checked={f.auto_reschedule} onChange={(v) => setF({ ...f, auto_reschedule: v })} />
          <Checkbox label="Aviso de cancelamento" checked={f.auto_cancellation} onChange={(v) => setF({ ...f, auto_cancellation: v })} />
          <Checkbox label="Agradecimento após o atendimento" checked={f.auto_thanks} onChange={(v) => setF({ ...f, auto_thanks: v })} />
          <Checkbox label="Mensagem de aniversário (exige consentimento de relacionamento)" checked={f.auto_birthday} onChange={(v) => setF({ ...f, auto_birthday: v })} />
          <Field label="Horário do envio de aniversário"><Input type="number" min={6} max={20} value={f.birthday_hour} onChange={set("birthday_hour")} /></Field>
          <p className="text-xs text-slate-500">Opt-out: respostas como “SAIR” ou “PARAR” revogam automaticamente o consentimento de mensagens promocionais.</p>
        </div>
      </Card>
      <div className="flex justify-end gap-2 lg:col-span-2">
        <Button variant="secondary" loading={test.isPending} onClick={() => test.mutate(undefined)}>Testar conexão</Button>
        <Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Salvar configuração</Button>
      </div>
    </div>
  );
}
