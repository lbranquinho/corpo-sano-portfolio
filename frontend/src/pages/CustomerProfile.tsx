import { ArrowLeft, CalendarPlus, Download, Pencil } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CustomerForm } from "../components/shared";
import {
  Alert, Badge, Button, Card, ConfirmButton, DataTable, Empty, Field, Input, Loading, Modal, PageHeader, Select, StatCard, StatusBadge, Tabs, Textarea,
} from "../components/ui";
import { download, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { cpf, date, dateTime, isoDay, money, phone } from "../lib/format";
import { useAction, useGet } from "../lib/hooks";

const KINDS: Record<string, string> = { ligacao: "Ligação", mensagem: "Mensagem", whatsapp: "WhatsApp", email: "E-mail", presencial: "Presencial", nota: "Nota", sistema: "Sistema" };

export default function CustomerProfile() {
  const { id } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const q = useGet<any>(["customer-profile", id], `/customers/${id}/profile`);
  const [tab, setTab] = useState("resumo");
  const [editing, setEditing] = useState(false);
  const [contact, setContact] = useState(false);
  const [anonymize, setAnonymize] = useState(false);
  if (q.isLoading) return <Loading />;
  if (q.error) return <Alert kind="danger">{(q.error as Error).message}</Alert>;
  const p = q.data;
  const c = p.customer;
  const tabs = [
    { key: "resumo", label: "Resumo" },
    { key: "agendamentos", label: `Agendamentos (${p.appointments.length})` },
    { key: "pacotes", label: `Pacotes (${p.packages.length})` },
    ...(p.stats.payments_total !== null ? [{ key: "financeiro", label: "Financeiro" }] : []),
    ...(can("fiscal.read") || can("finance.read") ? [{ key: "notas", label: "Notas fiscais" }] : []),
    ...(can("crm.read") ? [{ key: "contatos", label: "Contatos" }] : []),
    { key: "lgpd", label: "Privacidade (LGPD)" },
  ];
  return (
    <div>
      <button className="mb-3 flex items-center gap-1 text-sm text-slate-500 hover:text-brand-600" onClick={() => navigate("/clientes")}><ArrowLeft className="h-4 w-4" /> Clientes</button>
      <PageHeader title={c.full_name} subtitle={[phone(c.whatsapp || c.phone), c.email, c.cpf ? `CPF ${cpf(c.cpf)}` : null].filter(Boolean).join(" · ")}
        actions={<>
          {can("agenda.write") && c.status !== "anonimizado" && <Button variant="secondary" icon={<CalendarPlus className="h-4 w-4" />}
            onClick={() => navigate(`/agenda?novo=1&cliente=${c.id}&nome=${encodeURIComponent(c.full_name)}`)}>Agendar</Button>}
          {can("clinical.read") && <Button variant="secondary" onClick={() => navigate(`/atendimentos?cliente=${c.id}`)}>Anamnese e atendimentos</Button>}
          {can("customers.write") && c.status !== "anonimizado" && <Button icon={<Pencil className="h-4 w-4" />} onClick={() => setEditing(true)}>Editar</Button>}
        </>} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Atendimentos" value={p.stats.visits} hint={`Último: ${date(p.stats.last_visit_at)}`} />
        <StatCard label="Próximo agendamento" value={p.stats.next_appointment_at ? date(p.stats.next_appointment_at) : "—"} tone="violet" />
        <StatCard label="Sessões disponíveis" value={p.stats.sessions_available} hint="em pacotes ativos" tone="pink" />
        {p.stats.payments_total !== null ? <StatCard label="Total pago" value={money(p.stats.payments_total)} hint={`Em aberto: ${money(p.stats.open_balance)}`} tone="green" />
          : <StatCard label="Faltas / cancelamentos" value={`${p.stats.no_shows} / ${p.stats.cancellations}`} tone="amber" />}
      </div>
      <Tabs tabs={tabs} value={tab} onChange={setTab} />

      {tab === "resumo" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Cadastro">
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div><dt className="label">Nascimento</dt><dd>{date(c.birth_date)}</dd></div>
              <div><dt className="label">Cliente desde</dt><dd>{date(c.created_at)}</dd></div>
              <div><dt className="label">Origem</dt><dd>{c.source || "—"}</dd></div>
              <div><dt className="label">Situação</dt><dd><StatusBadge status={c.status} /></dd></div>
              <div className="col-span-2"><dt className="label">Endereço</dt><dd>{[c.street, c.number, c.complement, c.district, c.city, c.state].filter(Boolean).join(", ") || "—"}</dd></div>
              <div className="col-span-2"><dt className="label">Preferências</dt><dd className="whitespace-pre-wrap">{c.preferences || "—"}</dd></div>
              <div className="col-span-2"><dt className="label">Observações</dt><dd className="whitespace-pre-wrap">{c.notes || "—"}</dd></div>
            </dl>
          </Card>
          <div className="space-y-4">
            <Card title="Serviços realizados">
              {p.services.length ? (
                <ul className="space-y-1 text-sm">{p.services.map((s: any) => <li key={s.name} className="flex justify-between"><span>{s.name}</span><Badge color="blue">{s.count}x</Badge></li>)}</ul>
              ) : <p className="text-sm text-slate-500">Nenhum atendimento concluído.</p>}
            </Card>
            <Card title="Relacionamento">
              <p className="text-sm">Estágio no funil: <Badge color="violet">{p.crm.stage || "—"}</Badge></p>
              <p className="mt-2 text-sm text-slate-500">Faltas: {p.stats.no_shows} · Cancelamentos: {p.stats.cancellations}</p>
            </Card>
          </div>
        </div>
      )}

      {tab === "agendamentos" && (
        <Card padded={false}>
          <DataTable rows={p.appointments} onRowClick={(r) => navigate(`/agenda?data=${isoDay(new Date(r.start_at))}&agendamento=${r.id}`)} columns={[
            { key: "start_at", label: "Data", render: (r) => dateTime(r.start_at) },
            { key: "service", label: "Serviço" },
            { key: "professional", label: "Profissional" },
            { key: "price", label: "Valor", render: (r) => (r.package_id ? <Badge color="pink">Pacote</Badge> : money(r.price)) },
            { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
          ]} />
        </Card>
      )}

      {tab === "pacotes" && (
        <Card padded={false}>
          <DataTable rows={p.packages} onRowClick={() => navigate(`/pacotes?cliente=${c.id}`)} columns={[
            { key: "name", label: "Pacote" },
            { key: "service", label: "Serviço" },
            { key: "s", label: "Sessões", render: (r) => `${r.sessions_used}/${r.sessions_total} (restam ${r.sessions_remaining})` },
            { key: "purchased_at", label: "Contratação", render: (r) => date(r.purchased_at) },
            { key: "expires_at", label: "Vencimento", render: (r) => date(r.expires_at) },
            { key: "price", label: "Valor", render: (r) => money(r.price) },
            { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
          ]} />
        </Card>
      )}

      {tab === "financeiro" && (
        <Card padded={false}>
          <DataTable rows={p.receivables} columns={[
            { key: "due_date", label: "Vencimento", render: (r) => date(r.due_date) },
            { key: "description", label: "Descrição" },
            { key: "amount", label: "Valor", render: (r) => money(r.amount) },
            { key: "paid", label: "Pago", render: (r) => money(r.paid) },
            { key: "balance", label: "Saldo", render: (r) => money(r.balance) },
            { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
          ]} />
        </Card>
      )}

      {tab === "notas" && (
        <Card padded={false}>
          <DataTable rows={p.invoices} onRowClick={(r) => can("fiscal.read") && navigate(`/fiscal/notas/${r.id}`)} columns={[
            { key: "number", label: "Número", render: (r) => r.number || "—" },
            { key: "competence_date", label: "Competência", render: (r) => date(r.competence_date) },
            { key: "amount", label: "Valor", render: (r) => money(r.amount) },
            { key: "environment", label: "Ambiente" },
            { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
          ]} />
        </Card>
      )}

      {tab === "contatos" && (
        <Card title="Histórico de contatos" actions={can("crm.write") && <Button size="sm" onClick={() => setContact(true)}>Registrar contato</Button>}>
          {p.interactions.length === 0 ? <Empty title="Nenhum contato registrado" /> : (
            <ol className="space-y-2">
              {p.interactions.map((i: any) => (
                <li key={i.id} className="rounded-xl border border-slate-100 p-3 text-sm dark:border-slate-800">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{i.subject}</span>
                    <span className="text-xs text-slate-500">{KINDS[i.kind] || i.kind} {i.direction ? `· ${i.direction}` : ""} · {dateTime(i.occurred_at)}</span>
                  </div>
                  {i.summary && <p className="mt-1 whitespace-pre-wrap text-slate-600 dark:text-slate-300">{i.summary}</p>}
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}

      {tab === "lgpd" && <LgpdTab customer={c} consents={p.consents} onAnonymize={() => setAnonymize(true)} reload={() => q.refetch()} />}

      <CustomerForm open={editing} onClose={() => setEditing(false)} customer={c} onSaved={() => q.refetch()} />
      {contact && <ContactForm customerId={c.id} onClose={() => { setContact(false); q.refetch(); }} />}
      <Modal open={anonymize} onClose={() => setAnonymize(false)} title="Anonimizar dados do cliente" size="sm"
        footer={<Button variant="secondary" onClick={() => setAnonymize(false)}>Fechar</Button>}>
        <AnonymizeForm id={c.id} onDone={() => { setAnonymize(false); q.refetch(); }} />
      </Modal>
    </div>
  );
}

function LgpdTab({ customer, consents, onAnonymize, reload }: { customer: any; consents: any[]; onAnonymize: () => void; reload: () => void }) {
  const { can } = useAuth();
  const set = useAction((v: { type: string; granted: boolean }) => post(`/customers/${customer.id}/consents`, { consent_type: v.type, granted: v.granted, source: "presencial" }),
    { success: "Consentimento registrado.", onDone: reload });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Consentimentos">
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {consents.map((c) => (
            <li key={c.type} className="flex items-center justify-between gap-3 py-2.5 text-sm">
              <div>
                <p className="font-medium">{c.label}</p>
                <p className="text-xs text-slate-500">{c.updated_at ? `Atualizado em ${dateTime(c.updated_at)} (${c.source})` : "Nunca registrado"}</p>
              </div>
              <div className="flex items-center gap-2">
                <Badge color={c.granted ? "green" : "gray"}>{c.granted ? "Concedido" : "Não concedido"}</Badge>
                {can("customers.write") && customer.status !== "anonimizado" && (
                  <Button size="sm" variant="secondary" loading={set.isPending} onClick={() => set.mutate({ type: c.type, granted: !c.granted })}>
                    {c.granted ? "Revogar" : "Conceder"}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-slate-500">Cada alteração fica registrada (data, origem e responsável) como prova do consentimento.</p>
      </Card>
      <Card title="Direitos do titular">
        <div className="space-y-3 text-sm">
          <p>Exporte todos os dados do cliente (acesso/portabilidade) ou anonimize o cadastro quando legalmente cabível. Registros fiscais e financeiros são mantidos pelo prazo legal.</p>
          {can("customers.lgpd") ? (
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" icon={<Download className="h-4 w-4" />} onClick={() => download(`/customers/${customer.id}/export`)}>Exportar dados (JSON)</Button>
              {customer.status !== "anonimizado" && <Button variant="danger" onClick={onAnonymize}>Anonimizar</Button>}
            </div>
          ) : <Alert kind="info">Somente usuários com permissão de LGPD podem exportar ou anonimizar.</Alert>}
        </div>
      </Card>
    </div>
  );
}

function AnonymizeForm({ id, onDone }: { id: string; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const run = useAction(() => post(`/customers/${id}/anonymize`, { confirmation: "ANONIMIZAR", reason }), { onDone });
  return (
    <div className="space-y-3 text-sm">
      <Alert kind="warning">Ação irreversível: nome, contatos, documentos, endereço e dados de saúde serão removidos. Notas fiscais e lançamentos financeiros permanecem por obrigação legal.</Alert>
      <Field label="Motivo / solicitação do titular" required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <ConfirmButton message="Confirma a anonimização definitiva deste cliente?" requireText="ANONIMIZAR" confirmLabel="Anonimizar" onConfirm={() => run.mutateAsync(undefined)}>
        Anonimizar definitivamente
      </ConfirmButton>
    </div>
  );
}

export function ContactForm({ customerId, leadId, onClose }: { customerId?: string; leadId?: string; onClose: () => void }) {
  const [f, setF] = useState({ kind: "ligacao", direction: "saida", subject: "", summary: "" });
  const save = useAction(() => post("/crm/interactions", { customer_id: customerId || null, lead_id: leadId || null, ...f }), { success: "Contato registrado.", onDone: onClose });
  return (
    <Modal open onClose={onClose} title="Registrar contato" size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={save.isPending} disabled={f.subject.length < 2} onClick={() => save.mutate(undefined)}>Salvar</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Tipo"><Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          {Object.entries(KINDS).filter(([k]) => k !== "sistema").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select></Field>
        <Field label="Direção"><Select value={f.direction} onChange={(e) => setF({ ...f, direction: e.target.value })}><option value="saida">Clínica → cliente</option><option value="entrada">Cliente → clínica</option></Select></Field>
        <Field label="Assunto" required className="sm:col-span-2"><Input value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} /></Field>
        <Field label="Resumo" className="sm:col-span-2"><Textarea value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} /></Field>
      </div>
    </Modal>
  );
}
