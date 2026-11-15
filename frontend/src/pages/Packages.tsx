import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CustomerPicker } from "../components/shared";
import { Alert, Badge, Button, Card, Checkbox, DataTable, Drawer, Field, Input, Modal, PageHeader, Select, StatusBadge, Tabs, Textarea } from "../components/ui";
import { get, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { date, dateTime, isoDay, money } from "../lib/format";
import { useAction, useGet, useLookups } from "../lib/hooks";

export default function Packages() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const [tab, setTab] = useState(params.get("alerta") || "ativo");
  const [selling, setSelling] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [customerFilter, setCustomerFilter] = useState<any>(null);
  useEffect(() => {
    const cid = params.get("cliente");
    if (cid) get(`/customers/${cid}`).then((c) => setCustomerFilter({ id: c.id, full_name: c.full_name })).catch(() => undefined);
  }, [params]);
  const isAlert = tab === "low_balance" || tab === "expiring";
  const list = useGet<any[]>(["packages"], "/packages", isAlert ? { alert: tab } : { status: tab === "todos" ? undefined : tab, customer_id: customerFilter?.id });
  return (
    <div>
      <PageHeader title="Pacotes e planos" subtitle="Sessões são baixadas somente após a conclusão do atendimento."
        actions={can("packages.write") && <Button onClick={() => setSelling(true)}>Vender pacote</Button>} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { key: "ativo", label: "Ativos" }, { key: "low_balance", label: "Saldo baixo" }, { key: "expiring", label: "Vencendo" },
        { key: "concluido", label: "Concluídos" }, { key: "expirado", label: "Expirados" }, { key: "cancelado", label: "Cancelados" }, { key: "todos", label: "Todos" },
      ]} />
      {!isAlert && <div className="mb-3 max-w-md"><CustomerPicker value={customerFilter} onChange={setCustomerFilter} allowCreate={false} /></div>}
      <Card padded={false}>
        <DataTable rows={list.data || []} onRowClick={(r) => setOpen(r.id)} columns={[
          { key: "customer_name", label: "Cliente", render: (r) => <span className="font-medium">{r.customer_name}</span> },
          { key: "name", label: "Pacote" },
          { key: "service_name", label: "Serviço" },
          { key: "s", label: "Sessões", render: (r) => (
            <div className="min-w-[120px]">
              <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800"><div className="h-1.5 rounded-full bg-brand-600" style={{ width: `${(r.sessions_used / r.sessions_total) * 100}%` }} /></div>
              <p className="mt-1 text-xs text-slate-500">{r.sessions_used} de {r.sessions_total} · restam {r.sessions_remaining}{r.reserved ? ` (${r.reserved} agendada)` : ""}</p>
            </div>) },
          { key: "price", label: "Valor", render: (r) => money(r.price) },
          { key: "purchased_at", label: "Contratação", render: (r) => date(r.purchased_at) },
          { key: "expires_at", label: "Vencimento", render: (r) => date(r.expires_at) },
          { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
        ]} />
      </Card>
      {selling && <SellForm onClose={() => setSelling(false)} />}
      {open && <PackageDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function SellForm({ onClose }: { onClose: () => void }) {
  const { can } = useAuth();
  const { services, methods } = useLookups();
  const plans = useGet<any[]>(["package-plans"], "/package-plans");
  const [customer, setCustomer] = useState<any>(null);
  const [f, setF] = useState<any>({ plan_id: "", service_id: "", name: "", sessions_total: "", price: "", discount: "0", purchased_at: isoDay(), expires_at: "",
    payment_method_id: "", installments: 1, first_due_date: isoDay(), notes: "", receive_now: false });
  const plan = (plans.data || []).find((p) => p.id === f.plan_id);
  useEffect(() => {
    if (plan) setF((x: any) => ({ ...x, service_id: plan.service_id, sessions_total: plan.sessions_count, price: plan.price, name: plan.name }));
  }, [plan]);
  const save = useAction(() => post("/packages", {
    customer_id: customer.id, plan_id: f.plan_id || null, service_id: f.plan_id ? null : f.service_id, name: f.name || null,
    sessions_total: f.sessions_total ? Number(f.sessions_total) : null, price: f.price !== "" ? String(f.price) : null, discount: String(f.discount || 0),
    purchased_at: f.purchased_at, expires_at: f.expires_at || null, payment_method_id: f.payment_method_id || null,
    installments: Number(f.installments), first_due_date: f.first_due_date, notes: f.notes || null, receive_now: f.receive_now,
  }), { success: "Pacote vendido e lançado em contas a receber.", invalidate: [["packages"]], onDone: onClose });
  return (
    <Modal open onClose={onClose} title="Vender pacote" size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={save.isPending} disabled={!customer || (!f.plan_id && (!f.service_id || !f.sessions_total || f.price === ""))} onClick={() => save.mutate(undefined)}>Confirmar venda</Button></>}>
      <div className="grid gap-3 sm:grid-cols-6">
        <Field label="Cliente" required className="sm:col-span-6"><CustomerPicker value={customer} onChange={setCustomer} /></Field>
        <Field label="Plano" className="sm:col-span-3"><Select value={f.plan_id} onChange={(e) => setF({ ...f, plan_id: e.target.value })}><option value="">Personalizado</option>{(plans.data || []).filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.name} · {money(p.price)}</option>)}</Select></Field>
        <Field label="Serviço" required className="sm:col-span-3"><Select value={f.service_id} disabled={!!f.plan_id} onChange={(e) => setF({ ...f, service_id: e.target.value })}><option value="">Selecione</option>{services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
        <Field label="Nome do pacote" className="sm:col-span-3"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Sessões" required className="sm:col-span-1"><Input type="number" min={1} value={f.sessions_total} onChange={(e) => setF({ ...f, sessions_total: e.target.value })} /></Field>
        <Field label="Valor (R$)" required className="sm:col-span-1"><Input type="number" step="0.01" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} /></Field>
        <Field label="Desconto" className="sm:col-span-1"><Input type="number" step="0.01" value={f.discount} onChange={(e) => setF({ ...f, discount: e.target.value })} /></Field>
        <Field label="Contratação" className="sm:col-span-2"><Input type="date" value={f.purchased_at} onChange={(e) => setF({ ...f, purchased_at: e.target.value })} /></Field>
        <Field label="Vencimento" hint={plan?.validity_days ? `Padrão do plano: ${plan.validity_days} dias` : undefined} className="sm:col-span-2"><Input type="date" value={f.expires_at} onChange={(e) => setF({ ...f, expires_at: e.target.value })} /></Field>
        <Field label="Forma de pagamento" className="sm:col-span-2"><Select value={f.payment_method_id} onChange={(e) => setF({ ...f, payment_method_id: e.target.value })}><option value="">—</option>{methods.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field>
        <Field label="Parcelas" className="sm:col-span-2"><Input type="number" min={1} max={24} value={f.installments} onChange={(e) => setF({ ...f, installments: e.target.value })} /></Field>
        <Field label="1º vencimento" className="sm:col-span-2"><Input type="date" value={f.first_due_date} onChange={(e) => setF({ ...f, first_due_date: e.target.value })} /></Field>
        <Field label="Observações" className="sm:col-span-6"><Textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        {can("finance.payments") && <div className="sm:col-span-6"><Checkbox label="Registrar agora o recebimento da 1ª parcela (ou valor total)" checked={f.receive_now} onChange={(v) => setF({ ...f, receive_now: v })} /></div>}
        <div className="sm:col-span-6"><Alert kind="info">A venda gera a conta a receber do pacote. Os atendimentos realizados com o pacote não geram nova cobrança nem nova nota fiscal.</Alert></div>
      </div>
    </Modal>
  );
}

function PackageDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useAuth();
  const navigate = useNavigate();
  const q = useGet<any>(["package", id], `/packages/${id}`);
  const [reason, setReason] = useState("");
  const [revertId, setRevertId] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const cancel = useAction(() => post(`/packages/${id}/cancel`, { reason }), { invalidate: [["packages"], ["package", id]], onDone: () => setCancelling(false) });
  const revert = useAction(() => post(`/packages/sessions/${revertId}/revert`, { reason }), { invalidate: [["packages"], ["package", id]], onDone: () => setRevertId(null) });
  const p = q.data?.package;
  return (
    <Drawer open onClose={onClose} title="Pacote">
      {!p ? <p className="text-sm text-slate-500">Carregando...</p> : (
        <div className="space-y-4 text-sm">
          <div className="flex items-start justify-between">
            <div><p className="text-lg font-semibold">{p.name}</p><p className="text-slate-500">{p.customer_name} · {p.service_name}</p></div>
            <StatusBadge status={p.status} />
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded-xl bg-slate-50 p-2 dark:bg-slate-800/60"><p className="text-xl font-semibold">{p.sessions_total}</p><p className="text-xs text-slate-500">contratadas</p></div>
            <div className="rounded-xl bg-slate-50 p-2 dark:bg-slate-800/60"><p className="text-xl font-semibold">{p.sessions_used}</p><p className="text-xs text-slate-500">utilizadas</p></div>
            <div className="rounded-xl bg-brand-50 p-2 dark:bg-brand-900/30"><p className="text-xl font-semibold">{p.sessions_remaining}</p><p className="text-xs text-slate-500">restantes</p></div>
          </div>
          <dl className="grid grid-cols-2 gap-2">
            <div><dt className="label">Valor</dt><dd>{money(p.price)}</dd></div>
            <div><dt className="label">Vencimento</dt><dd>{date(p.expires_at)}</dd></div>
            <div className="col-span-2"><dt className="label">Regras</dt><dd>{p.no_show_consumes ? "Falta desconta sessão" : "Falta não desconta"}; {p.late_cancel_consumes ? `cancelamento com menos de ${p.late_cancel_hours}h desconta` : "cancelamento não desconta"}.</dd></div>
          </dl>
          <div>
            <p className="mb-1 font-semibold">Sessões baixadas</p>
            {q.data.sessions.length === 0 ? <p className="text-slate-500">Nenhuma.</p> : (
              <ul className="space-y-1">
                {q.data.sessions.map((s: any) => (
                  <li key={s.id} className="flex items-center justify-between rounded-lg bg-slate-50 px-2 py-1.5 dark:bg-slate-800/50">
                    <span>{dateTime(s.appointment_start || s.consumed_at)} · <Badge color={s.reason === "atendimento" ? "green" : "yellow"}>{s.reason}</Badge> {s.reverted_at && <Badge color="gray">revertida</Badge>}</span>
                    {can("packages.write") && !s.reverted_at && <Button size="sm" variant="ghost" onClick={() => { setReason(""); setRevertId(s.id); }}>Reverter</Button>}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {q.data.scheduled.length > 0 && <p>Agendadas com este pacote: {q.data.scheduled.map((a: any) => dateTime(a.start_at)).join(", ")}</p>}
          {q.data.receivables && (
            <div>
              <p className="mb-1 font-semibold">Financeiro</p>
              <DataTable rows={q.data.receivables} columns={[
                { key: "due_date", label: "Vencimento", render: (r) => date(r.due_date) },
                { key: "amount", label: "Valor", render: (r) => money(r.amount) },
                { key: "paid", label: "Pago", render: (r) => money(r.paid) },
                { key: "status", label: "", render: (r) => <StatusBadge status={r.status} /> },
              ]} />
            </div>
          )}
          <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
            {can("agenda.write") && p.status === "ativo" && <Button size="sm" onClick={() => navigate(`/agenda?novo=1&cliente=${p.customer_id}&nome=${encodeURIComponent(p.customer_name)}`)}>Agendar sessão</Button>}
            {can("fiscal.issue") && <Button size="sm" variant="secondary" onClick={() => navigate(`/fiscal/emissao?pacote=${p.id}`)}>Emitir NFS-e do pacote</Button>}
            {can("packages.write") && p.status !== "cancelado" && <Button size="sm" variant="danger" onClick={() => { setReason(""); setCancelling(true); }}>Cancelar pacote</Button>}
          </div>
        </div>
      )}
      <Modal open={cancelling || !!revertId} onClose={() => { setCancelling(false); setRevertId(null); }} title={cancelling ? "Cancelar pacote" : "Reverter baixa de sessão"} size="sm"
        footer={<Button variant="danger" loading={cancel.isPending || revert.isPending} disabled={reason.length < 5} onClick={() => (cancelling ? cancel.mutate(undefined) : revert.mutate(undefined))}>Confirmar</Button>}>
        <Field label="Motivo" required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>
    </Drawer>
  );
}
