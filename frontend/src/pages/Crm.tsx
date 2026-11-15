import clsx from "clsx";
import { Cake, Phone, Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Badge, Button, Card, DataTable, Empty, Field, Input, Loading, Modal, PageHeader, Select, StatusBadge, Tabs, Textarea } from "../components/ui";
import { post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { date, dateTime, isoDay, localToIso, phone } from "../lib/format";
import { useAction, useGet } from "../lib/hooks";
import { ContactForm } from "./CustomerProfile";

export default function Crm() {
  const [params] = useSearchParams();
  const [tab, setTab] = useState(params.get("aba") || "funil");
  const { can } = useAuth();
  return (
    <div>
      <PageHeader title="CRM — Relacionamento" subtitle="Funil, tarefas, retornos e campanhas respeitando o consentimento de cada cliente." />
      <Tabs value={tab} onChange={setTab} tabs={[
        { key: "funil", label: "Funil" }, { key: "alertas", label: "Retornos e aniversários" }, { key: "tarefas", label: "Tarefas" },
        { key: "historico", label: "Histórico de contatos" }, ...(can("crm.campaigns") ? [{ key: "campanhas", label: "Campanhas" }] : []),
      ]} />
      {tab === "funil" && <Funnel />}
      {tab === "alertas" && <Alerts />}
      {tab === "tarefas" && <Tasks />}
      {tab === "historico" && <History />}
      {tab === "campanhas" && <Campaigns />}
    </div>
  );
}

function Funnel() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const stages = useGet<any[]>(["crm-stages"], "/crm/stages");
  const leads = useGet<any[]>(["crm-leads"], "/crm/leads");
  const [creating, setCreating] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [contactLead, setContactLead] = useState<any>(null);
  const move = useAction((v: { id: string; stage: string }) => post(`/crm/leads/${v.id}/stage`, { stage: v.stage }), { success: "Estágio atualizado.", invalidate: [["crm-leads"]] });
  const convert = useAction((id: string) => post(`/crm/leads/${id}/convert`), { invalidate: [["crm-leads"]], onDone: (r: any) => navigate(`/clientes/${r.customer_id}`) });
  if (leads.isLoading || stages.isLoading) return <Loading />;
  return (
    <div>
      {can("crm.write") && <div className="mb-3 flex justify-end"><Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>Novo contato</Button></div>}
      <div className="flex gap-3 overflow-x-auto pb-3">
        {(stages.data || []).map((s) => {
          const items = (leads.data || []).filter((l) => l.stage === s.code);
          return (
            <div key={s.code} className={clsx("w-64 shrink-0 rounded-2xl bg-slate-50 p-2 dark:bg-slate-900/60", dragId && "ring-1 ring-brand-100")}
              onDragOver={(e) => can("crm.write") && e.preventDefault()}
              onDrop={() => { if (dragId) move.mutate({ id: dragId, stage: s.code }); setDragId(null); }}>
              <div className="mb-2 flex items-center justify-between px-1">
                <p className="text-xs font-semibold uppercase text-slate-500">{s.label}</p>
                <Badge color="blue">{items.length}</Badge>
              </div>
              <div className="space-y-2">
                {items.map((l) => (
                  <div key={l.id} draggable={can("crm.write")} onDragStart={() => setDragId(l.id)} onDragEnd={() => setDragId(null)}
                    className="card cursor-grab p-3 text-sm active:cursor-grabbing">
                    <p className="font-medium">{l.name}</p>
                    <p className="text-xs text-slate-500">{phone(l.phone)} {l.source ? `· ${l.source}` : ""}</p>
                    <p className="mt-1 text-[11px] text-slate-400">no estágio desde {date(l.stage_changed_at)}</p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {l.customer_id ? <Button size="sm" variant="ghost" onClick={() => navigate(`/clientes/${l.customer_id}`)}>Perfil</Button>
                        : can("customers.write") && <Button size="sm" variant="ghost" onClick={() => convert.mutate(l.id)}>Cadastrar cliente</Button>}
                      {can("crm.write") && <Button size="sm" variant="ghost" onClick={() => setContactLead(l)}>Contato</Button>}
                      {can("crm.write") && (
                        <select className="rounded-lg border border-slate-200 bg-transparent px-1 text-[11px] dark:border-slate-700" value={l.stage} aria-label="Mover estágio"
                          onChange={(e) => move.mutate({ id: l.id, stage: e.target.value })}>
                          {(stages.data || []).map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}
                        </select>
                      )}
                    </div>
                  </div>
                ))}
                {items.length === 0 && <p className="px-1 py-4 text-center text-xs text-slate-400">Arraste cartões para cá</p>}
              </div>
            </div>
          );
        })}
      </div>
      {creating && <LeadForm stages={stages.data || []} onClose={() => setCreating(false)} />}
      {contactLead && <ContactForm customerId={contactLead.customer_id || undefined} leadId={contactLead.id} onClose={() => setContactLead(null)} />}
    </div>
  );
}

function LeadForm({ stages, onClose }: { stages: any[]; onClose: () => void }) {
  const [f, setF] = useState({ name: "", phone: "", email: "", source: "", stage: "novo_contato", notes: "" });
  const save = useAction(() => post("/crm/leads", f), { success: "Contato registrado no funil.", invalidate: [["crm-leads"]], onDone: onClose });
  return (
    <Modal open onClose={onClose} title="Novo contato" size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={save.isPending} disabled={f.name.length < 2} onClick={() => save.mutate(undefined)}>Salvar</Button></>}>
      <div className="grid gap-3">
        <Field label="Nome" required><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Telefone/WhatsApp"><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field>
        <Field label="E-mail"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Origem"><Input value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} /></Field>
        <Field label="Estágio"><Select value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })}>{stages.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}</Select></Field>
        <Field label="Observações"><Textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      </div>
    </Modal>
  );
}

function Alerts() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const q = useGet<any>(["crm-alerts"], "/crm/alerts");
  const [task, setTask] = useState<any>(null);
  if (q.isLoading) return <Loading />;
  const a = q.data;
  const row = (r: any) => (
    <li key={r.customer_id} className="flex items-center justify-between gap-2 py-2 text-sm">
      <button className="text-left" onClick={() => navigate(`/clientes/${r.customer_id}`)}>
        <span className="font-medium">{r.name}</span>
        <span className="block text-xs text-slate-500">{phone(r.phone)} · último atendimento {date(r.last_visit_at)} ({r.days} dias)</span>
      </button>
      <div className="flex items-center gap-1">
        {!r.marketing_consent && <Badge color="gray">sem consentimento</Badge>}
        {can("crm.write") && <Button size="sm" variant="ghost" icon={<Phone className="h-3.5 w-3.5" />} onClick={() => setTask(r)}>Tarefa</Button>}
      </div>
    </li>
  );
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {a.return_thresholds.map((d: number) => (
        <Card key={d} title={`Sem retorno há ${d}+ dias`} actions={<Badge color="violet">{a.returns[String(d)].length}</Badge>}>
          {a.returns[String(d)].length === 0 ? <p className="text-sm text-slate-500">Ninguém nesta faixa.</p> :
            <ul className="max-h-80 divide-y divide-slate-100 overflow-y-auto dark:divide-slate-800">{a.returns[String(d)].map(row)}</ul>}
        </Card>
      ))}
      <Card title="Aniversariantes (próximos 7 dias)" actions={<Cake className="h-4 w-4 text-rose-500" />}>
        {a.birthdays.length === 0 ? <p className="text-sm text-slate-500">Nenhum aniversário próximo.</p> : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {a.birthdays.map((b: any) => (
              <li key={b.customer_id} className="flex items-center justify-between py-2 text-sm">
                <button className="font-medium" onClick={() => navigate(`/clientes/${b.customer_id}`)}>{b.name}</button>
                <span className="flex items-center gap-2">{b.today && <Badge color="pink">hoje!</Badge>}{date(b.birth_date).slice(0, 5)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Clientes inativos" actions={<Badge color="gray">{a.inactive.length}</Badge>}>
        {a.inactive.length === 0 ? <p className="text-sm text-slate-500">Nenhum cliente inativo.</p> : (
          <ul className="max-h-80 divide-y divide-slate-100 overflow-y-auto dark:divide-slate-800">
            {a.inactive.map((l: any) => (
              <li key={l.lead_id} className="flex justify-between py-2 text-sm">
                <button className="font-medium" onClick={() => l.customer_id && navigate(`/clientes/${l.customer_id}`)}>{l.name}</button>
                <span className="text-xs text-slate-500">desde {date(l.since)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Atendidos sem agendamento futuro" className="lg:col-span-2" actions={<Badge color="blue">{a.without_future.length}</Badge>}>
        {a.without_future.length === 0 ? <p className="text-sm text-slate-500">Todos os clientes atendidos têm retorno marcado.</p> :
          <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto dark:divide-slate-800">{a.without_future.map(row)}</ul>}
      </Card>
      {task && <TaskForm initial={{ title: `Contato de retorno: ${task.name}`, kind: "retorno", customer_id: task.customer_id }} onClose={() => setTask(null)} />}
    </div>
  );
}

function TaskForm({ initial, onClose }: { initial?: any; onClose: () => void }) {
  const [f, setF] = useState({ title: initial?.title || "", description: "", kind: initial?.kind || "follow_up", day: isoDay(), time: "10:00" });
  const save = useAction(() => post("/crm/tasks", { title: f.title, description: f.description || null, kind: f.kind, due_at: localToIso(f.day, f.time),
    customer_id: initial?.customer_id || null }), { success: "Tarefa criada.", invalidate: [["crm-tasks"]], onDone: onClose });
  return (
    <Modal open onClose={onClose} title="Nova tarefa" size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={save.isPending} disabled={f.title.length < 2} onClick={() => save.mutate(undefined)}>Salvar</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Título" required className="sm:col-span-2"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="Tipo"><Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          <option value="retorno">Retorno</option><option value="lembrete">Lembrete</option><option value="follow_up">Follow-up</option><option value="aniversario">Aniversário</option><option value="outro">Outro</option>
        </Select></Field>
        <Field label="Data"><Input type="date" value={f.day} onChange={(e) => setF({ ...f, day: e.target.value })} /></Field>
        <Field label="Hora"><Input type="time" value={f.time} onChange={(e) => setF({ ...f, time: e.target.value })} /></Field>
        <Field label="Descrição" className="sm:col-span-2"><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      </div>
    </Modal>
  );
}

function Tasks() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState("pendente");
  const [creating, setCreating] = useState(false);
  const q = useGet<any[]>(["crm-tasks"], "/crm/tasks", { status });
  const act = useAction((v: { id: string; action: string }) => post(`/crm/tasks/${v.id}/${v.action}`), { success: "Tarefa atualizada.", invalidate: [["crm-tasks"]] });
  const now = new Date().toISOString();
  return (
    <Card padded={false} title="Tarefas e lembretes" actions={<>
      <Select className="!w-auto" value={status} onChange={(e) => setStatus(e.target.value)}><option value="pendente">Pendentes</option><option value="concluida">Concluídas</option><option value="cancelada">Canceladas</option></Select>
      {can("crm.write") && <Button size="sm" onClick={() => setCreating(true)}>Nova tarefa</Button>}
    </>}>
      <DataTable rows={q.data || []} empty={<Empty title="Nenhuma tarefa" />} columns={[
        { key: "due_at", label: "Prazo", render: (r) => <span className={clsx(r.status === "pendente" && r.due_at < now && "font-semibold text-rose-600")}>{dateTime(r.due_at)}</span> },
        { key: "title", label: "Tarefa" },
        { key: "kind", label: "Tipo", render: (r) => <Badge color="violet">{r.kind}</Badge> },
        { key: "customer_name", label: "Cliente", render: (r) => r.customer_id ? <button className="text-brand-600" onClick={() => navigate(`/clientes/${r.customer_id}`)}>{r.customer_name}</button> : "—" },
        { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
        { key: "a", label: "", render: (r) => can("crm.write") && (r.status === "pendente" ? (
          <div className="flex gap-1"><Button size="sm" variant="secondary" onClick={() => act.mutate({ id: r.id, action: "concluir" })}>Concluir</Button>
            <Button size="sm" variant="ghost" onClick={() => act.mutate({ id: r.id, action: "cancelar" })}>Cancelar</Button></div>
        ) : <Button size="sm" variant="ghost" onClick={() => act.mutate({ id: r.id, action: "reabrir" })}>Reabrir</Button>) },
      ]} />
      {creating && <TaskForm onClose={() => setCreating(false)} />}
    </Card>
  );
}

function History() {
  const [kind, setKind] = useState("");
  const q = useGet<any[]>(["crm-interactions"], "/crm/interactions", { kind: kind || undefined, limit: 300 });
  return (
    <Card padded={false} title="Histórico de conversas e contatos" actions={
      <Select className="!w-auto" value={kind} onChange={(e) => setKind(e.target.value)}>
        <option value="">Todos</option><option value="ligacao">Ligações</option><option value="whatsapp">WhatsApp</option><option value="mensagem">Mensagens</option>
        <option value="email">E-mail</option><option value="presencial">Presencial</option><option value="nota">Notas</option><option value="sistema">Sistema</option>
      </Select>}>
      <DataTable rows={q.data || []} columns={[
        { key: "occurred_at", label: "Data", render: (r) => dateTime(r.occurred_at) },
        { key: "customer_name", label: "Cliente", render: (r) => r.customer_name || "—" },
        { key: "kind", label: "Tipo" },
        { key: "subject", label: "Assunto" },
        { key: "summary", label: "Resumo", render: (r) => <span className="line-clamp-2 max-w-md text-slate-500">{r.summary || "—"}</span> },
      ]} />
    </Card>
  );
}

function Campaigns() {
  const list = useGet<any[]>(["campaigns"], "/crm/campaigns");
  const templates = useGet<any[]>(["wa-templates"], "/whatsapp/templates");
  const stages = useGet<any[]>(["crm-stages"], "/crm/stages");
  const [f, setF] = useState({ name: "", description: "", template_id: "", segment: "", stage: "", no_visit_days: "" });
  const [preview, setPreview] = useState<any>(null);
  const body = () => ({ name: f.name, description: f.description || null, template_id: f.template_id,
    audience: { segment: f.segment || undefined, stage: f.stage || undefined, no_visit_days: f.no_visit_days ? Number(f.no_visit_days) : undefined } });
  const doPreview = useAction(() => post("/crm/campaigns/preview", body()), { success: () => "", onDone: setPreview });
  const create = useAction(() => post("/crm/campaigns", body()), { invalidate: [["campaigns"]], onDone: () => { setF({ ...f, name: "" }); setPreview(null); } });
  const dispatch = useAction((id: string) => post(`/crm/campaigns/${id}/dispatch`), { invalidate: [["campaigns"]] });
  const marketing = (templates.data || []).filter((t) => t.category === "MARKETING" && t.meta_status === "APPROVED" && t.is_active);
  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <Card title="Nova campanha" className="lg:col-span-2">
        <div className="space-y-3">
          <Field label="Nome" required><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Template aprovado (categoria MARKETING)" required hint={marketing.length ? undefined : "Nenhum template de marketing aprovado. Sincronize em WhatsApp > Templates."}>
            <Select value={f.template_id} onChange={(e) => setF({ ...f, template_id: e.target.value })}><option value="">Selecione</option>{marketing.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select>
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Segmento"><Select value={f.segment} onChange={(e) => setF({ ...f, segment: e.target.value })}><option value="">Todos ativos</option><option value="novos">Novos</option><option value="recorrentes">Recorrentes</option><option value="inativos">Inativos</option></Select></Field>
            <Field label="Estágio do funil"><Select value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })}><option value="">Qualquer</option>{(stages.data || []).map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}</Select></Field>
          </div>
          <Field label="Sem atendimento há (dias)"><Input type="number" min={1} value={f.no_visit_days} onChange={(e) => setF({ ...f, no_visit_days: e.target.value })} /></Field>
          <Field label="Descrição"><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <p className="text-xs text-slate-500">Somente clientes com consentimento para mensagens de relacionamento recebem a campanha. Opt-out ("SAIR") é respeitado automaticamente.</p>
          <div className="flex gap-2">
            <Button variant="secondary" disabled={!f.template_id || !f.name} loading={doPreview.isPending} onClick={() => doPreview.mutate(undefined)}>Prévia do público</Button>
            <Button disabled={!f.template_id || !f.name} loading={create.isPending} onClick={() => create.mutate(undefined)}>Salvar rascunho</Button>
          </div>
          {preview && <p className="text-sm">Público: <b>{preview.total}</b> cliente(s), <b>{preview.with_consent}</b> com consentimento. {preview.sample.length > 0 && `Ex.: ${preview.sample.slice(0, 5).join(", ")}`}</p>}
        </div>
      </Card>
      <Card title="Campanhas" padded={false} className="lg:col-span-3">
        <DataTable rows={list.data || []} empty={<Empty title="Nenhuma campanha" />} columns={[
          { key: "name", label: "Campanha" },
          { key: "status", label: "Situação", render: (r) => <Badge color={r.status === "rascunho" ? "gray" : "green"}>{r.status}</Badge> },
          { key: "q", label: "Envios", render: (r) => r.status === "rascunho" ? "—" : `${r.queued_count} na fila · ${r.skipped_count} ignorados` },
          { key: "created_at", label: "Criada", render: (r) => date(r.created_at) },
          { key: "a", label: "", render: (r) => r.status === "rascunho" && <Button size="sm" loading={dispatch.isPending} onClick={() => dispatch.mutate(r.id)}>Disparar</Button> },
        ]} />
      </Card>
    </div>
  );
}
